"""Psychopomp core: the dead man's switch as a pure state machine.

No Hermes imports here, so it is testable with the stdlib alone. Every
function takes the state dict and a clock value and returns actions; the
plugin layer (``__init__.py``) persists the state and performs the actions.

Phases:
    watching          -> the owner is around; nothing to do
    checking_in       -> silent too long; ask the owner "are you there?"
    awaiting_trusted  -> no answer; the trusted contact got a code
    delivered         -> the trusted contact confirmed; letters were sent

The owner speaking on any surface resets everything to ``watching``.
Letters are never delivered without the trusted contact's code.
"""

from __future__ import annotations

import re
import secrets
import time
import uuid

DAY = 86400.0

DEFAULTS = {
    "silence_days": 30,       # days without a word before the first check-in
    "checkin_every_days": 3,  # days between check-ins
    "checkins": 3,            # check-ins to the owner before the trusted contact is asked
    "day_seconds": DAY,       # time dilation: 60 makes a "day" last a minute (demo mode)
}


def new_state(now: float | None = None) -> dict:
    now = time.time() if now is None else now
    return {
        **DEFAULTS,
        "armed": False,
        "owner": {"name": "", "channels": []},
        "trusted": {"name": "", "channels": []},
        "last_seen": now,
        "phase": "watching",
        "checkins_sent": 0,
        "last_checkin_at": None,
        "code": None,
        "trusted_asked_at": None,
        "letters": [],
        "log": [],
    }


# --- small helpers ---------------------------------------------------------

def _days(state: dict, seconds: float) -> float:
    return seconds / float(state.get("day_seconds") or DAY)


def _log(state: dict, now: float, text: str) -> None:
    state["log"] = (state.get("log") or [])[-49:] + [{"at": now, "text": text}]


def _send_all(channels: list, text: str) -> list:
    return [{"type": "send", "target": c, "text": text} for c in channels]


def norm_channel(channel: str) -> str:
    """``Telegram:123`` and ``telegram:123`` are the same sender."""
    platform, _, ident = (channel or "").strip().partition(":")
    return f"{platform.lower()}:{ident.strip().lower()}"


def _in(channel: str, channels: list) -> bool:
    return norm_channel(channel) in {norm_channel(c) for c in channels}


def _new_code() -> str:
    return f"PSY-{secrets.randbelow(900000) + 100000}"


# --- letters ---------------------------------------------------------------

def seal_letter(state: dict, to_name: str, to_email: str, subject: str, body: str,
                now: float | None = None) -> dict:
    """Store a letter. After sealing, only its envelope is ever shown again."""
    if not to_email or "@" not in to_email:
        raise ValueError("a letter needs a recipient email")
    if not (body or "").strip():
        raise ValueError("a letter needs words")
    now = time.time() if now is None else now
    letter = {
        "id": uuid.uuid4().hex[:8],
        "to_name": (to_name or to_email).strip(),
        "to_email": to_email.strip(),
        "subject": (subject or "A letter for you").strip(),
        "body": body,
        "sealed_at": now,
        "delivered_at": None,
    }
    state["letters"].append(letter)
    _log(state, now, f"Sealed a letter for {letter['to_name']}.")
    return envelope(letter)


def envelope(letter: dict) -> dict:
    """What anyone (including the agent) may see of a sealed letter."""
    return {k: letter[k] for k in ("id", "to_name", "to_email", "subject", "sealed_at", "delivered_at")}


def unseal(state: dict, letter_id: str, now: float | None = None) -> bool:
    """Withdraw a letter that has not been delivered yet."""
    before = len(state["letters"])
    state["letters"] = [l for l in state["letters"] if l["id"] != letter_id or l["delivered_at"]]
    if len(state["letters"]) < before:
        _log(state, time.time() if now is None else now, "Withdrew a letter.")
        return True
    return False


# --- the switch ------------------------------------------------------------

def heartbeat(state: dict, now: float | None = None) -> list:
    """The owner did something. Reset the switch; tell the trusted contact if they were asked."""
    now = time.time() if now is None else now
    actions: list = []
    if state["phase"] == "awaiting_trusted":
        actions += _send_all(
            state["trusted"]["channels"],
            f"Good news: {state['owner']['name'] or 'they'} just spoke to Hermes. "
            "Please ignore my earlier message; the code is no longer valid.",
        )
    if state["phase"] in ("checking_in", "awaiting_trusted"):
        _log(state, now, "The owner answered. Back to watching.")
    if state["phase"] != "delivered":
        state.update(phase="watching", checkins_sent=0, last_checkin_at=None,
                     code=None, trusted_asked_at=None)
    state["last_seen"] = now
    return actions


def tick(state: dict, now: float | None = None) -> list:
    """Advance the switch. Call it every few minutes; it is idempotent between thresholds."""
    now = time.time() if now is None else now
    if state["phase"] == "delivered":
        return pending_letters(state)  # retry anything the mail server refused
    if not state.get("armed"):
        return []
    owner = state["owner"]["name"] or "you"
    phase = state["phase"]

    if phase == "watching":
        if _days(state, now - state["last_seen"]) >= state["silence_days"]:
            state.update(phase="checking_in", checkins_sent=0)
            return _checkin(state, now, owner)
        return []

    if phase == "checking_in":
        if _days(state, now - (state["last_checkin_at"] or now)) < state["checkin_every_days"]:
            return []
        if state["checkins_sent"] < state["checkins"]:
            return _checkin(state, now, owner)
        state.update(phase="awaiting_trusted", code=_new_code(), trusted_asked_at=now)
        _log(state, now, f"No answer after {state['checkins']} check-ins. Asked the trusted contact.")
        n = sum(1 for l in state["letters"] if not l["delivered_at"])
        return _send_all(
            state["trusted"]["channels"],
            f"Hello {state['trusted']['name'] or ''}. This is Hermes, {owner}'s agent. "
            f"{owner} has not spoken to me in {state['silence_days']} days and has not answered "
            f"{state['checkins']} check-ins. They asked me to carry {n} sealed letter(s) if this happened. "
            f"If you know {owner} cannot answer anymore, reply with the code {state['code']} "
            "on any channel where you can reach me. If they are fine, do nothing.",
        )
    return []


def _checkin(state: dict, now: float, owner: str) -> list:
    state["checkins_sent"] += 1
    state["last_checkin_at"] = now
    left = state["checkins"] - state["checkins_sent"]
    _log(state, now, f"Check-in {state['checkins_sent']} of {state['checkins']} sent.")
    return _send_all(
        state["owner"]["channels"],
        f"Hermes here. I haven't heard from you in a while, {owner}. "
        f"Say anything to me, on any channel, and I'll keep your letters sealed. "
        + (f"{left} more check-in(s) before I contact {state['trusted']['name'] or 'your trusted contact'}."
           if left else f"Next, I contact {state['trusted']['name'] or 'your trusted contact'}."),
    )


CODE_RE = re.compile(r"\bPSY-\d{6}\b", re.I)
MAX_BAD_CODES = 5


def inbound(state: dict, sender: str, text: str, now: float | None = None) -> tuple[list, bool]:
    """A message arrived on any channel ("omni input").

    Returns ``(actions, handled)``. ``handled`` means the message was a
    Psychopomp confirmation and should not reach the model.
    """
    now = time.time() if now is None else now
    if _in(sender, state["owner"]["channels"]):
        return heartbeat(state, now), False
    match = CODE_RE.search(text or "")
    if not match:
        return [], False
    if state["phase"] != "awaiting_trusted":
        return [{"type": "send", "target": sender, "text": "That code isn't valid right now."}], True
    if match.group(0).upper() != state["code"]:
        state["bad_codes"] = state.get("bad_codes", 0) + 1
        actions = [{"type": "send", "target": sender, "text": "That code isn't valid right now."}]
        if state["bad_codes"] >= MAX_BAD_CODES:  # guessing: retire the code, send a fresh one
            state.update(code=_new_code(), bad_codes=0)
            _log(state, now, "Too many wrong codes. Sent the trusted contact a new one.")
            actions += _send_all(state["trusted"]["channels"],
                                 f"Someone tried wrong codes. Your new code is {state['code']}.")
        return actions, True
    return deliver(state, now, confirmed_by=sender), True


MAX_ATTEMPTS = 20


def pending_letters(state: dict) -> list:
    """Email actions for letters not yet delivered. The caller marks success with ``mark_delivered``."""
    actions = []
    for letter in state["letters"]:
        if letter["delivered_at"] or letter.get("attempts", 0) >= MAX_ATTEMPTS:
            continue
        letter["attempts"] = letter.get("attempts", 0) + 1
        actions.append({"type": "letter", "id": letter["id"], "to": letter["to_email"],
                        "subject": letter["subject"],
                        "body": letter["body"] + "\n\n— Carried to you by Hermes, at the request of "
                        + (state["owner"]["name"] or "its owner") + "."})
    return actions


def mark_delivered(state: dict, letter_id: str, now: float | None = None) -> None:
    now = time.time() if now is None else now
    for letter in state["letters"]:
        if letter["id"] == letter_id and not letter["delivered_at"]:
            letter["delivered_at"] = now
            _log(state, now, f"Delivered the letter for {letter['to_name']}.")


def deliver(state: dict, now: float, confirmed_by: str) -> list:
    state["phase"] = "delivered"
    letters = pending_letters(state)
    _log(state, now, f"Confirmed by {confirmed_by}. Carrying {len(letters)} letter(s).")
    return letters + _send_all(state["trusted"]["channels"],
                               f"Thank you. I am carrying {len(letters)} letter(s) now. Take care.")


def public_view(state: dict, now: float | None = None) -> dict:
    """State for the Desktop pane and the status tool: no letter bodies, no code."""
    now = time.time() if now is None else now
    silent = _days(state, now - state["last_seen"])
    return {
        "armed": state.get("armed", False),
        "phase": state["phase"],
        "owner": state["owner"],
        "trusted": state["trusted"],
        "silence_days": state["silence_days"],
        "checkin_every_days": state["checkin_every_days"],
        "checkins": state["checkins"],
        "checkins_sent": state["checkins_sent"],
        "day_seconds": state["day_seconds"],
        "silent_days": round(silent, 2),
        "days_left": round(max(0.0, state["silence_days"] - silent), 2),
        "letters": [envelope(l) for l in state["letters"]],
        "log": state.get("log", [])[-10:],
    }
