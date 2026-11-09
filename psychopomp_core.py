"""Psychopomp core: the Book, the letters and the switch, as pure functions.

No Hermes imports here, so everything is testable with the stdlib alone. Each
function takes the state dict and a clock value and returns *actions*; the
plugin layer persists the state and carries the actions out.

Three parts:
    The Book      a weekly page (and a yearly review) you write with Hermes:
                  your life, consolidated, for your future self and those who love you.
    The letters   sealed words for particular people.
    The watch     silence -> check-ins -> your witness's code -> the Book and
                  the letters are carried. You speaking anywhere resets it.
    Rehearsal     the whole passage on a copy of the state with a virtual clock,
                  every message redirected to you.
"""

from __future__ import annotations

import copy
import datetime as _dt
import html
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
    return state["trusted"]["name"] or "your witness"


def week_label(ts: float) -> str:
    """'Week 46 · 2026' (ISO week), how pages are named everywhere."""
    y, w, _ = _dt.datetime.fromtimestamp(ts, _dt.timezone.utc).isocalendar()
    return f"Week {w} · {y}"


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


def draft_page(state: dict, title: str, text: str, kind: str = "week", now: float | None = None) -> dict:
    """A page Hermes proposes; it joins the Book only when the owner approves it."""
    if not (text or "").strip():
        raise ValueError("a page needs words")
    now = time.time() if now is None else now
    drafts = state["book"].setdefault("drafts", {})
    for k in [k for k, d in drafts.items() if now - d["drafted_at"] > 30 * DAY]:
        del drafts[k]  # old proposals fade
    d = {"id": uuid.uuid4().hex[:8], "kind": "year" if kind == "year" else "week",
         "title": (title or "").strip() or "A week", "text": text.strip(), "drafted_at": now, "page_id": None}
    drafts[d["id"]] = d
    return d


def approve_draft(state: dict, draft_id: str, now: float | None = None) -> dict:
    d = state["book"].get("drafts", {}).get(draft_id)
    if not d:
        raise ValueError("that draft is gone; ask Hermes for a new one")
    if not d["page_id"]:  # approving twice (card + chat) adds it once
        d["page_id"] = write_page(state, d["title"], d["text"], d["kind"], now)["id"]
    return next(p for p in state["book"]["pages"] if p["id"] == d["page_id"])


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


CADUCEUS_SVG = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width=".8" stroke-linecap="round" '
                'stroke-linejoin="round"><circle cx="12" cy="2.9" r="1.3"/><path d="M12 4.3V22"/>'
                '<path d="M11 6.2C8.6 4.6 5.6 4.4 2.8 5.6c2.4.6 4.9 1.6 8.2 2.4"/>'
                '<path d="M13 6.2c2.4-1.6 5.4-1.8 8.2-.6-2.4.6-4.9 1.6-8.2 2.4"/>'
                '<path d="M9.2 9.4c4.6 0 6.2 1.2 6.2 2.6s-6.8 1.4-6.8 3.4 3.6 2.4 5.8 2.4"/>'
                '<path d="M14.8 9.4c-4.6 0-6.2 1.2-6.2 2.6s6.8 1.4 6.8 3.4-3.6 2.4-5.8 2.4"/></svg>')

BOOK_CSS = """
@page{margin:22mm 20mm}
*{box-sizing:border-box}
body{margin:0;background:#f6f1e7;color:#2b2722;font:18px/1.75 "Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif}
main{max-width:640px;margin:0 auto;padding:0 24px 96px}
.cover{min-height:min(92vh,620px);display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;page-break-after:always}
.cover svg{width:88px;height:96px;color:#a8792a;margin-bottom:28px}
.cover h1{font-size:42px;font-weight:normal;letter-spacing:.01em;margin:0 0 10px}
.cover p{margin:0;color:#7a6f61;font-size:17px}
.fore{font-style:italic;color:#5c5348;margin:48px 0 64px;text-align:center}
.year{font-size:13px;letter-spacing:.3em;text-transform:uppercase;color:#a8792a;text-align:center;margin:80px 0 8px}
article{margin:56px 0;page-break-inside:avoid}
article .when{font-size:13px;letter-spacing:.12em;text-transform:uppercase;color:#9a8e7e}
article h2{font-size:27px;font-weight:normal;margin:4px 0 14px;line-height:1.3}
article.review h2{font-size:32px}
article.review{border-top:1px solid #d9cdb8;border-bottom:1px solid #d9cdb8;padding:28px 0}
article p{margin:0 0 14px}
.orn{text-align:center;color:#c2a875;letter-spacing:.6em;margin:40px 0}
.end{text-align:center;color:#7a6f61;margin-top:72px;font-size:16px}
@media (max-width:520px){body{font-size:17px}.cover h1{font-size:34px}}
"""


def render_book(state: dict, now: float | None = None) -> str:
    """The Book as one self-contained HTML file, designed to be opened by family on any phone or printed."""
    now = time.time() if now is None else now
    name = html.escape(_name(state))
    pages = state["book"]["pages"]
    years = sorted({_dt.datetime.fromtimestamp(p["written_at"], _dt.timezone.utc).year for p in pages})
    span = f"{years[0]}–{years[-1]}" if len(years) > 1 else (str(years[0]) if years else "")
    body, current = [], None
    for p in pages:
        y = _dt.datetime.fromtimestamp(p["written_at"], _dt.timezone.utc).year
        if y != current:
            current = y
            body.append(f'<div class="year">{y}</div><div class="orn">· · ·</div>')
        when = ("The year in review · " if p["kind"] == "year" else week_label(p["written_at"]).split(" · ")[0] + " · ")
        when += time.strftime("%d %B %Y", time.gmtime(p["written_at"])).lstrip("0")
        paras = "".join(f"<p>{html.escape(x.strip())}</p>" for x in p["text"].split("\n") if x.strip())
        body.append(f'<article class="{"review" if p["kind"] == "year" else "week"}"><div class="when">{when}</div>'
                    f'<h2>{html.escape(p["title"])}</h2>{paras}</article>')
    letters = len(state["letters"])
    end = (f"{name} also left {letters} sealed letter{'s' if letters != 1 else ''}. Each one is being carried to its person."
           if letters else "")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width,initial-scale=1"><title>The Book of {name}</title><style>{BOOK_CSS}</style>'
            f'</head><body><main><section class="cover">{CADUCEUS_SVG}<h1>The Book of {name}</h1>'
            f'<p>Written week by week with Hermes{" · " + span if span else ""}</p></section>'
            f'<p class="fore">{name} wrote these pages with me, one week at a time: what they did, what moved them, '
            f'who they loved. They asked me to bring them to you, so you can share them with family and friends.<br>'
            f'— Hermes</p>{"".join(body)}<div class="orn">☤</div><p class="end">{end}</p></main></body></html>')


# --- letters -----------------------------------------------------------------

def seal_letter(state: dict, to_name: str, body: str, subject: str = "", to_target: str = "",
                now: float | None = None) -> dict:
    """Seal a letter. ``to_target`` is any channel Hermes speaks (telegram:123); empty means
    'hand it to my witness'. After sealing only its envelope is ever shown."""
    if not (body or "").strip():
        raise ValueError("a letter needs words")
    to_target = (to_target or "").strip()
    if to_target and ":" not in to_target:
        raise ValueError("a channel looks like telegram:123456789; leave it empty and your witness passes it on")
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
        else:  # no channel for the recipient: the witness passes it on
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
                         f"Good news: {_name(state)} just spoke to me. All is well; please disregard my earlier "
                         "message. That code no longer works.")
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
    Owner = owner[:1].upper() + owner[1:]
    hello = f"Hello {state['trusted']['name']}." if state["trusted"]["name"] else "Hello."
    n = sum(1 for l in state["letters"] if not l["delivered_at"])
    pages = len(state["book"]["pages"])
    return (f"{hello} This is Hermes, {owner}'s companion. {Owner} chose you as their witness. I haven't heard "
            f"from them in {state['silence_days']} days, and they haven't answered {state['checkins']} check-ins. "
            f"I am keeping {owner}'s Book ({pages} pages of their life) and {n} sealed letter(s) for the people "
            f"they love. If you know {owner} can no longer answer, send me {state['code']} on any channel where "
            f"you can reach me, and I will carry them. If {owner} is well, simply do nothing.")


def _checkin(state: dict, now: float) -> list:
    state["checkins_sent"] += 1
    state["last_checkin_at"] = now
    left = state["checkins"] - state["checkins_sent"]
    _log(state, now, f"Check-in {state['checkins_sent']} of {state['checkins']}.")
    return _send(state["owner"]["channels"],
                 f"Hermes here. I haven't heard from you in a while{', ' + state['owner']['name'] if state['owner']['name'] else ''}. Say anything, on any "
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
            return _send([reply_to], f"Thank you. {_name(state)} has chosen you as their witness. I will only "
                                     "write to you if they go silent for a long time, and nothing is ever "
                                     "carried without you.") \
                + _send(state["owner"]["channels"][:1], f"{_trusted_name(state)} is now your witness."), True
        return _send([reply_to], "That invitation isn't valid anymore."), True

    reh = state.get("rehearsal")
    code = CODE_RE.search(text)
    if reh and reh.get("status") == "awaiting_code" and code and f"PSY-{code.group(1)}" == reh["sim"]["code"]:
        out = rehearsal_confirm(state, now)
        return out + ([] if reh.get("mirror") else _send([reply_to], rehearsal_card(state))), True

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
    return deliver(state, now, confirmed_by=reply_to) + _send([reply_to], "Thank you. I am carrying them now. "
                                                              "Their Book comes to you next."), True


def deliver(state: dict, now: float, confirmed_by: str) -> list:
    state["phase"] = "delivered"
    letters = pending_letters(state)
    _log(state, now, f"Confirmed by {confirmed_by}. Carrying the Book and {len(letters)} letter(s).")
    book = [{"type": "book", "targets": trusted_channels(state), "pages": len(state["book"]["pages"]),
             "intro": f"This is the Book of {_name(state)}: {len(state['book']['pages'])} pages of their life, "
                      "written with me week by week. They wanted you to have it, and to share it with family "
                      "and friends. Open it whenever you're ready."}] if state["book"]["pages"] else []
    return book + letters


def invite(state: dict, now: float | None = None, name: str = "") -> str:
    if (name or "").strip():
        state["trusted"]["name"] = name.strip()
    state["invite_code"] = f"PSY-JOIN-{secrets.randbelow(900000) + 100000}"
    return state["invite_code"]


# --- rehearsal: the passage on a virtual clock --------------------------------

def rehearsal_start(state: dict, now: float, mirror: bool = True) -> list:
    """Copy the state and play it on a virtual clock. Placeholders stand in for channels not set up yet, so
    the chain plays anyway; with ``mirror`` each step is also sent to the owner's own channels."""
    sim = copy.deepcopy({k: v for k, v in state.items() if k not in ("rehearsal", "log")})
    sim.update(armed=True, phase="watching", last_seen=now, last_tick=None, checkins_sent=0, code=None,
               day_seconds=DAY, rehearsal_copy=True, log=[])
    if not sim["owner"]["channels"]:
        sim["owner"]["channels"] = ["you:here"]
    if not trusted_channels(sim):
        sim["trusted"]["channels"] = ["trusted:not-invited-yet"]
    for l in sim["letters"]:
        l["delivered_at"] = None
    state["rehearsal"] = {"sim": sim, "day": 0, "status": "running", "started_at": now, "events": [],
                          "mirror": bool(mirror and state["owner"]["channels"])}
    _log(state, now, "Rehearsal started.")
    return _rehearsal_say(state, 0, "Day 0. You stop talking to Hermes. From here the clock is virtual: "
                                    "nothing leaves, nothing is unsealed.", kind="start")


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
        out += _rehearsal_say(state, day, f"Now play {_trusted_name(state)}: send {sim['code']} on any "
                                          "channel (or /psychopomp confirm with it), as they would.", kind="code")
    elif day > sim["silence_days"] + sim["checkins"] * sim["checkin_every_days"] + 10:
        reh["status"] = "failed"
        out += _rehearsal_say(state, day, "The rehearsal stalled. Run /psychopomp doctor.", kind="error")
    return out


def rehearsal_confirm(state: dict, now: float) -> list:
    reh = state["rehearsal"]
    sim, day = reh["sim"], reh["day"]
    out = []
    for a in deliver(sim, reh["started_at"] + day * DAY, confirmed_by="you, playing your witness"):
        out += _rehearsal_redirect(state, day, a)
    reh["status"] = "done"
    _log(state, now, f"Rehearsal complete on virtual day {day}. The chain works.")
    return out + _rehearsal_say(state, day, "The chain works. Nothing was sent to anyone and your letters stay "
                                            "sealed. Your real watch is untouched.", kind="done")


def rehearsal_stop(state: dict, now: float) -> bool:
    reh = state.get("rehearsal")
    if not reh or reh["status"] not in ("running", "awaiting_code"):
        return False
    reh["status"] = "stopped"
    _log(state, now, "Rehearsal stopped.")
    return True


def _rehearsal_say(state: dict, day: int, text: str, kind: str = "note", to: str = "", line: str = "") -> list:
    reh = state["rehearsal"]
    reh["events"].append({"day": day, "kind": kind, "to": to, "text": text})
    if not reh.get("mirror"):
        return []
    return _send(state["owner"]["channels"], f"[Rehearsal · day {day}] {line or text}")


def _who(sim: dict, target: str) -> str:
    if _in(target, sim["owner"]["channels"]):
        return "you"
    if _in(target, trusted_channels(sim)):
        return sim["trusted"]["name"] or "your witness"
    return target.split(":")[0].capitalize()  # "telegram:123" → "Telegram": ids stay out of the story


def _rehearsal_redirect(state: dict, day: int, a: dict) -> list:
    sim = state["rehearsal"]["sim"]
    if a["type"] == "send":
        who = _who(sim, a["target"])
        return _rehearsal_say(state, day, a["text"], kind="message", to=who,
                              line=f"I would send to {who}: “{a['text']}”")
    targets = ", ".join(_who(sim, t) for t in a["targets"]) or "nobody (no channel!)"
    if a["type"] == "letter":
        return _rehearsal_say(state, day, f"“{a['subject'] or 'A letter'}”. Sealed: its words stay hidden, even from Hermes.",
                              kind="letter", to=f"{a['to_name']} · via {targets}",
                              line=f"I would carry the sealed letter “{a['subject']}” for {a['to_name']} to "
                                   f"{targets}. Its words stay hidden.")
    return _rehearsal_say(state, day, f"Your Book, {a['pages']} page(s), to share with family and friends.",
                          kind="book", to=targets, line=f"I would hand your Book ({a['pages']} pages) to {targets}.")


# --- views -----------------------------------------------------------------

STAGES = ("You live", "Silence", "Check-ins", "Witness", "Carried")


def _stage(phase: str, days: float, silence: float) -> int:
    return {"delivered": 4, "awaiting_trusted": 3, "checking_in": 2}.get(phase, 1 if days / silence > 0.2 else 0)


def rehearsal_card(state: dict) -> str:
    """The rehearsal as one chat message (edited in place where the surface allows): the same path the
    Desktop page draws, a virtual clock, and the last few things Hermes would have sent."""
    reh = state.get("rehearsal")
    if not reh:
        return "No rehearsal yet. Send /psychopomp rehearse."
    sim, day = reh["sim"], reh["day"]
    at = _stage("delivered" if reh["status"] == "done" else sim["phase"], day, sim["silence_days"])
    path = " ─ ".join(("◉ " if i == at else "● " if i < at else "○ ") + n for i, n in enumerate(STAGES))
    when = time.strftime("%a %d %b", time.gmtime(reh["started_at"] + day * DAY))
    lines = [f"☤ Rehearsal · Day {day} · {when} (virtual clock)", path, ""]
    for e in [e for e in reh["events"] if e["kind"] not in ("start", "code")][-4:]:
        who = {"message": f"Hermes → {e['to']}", "letter": f"Sealed letter → {e['to']}", "book": f"Your Book → {e['to']}",
               "code": "Your turn", "done": "✓ Done"}.get(e["kind"], "")
        text = e["text"] if len(e["text"]) <= 220 else e["text"][:217] + "…"
        lines.append(f"Day {e['day']} · {who}: {text}" if who else f"Day {e['day']} · {text}")
    if reh["status"] == "running":
        lines.append("…time passes. Nothing leaves; nothing is unsealed.")
    elif reh["status"] == "awaiting_code":
        lines.append(f"\nPlay your witness: send /psychopomp confirm {sim['code']}")
    return "\n".join(lines)


def ritual_prompt(kind: str, name: str, *, skill: bool = True) -> str:
    """Context added to the owner's turn when a page is due. Hermes does the look-back in that turn."""
    who = name or "the user"
    what = f"{who}'s year in review" if kind == "year" else f"a new page of {who}'s Book ({week_label(time.time())})"
    if skill:
        return (f"[Psychopomp] It is time for {what}. At a natural moment in this conversation (not mid-task), "
                "offer to look back together. If they agree, load the skill psychopomp:weekly-page and follow it. "
                "If they decline, let it go until next week.")
    return (f"[Psychopomp] It is time for {what}. At a natural moment (not mid-task), offer to look back at the "
            "week together. If they agree, use session_search over the last 7 days, your memory and "
            "psychopomp_read_book, and draft a short page in their voice: what they did, what moved them, who they "
            "loved, what they are grateful for, one line for the people who love them, one intention. Warm, "
            "vitalist, never gloomy. Propose it with psychopomp_draft_page; it joins the Book only when they "
            "approve. If they decline, let it go until next week.")


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
        "book": {"pages": state["book"]["pages"], "due": page_due(state, now),
                 "drafts": state["book"].get("drafts", {})},
        "rehearsal": None if not reh else {
            "status": reh["status"], "day": reh["day"], "started_at": reh["started_at"],
            "mirror": reh.get("mirror", False), "events": reh["events"][-40:],
            "phase": reh["sim"]["phase"], "checkins_sent": reh["sim"]["checkins_sent"],
            # the rehearsal's own throwaway code, never the real one
            "code": reh["sim"]["code"] if reh["status"] == "awaiting_code" else None},
        "log": state.get("log", [])[-12:],
    }
