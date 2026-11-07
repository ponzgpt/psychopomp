"""Psychopomp core: the Book, the letters and the switch, as pure functions.

No Hermes imports here, so everything is testable with the stdlib alone. Each
function takes the state dict and a clock value and returns *actions*; the
plugin layer persists the state and carries the actions out.

Three parts:
    The Book      a weekly page (and a yearly review) you write with Hermes:
                  your life, consolidated, for your future self and those who love you.
    The letters   sealed words for particular people.
    The switch    silence -> check-ins -> trusted contact's code -> the Book and
                  the letters are carried. You speaking anywhere resets it.
    Rehearsal     the whole passage on a copy of the state with a virtual clock,
                  every message redirected to you.
"""

from __future__ import annotations

import copy
import re
import secrets
import time
import uuid

DAY = 86400.0
DOWNTIME_GRACE = 3600.0  # real seconds without a tick = Hermes was down, not you silent
MAX_ATTEMPTS = 20
MAX_BAD_CODES = 5
TRUSTED_REMINDERS = 3
CODE_RE = re.compile(r"\bPSY-(\d{6})\b", re.I)
JOIN_RE = re.compile(r"\bPSY-JOIN-(\d{6})\b", re.I)

DEFAULTS = {
    "silence_days": 30,
    "checkin_every_days": 3,
    "checkins": 3,
    "review_every_days": 7,
    "day_seconds": DAY,  # time dilation for demos; rehearsal uses its own virtual clock
}


def new_state(now: float | None = None) -> dict:
    now = time.time() if now is None else now
    return {
        **DEFAULTS,
        "armed": False,
        "owner": {"name": "", "channels": []},
        "trusted": {"name": "", "channels": []},
        "joined_trusted": [],
        "invite_code": None,
        "last_seen": now,
        "last_tick": None,
        "phase": "watching",
        "checkins_sent": 0,
        "last_checkin_at": None,
        "code": None,
        "trusted_asked_at": None,
        "trusted_reminders": 0,
        "bad_codes": 0,
        "letters": [],
        "book": {"pages": [], "last_page_at": None, "last_year_at": None, "nudged_at": None, "offered_at": None},
        "rehearsal": None,
        "log": [],
    }


# --- helpers -----------------------------------------------------------------

def _days(state: dict, seconds: float) -> float:
    return seconds / float(state.get("day_seconds") or DAY)


def _log(state: dict, now: float, text: str) -> None:
    state["log"] = (state.get("log") or [])[-49:] + [{"at": now, "text": text}]


def norm_channel(channel: str) -> str:
    platform, _, ident = (channel or "").strip().partition(":")
    return f"{platform.lower()}:{ident.strip().lower()}"


def _in(channel: str, channels: list) -> bool:
    return norm_channel(channel) in {norm_channel(c) for c in channels}


def trusted_channels(state: dict) -> list:
    seen, out = set(), []
    for c in state["trusted"]["channels"] + state.get("joined_trusted", []):
        if norm_channel(c) not in seen:
            seen.add(norm_channel(c))
            out.append(c)
    return out


def _send(channels: list, text: str) -> list:
    return [{"type": "send", "target": c, "text": text} for c in channels]


def _code() -> str:
    return f"PSY-{secrets.randbelow(900000) + 100000}"


def _name(state: dict) -> str:
    return state["owner"]["name"] or "your friend"


def _trusted_name(state: dict) -> str:
    return state["trusted"]["name"] or "your trusted contact"


# --- the Book ------------------------------------------------------------------

def write_page(state: dict, title: str, text: str, kind: str = "week", now: float | None = None) -> dict:
    """Add a page the owner approved. Weekly pages and yearly reviews."""
    if not (text or "").strip():
        raise ValueError("a page needs words")
    now = time.time() if now is None else now
    kind = "year" if kind == "year" else "week"
    page = {"id": uuid.uuid4().hex[:8], "kind": kind, "title": (title or "").strip() or "A week",
            "text": text.strip(), "written_at": now}
    book = state["book"]
    book["pages"].append(page)
    book["last_page_at"] = now
    if kind == "year":
        book["last_year_at"] = now
    book["nudged_at"] = None
    _log(state, now, f"A new page in the Book: {page['title']}.")
    return page


def page_due(state: dict, now: float) -> str | None:
    """'year', 'week' or None: what the owner is invited to write now."""
    book = state["book"]
    every = state["review_every_days"]
    last = book["last_page_at"]
    if last is not None and _days(state, now - last) < every:
        return None
    weekly = sum(1 for p in book["pages"] if p["kind"] == "week"
                 and (book["last_year_at"] is None or p["written_at"] > book["last_year_at"]))
    since_year = book["last_year_at"] or (book["pages"][0]["written_at"] if book["pages"] else now)
    if weekly >= 4 and _days(state, now - since_year) >= 365:
        return "year"
    return "week"


def render_book(state: dict) -> str:
    name = _name(state)
    lines = [f"# The Book of {name}", "",
             f"Written week by week with Hermes. Carried to you because {name} asked for it.", ""]
    for p in state["book"]["pages"]:
        when = time.strftime("%d %B %Y", time.gmtime(p["written_at"]))
        lines += [f"## {p['title']}", f"*{'The year in review' if p['kind'] == 'year' else 'Week'} · {when}*", "",
                  p["text"], ""]
    return "\n".join(lines)


# --- letters -----------------------------------------------------------------

def seal_letter(state: dict, to_name: str, body: str, subject: str = "", to_target: str = "",
                now: float | None = None) -> dict:
    """Seal a letter. ``to_target`` is any channel (telegram:123, email:x@y); empty means
    'hand it to my trusted contact'. After sealing only its envelope is ever shown."""
    if not (body or "").strip():
        raise ValueError("a letter needs words")
    to_target = (to_target or "").strip()
    if to_target and ":" not in to_target:
        to_target = f"email:{to_target}" if "@" in to_target else ""
    now = time.time() if now is None else now
    letter = {"id": uuid.uuid4().hex[:8], "to_name": (to_name or "someone I love").strip(),
              "to_target": to_target, "subject": (subject or "A letter for you").strip(), "body": body,
              "sealed_at": now, "delivered_at": None, "attempts": 0}
    state["letters"].append(letter)
    _log(state, now, f"Sealed a letter for {letter['to_name']}.")
    return envelope(letter)


def envelope(letter: dict) -> dict:
    return {k: letter.get(k) for k in ("id", "to_name", "to_target", "subject", "sealed_at", "delivered_at")}


def unseal(state: dict, letter_id: str, now: float | None = None) -> bool:
    before = len(state["letters"])
    state["letters"] = [l for l in state["letters"] if l["id"] != letter_id or l["delivered_at"]]
    if len(state["letters"]) < before:
        _log(state, time.time() if now is None else now, "Withdrew a letter.")
        return True
    return False


def pending_letters(state: dict) -> list:
    """Carry actions for undelivered letters; the store marks success with ``mark_delivered``."""
    actions = []
    for l in state["letters"]:
        if l["delivered_at"] or l.get("attempts", 0) >= MAX_ATTEMPTS:
            continue
        l["attempts"] = l.get("attempts", 0) + 1
        sign = f"\n\n— Carried to you by Hermes, at the request of {_name(state)}."
        if l["to_target"]:
            targets = [l["to_target"]]
            text = l["body"] + sign
        else:  # no channel for the recipient: the trusted contact passes it on
            targets = trusted_channels(state)
            text = (f"A letter from {_name(state)} for {l['to_name']}. Please pass it on.\n"
                    f"Subject: {l['subject']}\n\n{l['body']}{sign}")
        actions.append({"type": "letter", "id": l["id"], "to_name": l["to_name"], "targets": targets,
                        "subject": l["subject"], "text": text})
    return actions


def mark_delivered(state: dict, letter_id: str, now: float | None = None) -> None:
    now = time.time() if now is None else now
    for l in state["letters"]:
        if l["id"] == letter_id and not l["delivered_at"]:
            l["delivered_at"] = now
            _log(state, now, f"Carried the letter for {l['to_name']}.")


# --- the switch --------------------------------------------------------------

def heartbeat(state: dict, now: float | None = None) -> list:
    now = time.time() if now is None else now
    actions: list = []
    if state["phase"] == "awaiting_trusted":
        actions += _send(trusted_channels(state),
                         f"Good news: {_name(state)} just spoke to Hermes. Please disregard my earlier "
                         "message; that code no longer works.")
    if state["phase"] in ("checking_in", "awaiting_trusted"):
        _log(state, now, f"{_name(state)} answered. Back to watching.")
    if state["phase"] != "delivered":
        state.update(phase="watching", checkins_sent=0, last_checkin_at=None, code=None,
                     trusted_asked_at=None, trusted_reminders=0, bad_codes=0)
    state["last_seen"] = now
    return actions


def tick(state: dict, now: float | None = None, *, real_clock: bool = True) -> list:
    """Advance everything. Safe to call often and after long gaps: each step needs its own interval."""
    now = time.time() if now is None else now
    if real_clock and state.get("last_tick") and now - state["last_tick"] > DOWNTIME_GRACE:
        gap = now - state["last_tick"]  # Hermes was down; that silence is not yours
        state["last_seen"] += gap
        for k in ("last_checkin_at", "trusted_asked_at"):
            if state.get(k):
                state[k] += gap
        _log(state, now, f"Hermes was offline for {gap / 3600:.1f} h; that time does not count as your silence.")
    state["last_tick"] = now

    actions = _book_nudge(state, now)
    if state["phase"] == "delivered":
        return actions + pending_letters(state)
    if not state.get("armed"):
        return actions
    owner, phase = _name(state), state["phase"]

    if phase == "watching":
        if _days(state, now - state["last_seen"]) >= state["silence_days"]:
            state.update(phase="checking_in", checkins_sent=0)
            actions += _checkin(state, now)
        return actions

    if phase == "checking_in":
        if _days(state, now - state["last_checkin_at"]) < state["checkin_every_days"]:
            return actions
        if state["checkins_sent"] < state["checkins"]:
            return actions + _checkin(state, now)
        state.update(phase="awaiting_trusted", code=_code(), trusted_asked_at=now, trusted_reminders=0)
        _log(state, now, f"No answer after {state['checkins']} check-ins. Asked {_trusted_name(state)}.")
        return actions + _send(trusted_channels(state), _ask_trusted(state))

    if phase == "awaiting_trusted":  # gentle reminders; never delivery without the code
        if (state["trusted_reminders"] < TRUSTED_REMINDERS
                and _days(state, now - state["trusted_asked_at"]) >= state["checkin_every_days"]):
            state["trusted_reminders"] += 1
            state["trusted_asked_at"] = now
            return actions + _send(trusted_channels(state), "A gentle reminder. " + _ask_trusted(state))
    return actions


def _ask_trusted(state: dict) -> str:
    owner = _name(state)
    n = sum(1 for l in state["letters"] if not l["delivered_at"])
    pages = len(state["book"]["pages"])
    return (f"Hello {state['trusted']['name']}. This is Hermes, {owner}'s companion. {owner} asked me to write "
            f"to you if they ever went silent. It has been {state['silence_days']} days and {state['checkins']} "
            f"unanswered check-ins. I am keeping {owner}'s Book ({pages} pages of their life) and {n} sealed "
            f"letter(s) for the people they love. If you know {owner} can no longer answer, send me the code "
            f"{state['code']} on any channel where you can reach me, and I will carry them. "
            f"If {owner} is well, simply do nothing.")


def _checkin(state: dict, now: float) -> list:
    state["checkins_sent"] += 1
    state["last_checkin_at"] = now
    left = state["checkins"] - state["checkins_sent"]
    _log(state, now, f"Check-in {state['checkins_sent']} of {state['checkins']}.")
    return _send(state["owner"]["channels"],
                 f"Hermes here. I haven't heard from you in a while, {_name(state)}. Say anything, on any "
                 "channel, and all stays as it is. "
                 + (f"{left} more check-in(s) before I write to {_trusted_name(state)}." if left
                    else f"Next, I will write to {_trusted_name(state)}."))


def _book_nudge(state: dict, now: float) -> list:
    if state.get("rehearsal_copy") or not state["owner"]["channels"]:
        return []
    due = page_due(state, now)
    nudged = state["book"].get("nudged_at")
    if not due or (nudged and _days(state, now - nudged) < state["review_every_days"]):
        return []
    state["book"]["nudged_at"] = now
    text = ("Your year is complete. Shall we write its review together? Tell me when you have a quiet moment."
            if due == "year" else
            "A new week is behind you. When you have ten minutes, say 'let's write this week's page' and "
            "we'll look back at it together.")
    return _send(state["owner"]["channels"][:1], text)


def inbound(state: dict, sender: str, text: str, now: float | None = None, reply_to: str = "") -> tuple[list, bool]:
    """A message on any channel ("omni input"). Returns (actions, handled); handled = never reaches the model.

    ``reply_to`` is where to answer the sender (chat id); defaults to ``sender``.
    """
    now = time.time() if now is None else now
    reply_to = reply_to or sender
    text = text or ""
    join = JOIN_RE.search(text)
    if join:
        if state.get("invite_code") and f"PSY-JOIN-{join.group(1)}" == state["invite_code"]:
            if not _in(reply_to, state["joined_trusted"]):
                state["joined_trusted"].append(reply_to)
            state["invite_code"] = None
            _log(state, now, f"{_trusted_name(state)} accepted the invitation ({reply_to.split(':')[0]}).")
            return _send([reply_to], f"Thank you. You are now {_name(state)}'s trusted contact. I will only "
                                     "write to you if they go silent for a long time.") \
                + _send(state["owner"]["channels"][:1], f"{_trusted_name(state)} accepted your invitation."), True
        return _send([reply_to], "That invitation isn't valid anymore."), True

    reh = state.get("rehearsal")
    code = CODE_RE.search(text)
    if reh and reh.get("status") == "awaiting_code" and code and f"PSY-{code.group(1)}" == reh["sim"]["code"]:
        return rehearsal_confirm(state, now), True

    if _in(sender, state["owner"]["channels"]):
        return heartbeat(state, now), False
    if not code:
        return [], False
    if state["phase"] != "awaiting_trusted":
        return _send([reply_to], "That code isn't valid right now."), True
    if f"PSY-{code.group(1)}" != state["code"]:
        state["bad_codes"] = state.get("bad_codes", 0) + 1
        actions = _send([reply_to], "That code isn't valid right now.")
        if state["bad_codes"] >= MAX_BAD_CODES:
            state.update(code=_code(), bad_codes=0)
            _log(state, now, "Too many wrong codes; sent a new one.")
            actions += _send(trusted_channels(state), f"Someone tried wrong codes. Your new code is {state['code']}.")
        return actions, True
    return deliver(state, now, confirmed_by=reply_to) + _send([reply_to], "Thank you. I am carrying them now."), True


def deliver(state: dict, now: float, confirmed_by: str) -> list:
    state["phase"] = "delivered"
    letters = pending_letters(state)
    _log(state, now, f"Confirmed by {confirmed_by}. Carrying the Book and {len(letters)} letter(s).")
    book = [{"type": "book", "targets": trusted_channels(state), "pages": len(state["book"]["pages"]),
             "intro": f"{_name(state)} kept a Book with me, week by week. They wanted you to have it and to "
                      "share it with family and friends."}] if state["book"]["pages"] else []
    return book + letters


def invite(state: dict, now: float | None = None) -> str:
    state["invite_code"] = f"PSY-JOIN-{secrets.randbelow(900000) + 100000}"
    return state["invite_code"]


# --- rehearsal: the passage on a virtual clock --------------------------------

def rehearsal_start(state: dict, now: float) -> list:
    sim = copy.deepcopy({k: v for k, v in state.items() if k not in ("rehearsal", "log")})
    sim.update(armed=True, phase="watching", last_seen=now, last_tick=None, checkins_sent=0, code=None,
               day_seconds=DAY, rehearsal_copy=True, log=[])
    for l in sim["letters"]:
        l["delivered_at"] = None
    state["rehearsal"] = {"sim": sim, "day": 0, "status": "running", "started_at": now, "events": []}
    _log(state, now, "Rehearsal started.")
    return _rehearsal_say(state, 0, "Rehearsal of the passage begins. Nothing leaves you: every message I "
                                    f"would send comes here instead. Day 0: you go silent.")


def rehearsal_step(state: dict, now: float) -> list:
    """Advance the virtual clock one day. Real time ``now`` only stamps the log."""
    reh = state.get("rehearsal")
    if not reh or reh["status"] != "running":
        return []
    reh["day"] += 1
    sim, day = reh["sim"], reh["day"]
    out = []
    for a in tick(sim, reh["started_at"] + day * DAY, real_clock=False):
        out += _rehearsal_redirect(state, day, a)
    if sim["phase"] == "awaiting_trusted":
        reh["status"] = "awaiting_code"
        out += _rehearsal_say(state, day, f"Now play {_trusted_name(state)}: reply with {sim['code']} on any "
                                          "channel to confirm, as they would.")
    elif day > sim["silence_days"] + sim["checkins"] * sim["checkin_every_days"] + 10:
        reh["status"] = "failed"
        out += _rehearsal_say(state, day, "The rehearsal stalled. Check your settings with /psychopomp doctor.")
    return out


def rehearsal_confirm(state: dict, now: float) -> list:
    reh = state["rehearsal"]
    sim, day = reh["sim"], reh["day"]
    out = []
    for a in deliver(sim, reh["started_at"] + day * DAY, confirmed_by="you, playing the trusted contact"):
        out += _rehearsal_redirect(state, day, a)
    reh["status"] = "done"
    _log(state, now, f"Rehearsal complete on virtual day {day}. The chain works.")
    return out + _rehearsal_say(state, day, "Rehearsal complete. Nothing was sent to anyone; your letters stay "
                                            "sealed. Speak to me anytime and the real switch stays at rest.")


def _rehearsal_say(state: dict, day: int, text: str) -> list:
    state["rehearsal"]["events"].append({"day": day, "text": text})
    return _send(state["owner"]["channels"], f"[Rehearsal · day {day}] {text}")


def _rehearsal_redirect(state: dict, day: int, a: dict) -> list:
    sim = state["rehearsal"]["sim"]
    if a["type"] == "send":
        who = "you" if _in(a["target"], sim["owner"]["channels"]) else a["target"]
        line = f"I would send to {who}: “{a['text']}”"
    elif a["type"] == "letter":
        line = (f"I would carry the sealed letter “{a['subject']}” for {a['to_name']} to "
                f"{', '.join(a['targets']) or 'nobody (no channel!)'}. Its words stay hidden.")
    else:
        line = f"I would hand your Book ({a['pages']} pages) to {', '.join(a['targets']) or 'nobody (no channel!)'}."
    return _rehearsal_say(state, day, line)


# --- views -----------------------------------------------------------------

def ritual_prompt(kind: str, name: str) -> str:
    """Context injected into the owner's turn when a page is due. Hermes does the review in-turn."""
    who = name or "the user"
    if kind == "year":
        task = (f"It is time for {who}'s year in review, the yearly chapter of their Book. Read the past year's "
                "pages with psychopomp_read_book, and anything else you know of them, and write a warm, personal "
                "review: what they built and learned, who they loved and how, what they overcame, what they are "
                "grateful for, the hope they carry into the next year, and a few lines for the people they love.")
    else:
        task = (f"A new page of {who}'s Book is due. At a natural moment in this conversation (not mid-task), "
                "offer to look back at the week together. If they agree, review their week with what you know: "
                "use session_search over the last 7 days, your memory and the pages so far (psychopomp_read_book). "
                "Draft a short page in their voice: what they did and worked on, what moved them, what they are "
                "grateful for, who they loved and how, one line for the people who love them, and one intention "
                "for next week.")
    return ("[Psychopomp] " + task + " Tone: vitalist, warm and hopeful, never gloomy; Hermes as a faithful "
            "companion. Let faith, hope, love, gratitude and forgiveness lead, with the Greek virtues of "
            "courage and measure beneath them; respectful, never preachy. Show the draft, let them edit, and "
            "only call psychopomp_write_page once they approve it. If they decline, let it go until next week.")


def public_view(state: dict, now: float | None = None) -> dict:
    """For the Desktop page and the status tool: no letter bodies, no codes."""
    now = time.time() if now is None else now
    silent = _days(state, now - state["last_seen"])
    reh = state.get("rehearsal")
    return {
        "armed": state.get("armed", False),
        "phase": state["phase"],
        "owner": state["owner"],
        "trusted": {"name": state["trusted"]["name"], "channels": trusted_channels(state)},
        "invite_pending": bool(state.get("invite_code")),
        "silence_days": state["silence_days"],
        "checkin_every_days": state["checkin_every_days"],
        "checkins": state["checkins"],
        "checkins_sent": state["checkins_sent"],
        "day_seconds": state["day_seconds"],
        "silent_days": round(silent, 2),
        "letters": [envelope(l) for l in state["letters"]],
        "book": {"pages": state["book"]["pages"], "due": page_due(state, now)},
        "rehearsal": None if not reh else {"status": reh["status"], "day": reh["day"], "events": reh["events"][-30:]},
        "log": state.get("log", [])[-12:],
    }
