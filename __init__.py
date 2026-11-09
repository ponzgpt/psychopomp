"""Psychopomp — every week, Hermes helps you write a page of your life; if you ever go
silent for good, it carries your words to the people you love.

The Book (a page a week, a year in review), sealed letters, and the watch: silence,
check-ins, then your witness's code on any channel before anything is carried. A
rehearsal plays the whole passage on a virtual clock, on any surface.
"""

from __future__ import annotations

import fcntl
import json
import logging
import threading
import time
from pathlib import Path

from . import psychopomp_core as core
from . import psychopomp_store as store

log = logging.getLogger("psychopomp")
TICK_SECONDS = 30
RITUAL_EVERY_SECONDS = 6 * 3600  # offer the page at most every 6 h while it is due
HERE_WINDOW = 120  # seconds a "/psychopomp here" seen at the gateway stays claimable
_ctx = None
_has_skill = False


def _settings() -> dict:
    if _ctx is None:
        return {}
    return {k: _ctx.get_config(k, default) for k, default in store.SETTINGS.items()}


def _sync(state: dict) -> None:
    store.apply_settings(state, _settings())


def _bg(actions: list) -> None:
    if actions:
        threading.Thread(target=store.perform, args=(actions,), daemon=True).start()


# --- every turn on every surface: heartbeat + the weekly ritual -----------------

def _on_llm_call(platform=None, **_kw):
    if platform in ("cron",):  # Hermes' own scheduled jobs are not you
        return None
    try:
        now = time.time()
        with store.locked_state() as s:
            _sync(s)
            was = s["phase"]
            actions = core.heartbeat(s, now)
            due = core.page_due(s, now)
            offered = s["book"].get("offered_at") or 0
            ritual = None
            if due and now - offered > RITUAL_EVERY_SECONDS:
                s["book"]["offered_at"] = now
                ritual = core.ritual_prompt(due, s["owner"]["name"], skill=_has_skill)
        _bg(actions)
        if actions or was != "watching":
            store.notify_desktop()
        return {"context": ritual} if ritual else None
    except Exception as exc:  # never block a turn
        log.warning("psychopomp heartbeat failed: %s", exc)
        return None


# --- omni input: codes on any channel, before the gateway's sender check ----------

async def _on_gateway_message(event=None, gateway=None, **_kw):
    try:
        src = event.source
        platform = getattr(src.platform, "value", src.platform)
        sender, reply_to = f"{platform}:{src.user_id}", f"{platform}:{src.chat_id}"
        text = event.text or ""
        with store.locked_state() as s:
            if text.strip().lower().startswith("/psychopomp here"):  # claimed by the command, after auth
                s["here_pending"] = {"chat": reply_to, "at": time.time()}
            actions, handled = core.inbound(s, sender, text, reply_to=reply_to)
        if not handled:
            _bg(actions)
            return None
        _bg(actions)  # replies go out through Hermes' delivery (works in-process and in the plugin host)
        store.notify_desktop()
        return {"action": "skip", "reason": "psychopomp"}
    except Exception as exc:
        log.warning("psychopomp inbound check failed: %s", exc)
        return None


# --- background: the switch ticker and the rehearsal runner ---------------------

def _ticker(stop: threading.Event) -> None:
    """One process at a time advances the switch (whichever holds the lock)."""
    lock_file = open(store.data_dir() / "ticker.lock", "w")
    held = False
    while not stop.wait(0 if not held else TICK_SECONDS):
        try:
            if not held:
                try:
                    fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    held = True
                except OSError:
                    stop.wait(TICK_SECONDS)
                    continue
            with store.locked_state() as s:
                _sync(s)
                actions = core.tick(s)
            store.perform(actions)
        except Exception as exc:
            log.warning("psychopomp tick failed: %s", exc)
    lock_file.close()


# --- commands -------------------------------------------------------------------

PHASES = {
    "watching": "All is well.",
    "checking_in": "You have been quiet; Hermes is checking in.",
    "awaiting_trusted": "Waiting for your witness's code.",
    "delivered": "Your Book and letters have been carried.",
}
USAGE = ("/psychopomp [status | here | invite <name> | rehearse | confirm <code> | watch | rest | doctor | test]")


def _fmt(v: dict) -> str:
    w = v["trusted"]
    return "\n".join([
        "☤ Psychopomp",
        (f"Keeping watch · {PHASES[v['phase']]} (silent {v['silent_days']:.1f} of {v['silence_days']} days)"
         if v["armed"] else "Resting: Hermes is not keeping watch. /psychopomp watch to start."),
        f"Reaches you on: {', '.join(c.split(':')[0].capitalize() for c in v['owner']['channels']) or '— (/psychopomp here)'}",
        f"Witness: {w['name'] or '—'}" + ("" if w["channels"] else " (not joined yet: /psychopomp invite <name>)"),
        f"Book: {len(v['book']['pages'])} page(s)" + (" · this week's page is due" if v["book"]["due"] else ""),
        f"Sealed letters: {len(v['letters'])}",
    ])


def _current_chat() -> str:
    """platform:chat of the conversation running this command, if it is a messaging chat."""
    try:
        from gateway.session_context import get_session_env
        platform = get_session_env("HERMES_SESSION_PLATFORM", "").strip().lower()
        chat = get_session_env("HERMES_SESSION_CHAT_ID", "").strip()
        if platform and chat and platform not in ("cli", "tui", "desktop", "local", "api_server"):
            return f"{platform}:{chat}"
    except Exception:
        pass
    with store.locked_state() as s:  # seen by the gateway hook a moment ago (plugin host mode)
        pend = s.pop("here_pending", None)
    if pend and time.time() - pend["at"] < HERE_WINDOW:
        return pend["chat"]
    return ""


def _rehearse_in_chat() -> str:
    """One message, edited day by day, where the surface supports it; else the whole run at once."""
    handle = None
    try:
        handle = _ctx.post_message("☤ Rehearsal begins…") if _ctx is not None else None
    except Exception:
        handle = None
    if handle is not None and getattr(handle, "ok", False):
        msg, _ = store.start_rehearsal(on_step=lambda card: handle.edit(card))
        return "" if msg == "Rehearsal started." else msg
    return store.rehearse_now()


def run(raw: str) -> str:
    parts = (raw or "").strip().split()
    verb = parts[0].lower() if parts else "status"
    rest = " ".join(parts[1:])
    with store.locked_state() as s:
        _sync(s)
    if verb == "rehearse":
        return _rehearse_in_chat()
    if verb == "confirm":
        return store.confirm_rehearsal(rest) if rest else "Usage: /psychopomp confirm PSY-123456"
    if verb == "here":
        chat = _current_chat()
        if not chat:
            return ("Send /psychopomp here from the chat where Hermes should reach you: your Telegram, "
                    "WhatsApp or Signal chat with Hermes.")
        store.set_owner_channel(chat)
        return (f"Got it. I'll reach you here on {chat.split(':')[0].capitalize()}: your weekly page, and "
                "check-ins if you ever go quiet.")
    if verb == "test":
        chans = store.read_state()["owner"]["channels"]
        out = []
        for c in chans:
            try:
                store.send_to(c, "☤ Psychopomp: this is where I will reach you.")
                out.append(f"✓ {c.split(':')[0].capitalize()}")
            except Exception as exc:  # noqa: BLE001
                out.append(f"✗ {c.split(':')[0].capitalize()}: {exc}")
        return "Test message: " + (", ".join(out) or "nowhere yet. Send /psychopomp here from your phone.")
    with store.locked_state() as s:
        if verb in ("watch", "arm"):
            s["armed"] = True
            core.heartbeat(s)
            core._log(s, time.time(), "Hermes is keeping watch.")
        elif verb in ("rest", "disarm"):
            s["armed"] = False
            core._log(s, time.time(), "Hermes is resting.")
        elif verb == "reset":
            core.heartbeat(s)
            s["phase"] = "watching"
        elif verb == "invite":
            code = core.invite(s, name=rest)
        view = core.public_view(s)
        snapshot = json.loads(json.dumps(s))
    store.notify_desktop()
    if verb == "invite":
        return ("Forward this to your witness:\n\n"
                f"“I'd like you to be my witness in Psychopomp: if I ever go silent for a long time, my Hermes "
                f"will ask you to confirm before it passes on what I've left for the people I love. To accept, "
                f"send this to my Hermes (the same bot I use): {code}”")
    if verb == "doctor":
        issues = store.doctor(snapshot)
        return "All good. Hermes is keeping watch." if not issues else "Psychopomp doctor:\n- " + "\n- ".join(issues)
    if verb not in ("status", "watch", "arm", "rest", "disarm", "reset"):
        return USAGE
    return _fmt(view)


# --- tools for the agent ---------------------------------------------------------

TOOLS = {
    "psychopomp_status": {
        "description": "Psychopomp status: whether Hermes is keeping watch, the silence so far, the witness, Book "
                       "pages, and the envelopes of sealed letters (never their words).",
        "parameters": {"type": "object", "properties": {}},
    },
    "psychopomp_draft_page": {
        "description": "Propose a page of the user's Book (the weekly look-back, or the yearly review). It is NOT "
                       "added yet: the user approves it (a button in Desktop, or 'yes' in chat, then "
                       "psychopomp_write_page with the draft_id). Follow the result's instructions to show it.",
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string", "description": "A short, evocative title, e.g. 'Small brave things'"},
            "text": {"type": "string", "description": "The page in the user's voice"},
            "kind": {"type": "string", "enum": ["week", "year"]},
        }, "required": ["title", "text"]},
    },
    "psychopomp_write_page": {
        "description": "Add an approved page to the user's Book. ONLY after the user said yes to the final text. "
                       "Pass draft_id for a proposed draft (preferred), or title and text.",
        "parameters": {"type": "object", "properties": {
            "draft_id": {"type": "string"},
            "title": {"type": "string"},
            "text": {"type": "string", "description": "The page exactly as the user approved it"},
            "kind": {"type": "string", "enum": ["week", "year"]},
        }},
    },
    "psychopomp_read_book": {
        "description": "Read the user's most recent Book pages, for continuity in the weekly page or the yearly review.",
        "parameters": {"type": "object", "properties": {"last": {"type": "integer", "default": 8}}},
    },
    "psychopomp_seal_letter": {
        "description": "Seal a letter Hermes carries to someone only if the user goes silent for good and their "
                       "witness confirms. Help write it in the user's voice. ONLY call after the user "
                       "approved the final text. After sealing, its words are never shown again.",
        "parameters": {"type": "object", "properties": {
            "to_name": {"type": "string"},
            "body": {"type": "string"},
            "subject": {"type": "string"},
            "to_target": {"type": "string", "description": "Optional channel, e.g. telegram:<id>. "
                                                           "Empty: the witness passes it on."},
        }, "required": ["to_name", "body"]},
    },
}


def _surface() -> str:
    try:
        return (_ctx.session_surface() or "").lower() if _ctx is not None else ""
    except Exception:
        return ""


def _show_draft(d: dict) -> dict:
    """Desktop draws the draft as a card with an 'Add to my Book' button; other surfaces show text."""
    if _surface() == "desktop":
        return {"show": f'::psychopomp-page{{draft="{d["id"]}"}}',
                "instructions": "Write the `show` line alone as its own paragraph in your reply (it renders the "
                                "page as a card with an 'Add to my Book' button), then ask if they'd like changes. "
                                "Do not repeat the page text."}
    return {"instructions": "Show the title and the full page to the user and ask if they'd like changes. "
                            "When they say yes, call psychopomp_write_page with this draft_id."}


def _tool(name):
    def handler(args: dict, **_kw) -> str:
        try:
            with store.locked_state() as s:
                if name == "psychopomp_status":
                    out = core.public_view(s)
                    out["book"]["pages"] = [{"title": p["title"], "kind": p["kind"], "written_at": p["written_at"]}
                                            for p in out["book"]["pages"]]
                elif name == "psychopomp_draft_page":
                    d = core.draft_page(s, args.get("title", ""), args.get("text", ""), args.get("kind", "week"))
                    out = {"draft_id": d["id"], "week": core.week_label(d["drafted_at"]), **_show_draft(d)}
                elif name == "psychopomp_write_page":
                    if args.get("draft_id"):
                        out = core.approve_draft(s, args["draft_id"])
                    else:
                        out = core.write_page(s, args.get("title", ""), args.get("text", ""), args.get("kind", "week"))
                    out = {**out, "week": core.week_label(out["written_at"]), "note": "Added to the Book."}
                elif name == "psychopomp_read_book":
                    out = {"pages": s["book"]["pages"][-int(args.get("last") or 8):]}
                else:
                    out = {"sealed": core.seal_letter(s, args.get("to_name", ""), args.get("body", ""),
                                                      args.get("subject", ""), args.get("to_target", "")),
                           "note": "Sealed. Its words are now hidden, even from Hermes."}
            store.notify_desktop()
            return json.dumps(out)
        except ValueError as exc:
            return json.dumps({"error": str(exc)})
    return handler


# --- registration -------------------------------------------------------------

def register(ctx):
    global _ctx, _has_skill
    _ctx = ctx
    for name, spec in TOOLS.items():
        ctx.register_tool(name=name, toolset="psychopomp", schema={"name": name, **spec},
                          handler=_tool(name), emoji="☤")
    ctx.register_hook("pre_llm_call", _on_llm_call)
    ctx.register_hook("pre_gateway_dispatch", _on_gateway_message)
    ctx.register_command("psychopomp", run, description="Your Book, your letters, your witness",
                         args_hint="[status|here|invite <name>|rehearse|watch|doctor]")
    try:  # the weekly ritual lives in a skill Hermes loads when you say yes
        ctx.register_skill("weekly-page", Path(__file__).parent / "skills" / "weekly-page" / "SKILL.md")
        _has_skill = True
    except Exception as exc:  # older hosts: the ritual prompt carries the short version
        log.info("psychopomp: skill not registered (%s); using the inline ritual", exc)

    stop = threading.Event()
    threading.Thread(target=_ticker, args=(stop,), name="psychopomp-ticker", daemon=True).start()
    ctx.on_unload(stop.set)
