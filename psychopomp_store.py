"""Psychopomp I/O: the state file, settings, and carrying messages out.

Shared by the agent half (``__init__.py``) and the Desktop backend
(``dashboard/plugin_api.py``), which may run in different processes, so every
read-modify-write holds an exclusive file lock.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import os
import smtplib
import ssl
import threading
import sys
import time
from email.message import EmailMessage
from pathlib import Path

try:
    from . import psychopomp_core as core
except ImportError:  # loaded as a top-level module (Desktop backend, tests)
    import psychopomp_core as core

log = logging.getLogger("psychopomp")
PLUGIN_ID = "psychopomp"
REHEARSAL_SECONDS_PER_DAY = 2.0

SETTINGS = {  # key -> (default, cast); mirrored in plugin.yaml config_schema
    "owner_name": ("", str),
    "owner_channels": ("", str),
    "trusted_name": ("", str),
    "trusted_channels": ("", str),
    "silence_days": (30, int),
    "checkin_every_days": (3, int),
    "checkins": (3, int),
    "review_every_days": (7, int),
    "demo_mode": (False, bool),
}


def data_dir() -> Path:
    try:
        from plugins.plugin_storage import plugin_data_dir
        path = Path(plugin_data_dir(PLUGIN_ID))
    except Exception:  # running outside Hermes (tests, scripts)
        path = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")) / "plugin-data" / PLUGIN_ID
    path.mkdir(parents=True, exist_ok=True)
    return path


@contextlib.contextmanager
def locked_state():
    """Yield the state dict under an exclusive lock and save it on exit."""
    d = data_dir()
    with open(d / "state.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = d / "state.json"
        try:
            state = json.loads(path.read_text()) if path.exists() else core.new_state()
        except ValueError:
            log.error("psychopomp: state.json unreadable; keeping a copy and starting fresh")
            path.rename(d / f"state.broken.{int(time.time())}.json")
            state = core.new_state()
        yield state
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=1))
        os.replace(tmp, path)


def read_state() -> dict:
    with locked_state() as s:
        return json.loads(json.dumps(s))


def split_channels(text: str) -> list:
    return [c.strip() for c in (text or "").replace("\n", ",").split(",") if ":" in c]


def apply_settings(state: dict, settings: dict) -> None:
    """Copy plugin settings (Settings › Plugins › Psychopomp) into the state."""
    get = lambda k: SETTINGS[k][1](settings.get(k, SETTINGS[k][0]) or SETTINGS[k][0])  # noqa: E731
    state["owner"] = {"name": get("owner_name"), "channels": split_channels(get("owner_channels"))}
    state["trusted"] = {"name": get("trusted_name"), "channels": split_channels(get("trusted_channels"))}
    for k in ("silence_days", "checkin_every_days", "checkins", "review_every_days"):
        state[k] = max(1, get(k))
    state["day_seconds"] = 60.0 if get("demo_mode") else core.DAY


# --- carrying messages ------------------------------------------------------

def _secret(name: str, default: str = "") -> str:
    try:
        from agent.secret_scope import get_secret
        return get_secret(name, default) or default
    except Exception:
        return os.environ.get(name, default)


def smtp_ready() -> bool:
    return all(_secret(k) for k in ("EMAIL_ADDRESS", "EMAIL_PASSWORD", "EMAIL_SMTP_HOST"))


def send_email(to: str, subject: str, body: str) -> None:
    """Plain SMTP with Hermes' own email settings, so letters keep their subject."""
    msg = EmailMessage()
    msg["From"] = _secret("EMAIL_ADDRESS")
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    host, port = _secret("EMAIL_SMTP_HOST"), int(_secret("EMAIL_SMTP_PORT", "587"))
    ctx = ssl.create_default_context()
    if port == 465:
        server = smtplib.SMTP_SSL(host, port, context=ctx, timeout=30)
    else:
        server = smtplib.SMTP(host, port, timeout=30)
        server.starttls(context=ctx)
    with server:
        server.login(_secret("EMAIL_ADDRESS"), _secret("EMAIL_PASSWORD"))
        server.send_message(msg)


def send_to(target: str, text: str) -> None:
    """One message to ``platform:ref`` through Hermes' own delivery; email goes over SMTP."""
    platform, _, ref = target.partition(":")
    if platform.lower() == "email":
        return send_email(ref, "Hermes, from Psychopomp", text)
    # ponytail: tools.send_message_tool is not on Hermes' public-import list yet; it is what
    # `hermes send` uses. Swap for a public send API when one ships.
    from tools.send_message_tool import send_message_tool
    result = json.loads(send_message_tool({"action": "send", "target": target, "message": text}) or "{}")
    if result.get("error") or result.get("success") is False:
        raise RuntimeError(result.get("error") or "send failed")


def _deliver_to(target: str, text: str, subject: str = "") -> None:
    if target.lower().startswith("email:") and subject:
        return send_email(target.partition(":")[2], subject, text)
    send_to(target, text)


def send_book(targets: list, intro: str, book_md: str) -> None:
    """The Book as a document where the channel allows it, else as text."""
    path = data_dir() / "The-Book.md"
    path.write_text(book_md)
    for t in targets:
        try:
            send_to(t, f"{intro}\n[[as_document]]\nMEDIA:{path}")
        except Exception:
            send_to(t, f"{intro}\n\n{book_md}")


def perform(actions: list) -> None:
    """Carry out actions from the core. Failures are logged; letters retry on the next tick."""
    for a in actions:
        try:
            if a["type"] == "send":
                send_to(a["target"], a["text"])
            elif a["type"] == "letter":
                ok = False
                for t in a["targets"]:
                    try:
                        _deliver_to(t, a["text"], a["subject"])
                        ok = True
                    except Exception as exc:  # noqa: BLE001
                        log.warning("psychopomp: letter to %s failed: %s", t, exc)
                if not ok:  # the recipient's channel failed: the trusted contact passes it on
                    with locked_state() as s:
                        fallback = [c for c in core.trusted_channels(s) if c not in a["targets"]]
                    for t in fallback:
                        try:
                            send_to(t, f"I could not reach {a['to_name']} directly. Please pass this on.\n\n"
                                       + a["text"])
                            ok = True
                        except Exception as exc:  # noqa: BLE001
                            log.warning("psychopomp: fallback to %s failed: %s", t, exc)
                if ok:
                    with locked_state() as s:
                        core.mark_delivered(s, a["id"])
            elif a["type"] == "book":
                with locked_state() as s:
                    md = core.render_book(s)
                send_book(a["targets"], a["intro"], md)
        except Exception as exc:  # noqa: BLE001 - a dead channel must not stop the others
            where = a.get("target") or ", ".join(a.get("targets", []))
            log.warning("psychopomp: could not carry to %s: %s", where, exc)
            with locked_state() as s:
                core._log(s, time.time(), f"Could not reach {where}: {exc}")
    if actions:
        notify_desktop()


def notify_desktop() -> None:
    try:
        from hermes_cli.plugin_events import broadcast_plugin_event
        broadcast_plugin_event(PLUGIN_ID, "state.changed", {})
    except Exception:
        pass


def doctor(state: dict) -> list:
    """Plain-language problems that would stop the switch from working."""
    issues = []
    if not state["owner"]["channels"]:
        issues.append("No owner channels: Hermes has nowhere to send your check-ins.")
    if not core.trusted_channels(state):
        issues.append("No trusted contact yet: run /psychopomp invite and send them the code.")
    if any(l["to_target"].startswith("email:") for l in state["letters"]) and not smtp_ready():
        issues.append("Some letters go by email but email is not set up (EMAIL_ADDRESS, EMAIL_PASSWORD, "
                      "EMAIL_SMTP_HOST). They will be handed to your trusted contact instead if email fails.")
    if not state["letters"] and not state["book"]["pages"]:
        issues.append("Nothing to carry yet: no pages in your Book and no sealed letters.")
    if not state.get("armed"):
        issues.append("The switch is not armed.")
    if state.get("day_seconds", core.DAY) < core.DAY:
        issues.append("Demo mode is on: a day lasts one minute.")
    if sys.platform == "darwin":
        issues.append("Hermes is running on a Mac. The switch only runs while Hermes is awake; "
                      "for real use, install Psychopomp on an always-on Hermes (Hermes Cloud or a server).")
    return issues


# --- rehearsal runner ------------------------------------------------------------

def start_rehearsal(seconds_per_day: float = REHEARSAL_SECONDS_PER_DAY, *, mirror: bool = True,
                    need_channel: bool = True):
    """Play the passage on a virtual clock in a background thread. Returns (message, thread or None).
    The Desktop page watches it live (need_channel=False); chat surfaces need the owner's channel to see it."""
    with locked_state() as s:
        if need_channel and not s["owner"]["channels"]:
            return ("Set where Hermes reaches you first (Settings › Plugins › Psychopomp), or rehearse from the "
                    "Psychopomp page in Hermes Desktop."), None
        if (s.get("rehearsal") or {}).get("status") == "running":
            return "A rehearsal is already running.", None
        actions = core.rehearsal_start(s, time.time(), mirror=mirror)
    perform(actions)

    def run():  # quiet days fly by; days with something to say get time to be read
        acts = actions
        while True:
            time.sleep(seconds_per_day if acts else 0.15)
            with locked_state() as s:
                acts = core.rehearsal_step(s, time.time())
                status = s["rehearsal"]["status"]
            perform(acts)
            notify_desktop()
            if status != "running":
                return

    thread = threading.Thread(target=run, name="psychopomp-rehearsal", daemon=True)
    thread.start()
    return ("Rehearsal started: one virtual day every few seconds. Watch your messages; when Hermes asks, "
            "reply with the code on any channel to play your trusted contact."), thread


def stop_rehearsal() -> bool:
    with locked_state() as s:
        ok = core.rehearsal_stop(s, time.time())
    notify_desktop()
    return ok


def confirm_rehearsal(code: str) -> str:
    with locked_state() as s:
        actions, handled = core.inbound(s, "rehearsal:owner", code)
    perform(actions)
    return "Rehearsal confirmed." if handled else "No rehearsal is waiting for that code."
