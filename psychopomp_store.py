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
import time
from email.message import EmailMessage
from pathlib import Path

try:
    from . import psychopomp_core as core
except ImportError:  # loaded as a top-level module (Desktop backend, tests)
    import psychopomp_core as core

log = logging.getLogger("psychopomp")
PLUGIN_ID = "psychopomp"

SETTINGS = {  # key -> (default, cast); mirrored in plugin.yaml config_schema
    "owner_name": ("", str),
    "owner_channels": ("", str),
    "trusted_name": ("", str),
    "trusted_channels": ("", str),
    "silence_days": (30, int),
    "checkin_every_days": (3, int),
    "checkins": (3, int),
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
    for k in ("silence_days", "checkin_every_days", "checkins"):
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


def perform(actions: list) -> None:
    """Carry out actions from the core. Failures are logged; letters retry on the next tick."""
    for a in actions:
        try:
            if a["type"] == "send":
                send_to(a["target"], a["text"])
            elif a["type"] == "letter":
                send_email(a["to"], a["subject"], a["body"])
                with locked_state() as s:
                    core.mark_delivered(s, a["id"])
        except Exception as exc:  # noqa: BLE001 - a dead channel must not stop the others
            log.warning("psychopomp: could not carry %s: %s", a.get("target") or a.get("to"), exc)
            with locked_state() as s:
                core._log(s, time.time(), f"Could not reach {a.get('target') or a.get('to')}: {exc}")
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
    if not state["trusted"]["channels"]:
        issues.append("No trusted contact channels: nobody can confirm, so letters can never be carried.")
    if not smtp_ready():
        issues.append("Email is not set up (EMAIL_ADDRESS, EMAIL_PASSWORD, EMAIL_SMTP_HOST): letters travel by email.")
    if not state["letters"]:
        issues.append("No sealed letters yet.")
    if not state.get("armed"):
        issues.append("The switch is not armed.")
    if state.get("day_seconds", core.DAY) < core.DAY:
        issues.append("Demo mode is on: a day lasts one minute.")
    try:
        import subprocess
        out = subprocess.run(["pmset", "-g"], capture_output=True, text=True, timeout=5).stdout
        if any(line.split()[:1] == ["sleep"] and line.split()[1] != "0" for line in out.splitlines()):
            issues.append("This Mac goes to sleep. The switch only runs while Hermes is awake; "
                          "install Psychopomp on an always-on Hermes (a server) for real use.")
    except Exception:
        pass
    return issues
