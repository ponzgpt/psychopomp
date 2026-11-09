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
import sys
import threading
import time
from pathlib import Path

try:
    from . import psychopomp_core as core
except ImportError:  # loaded as a top-level module (Desktop backend, tests)
    import psychopomp_core as core

log = logging.getLogger("psychopomp")
PLUGIN_ID = "psychopomp"
REHEARSAL_SECONDS_PER_DAY = 2.0

SETTINGS = {  # key -> default; plugin.yaml config_schema shows the first two
    "owner_name": "",
    "silence_days": 30,
    "owner_channels": "",  # legacy (≤0.2): now set by sending /psychopomp here
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
    """Copy the two settings (Settings › Plugins › Psychopomp) into the state. Where Hermes reaches you comes
    from /psychopomp here and your witness from the invitation, so both live in the state."""
    if str(settings.get("owner_name") or "").strip():
        state["owner"]["name"] = str(settings["owner_name"]).strip()
    for c in split_channels(settings.get("owner_channels") or ""):
        if not core._in(c, state["owner"]["channels"]):
            state["owner"]["channels"].append(c)
    try:
        state["silence_days"] = max(1, int(settings.get("silence_days") or 30))
    except (TypeError, ValueError):
        pass


# --- carrying messages ------------------------------------------------------

def send_to(target: str, text: str) -> None:
    """One message to ``platform:ref`` through Hermes' own delivery."""
    # ponytail: tools.send_message_tool is not on Hermes' public-import list yet; it is what
    # `hermes send` uses. Swap for a public send API when one ships.
    from tools.send_message_tool import send_message_tool
    result = json.loads(send_message_tool({"action": "send", "target": target, "message": text}) or "{}")
    if result.get("error") or result.get("success") is False:
        raise RuntimeError(result.get("error") or "send failed")


def book_path(state: dict) -> Path:
    name = "".join(ch for ch in core._name(state).title() if ch.isalnum()) or "Hermes"
    return data_dir() / f"The-Book-of-{name}.html"


def send_book(targets: list, intro: str, state: dict) -> None:
    """The Book as one HTML file (opens on any phone, prints well); plain text where files can't go."""
    path = book_path(state)
    path.write_text(core.render_book(state))
    for t in targets:
        try:
            send_to(t, f"{intro}\n[[as_document]]\nMEDIA:{path}")
        except Exception:
            send_to(t, intro + "\n\n" + "\n\n".join(f"{p['title']}\n{p['text']}" for p in state["book"]["pages"]))


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
                        send_to(t, a["text"])
                        ok = True
                    except Exception as exc:  # noqa: BLE001
                        log.warning("psychopomp: letter to %s failed: %s", t, exc)
                if not ok:  # the recipient's channel failed: the witness passes it on
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
                send_book(a["targets"], a["intro"], read_state())
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
    """Plain-language problems that would stop Psychopomp from keeping watch."""
    issues = []
    if not state["owner"]["channels"]:
        issues.append("Hermes has nowhere to reach you yet: send /psychopomp here from your phone (Telegram, …).")
    if not core.trusted_channels(state):
        issues.append("No witness yet: run /psychopomp invite <their name> and send them the message.")
    if not state["letters"] and not state["book"]["pages"]:
        issues.append("Nothing to carry yet: no pages in your Book and no sealed letters.")
    if not state.get("armed"):
        issues.append("Hermes is not keeping watch yet: /psychopomp watch.")
    if sys.platform == "darwin":
        issues.append("Hermes is running on a Mac, which sleeps. For real use, install Psychopomp on an "
                      "always-on Hermes (Hermes Cloud or a server).")
    return issues


# --- rehearsal runner ------------------------------------------------------------

def start_rehearsal(seconds_per_day: float = REHEARSAL_SECONDS_PER_DAY, *, mirror: bool = False,
                    on_step=None):
    """Play the passage on a virtual clock in a background thread. Returns (message, thread or None).
    ``on_step(card)`` gets the chat card after each day worth showing (the chat surfaces edit one message
    with it); the Desktop page polls the state instead; ``mirror`` also sends each step to your channels."""
    with locked_state() as s:
        if (s.get("rehearsal") or {}).get("status") == "running":
            return "A rehearsal is already running.", None
        actions = core.rehearsal_start(s, time.time(), mirror=mirror)
        card = core.rehearsal_card(s)
    perform(actions)
    if on_step:
        on_step(card)

    def run():  # quiet days fly by; days with something to say get time to be read
        acts, quiet = actions, 0
        while True:
            time.sleep(seconds_per_day if acts else 0.15)
            with locked_state() as s:
                acts = core.rehearsal_step(s, time.time())
                status, card = s["rehearsal"]["status"], core.rehearsal_card(s)
            perform(acts)
            notify_desktop()
            quiet = 0 if acts else quiet + 1
            if on_step and (acts or quiet % 8 == 0 or status != "running"):
                try:
                    on_step(card)
                except Exception as exc:  # noqa: BLE001 - a failed edit must not stop the clock
                    log.debug("psychopomp: rehearsal edit failed: %s", exc)
            if status != "running":
                return

    thread = threading.Thread(target=run, name="psychopomp-rehearsal", daemon=True)
    thread.start()
    return "Rehearsal started.", thread


def rehearse_now() -> str:
    """The whole rehearsal at once, up to your witness's turn: for surfaces that can't show it live."""
    with locked_state() as s:
        core.rehearsal_start(s, time.time(), mirror=False)
        while s["rehearsal"]["status"] == "running":
            core.rehearsal_step(s, time.time())
        card = core.rehearsal_card(s)
    notify_desktop()
    return card


def stop_rehearsal() -> bool:
    with locked_state() as s:
        ok = core.rehearsal_stop(s, time.time())
    notify_desktop()
    return ok


def confirm_rehearsal(code: str) -> str:
    with locked_state() as s:
        reh = s.get("rehearsal") or {}
        ok = reh.get("status") == "awaiting_code" and code.strip().upper() == (reh.get("sim") or {}).get("code")
        actions = core.rehearsal_confirm(s, time.time()) if ok else []
        card = core.rehearsal_card(s)
    perform(actions)
    notify_desktop()
    return card if ok else "No rehearsal is waiting for that code."


def set_owner_channel(channel: str) -> None:
    with locked_state() as s:
        s["owner"]["channels"] = [channel]
        core.heartbeat(s)
        core._log(s, time.time(), f"Hermes will reach you on {channel.split(':')[0].capitalize()}.")
    notify_desktop()
