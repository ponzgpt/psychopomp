"""Psychopomp — Hermes carries your words across time.

Every week Hermes helps you write a page of your Book: what you did, what moved
you, who you loved. Once a year, a review. You can also seal letters for the
people you love. If you ever fall silent for good, Hermes checks in, asks your
trusted contact for a code on any channel, and then carries the Book and the
letters to them. A monthly rehearsal plays the whole passage on a virtual clock.
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import threading
import time

from . import psychopomp_core as core
from . import psychopomp_store as store

log = logging.getLogger("psychopomp")
TICK_SECONDS = 30
RITUAL_EVERY_SECONDS = 6 * 3600  # offer the page at most every 6 h while it is due
_ctx = None


def _settings() -> dict:
    if _ctx is None:
        return {}
    return {k: _ctx.get_config(k, default) for k, (default, _) in store.SETTINGS.items()}


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
                ritual = core.ritual_prompt(due, s["owner"]["name"])
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
        with store.locked_state() as s:
            actions, handled = core.inbound(s, sender, event.text or "", reply_to=reply_to)
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
    "watching": "Watching over you. All is well.",
    "checking_in": "You have been quiet; checking in.",
    "awaiting_trusted": "Waiting for your trusted contact's code.",
    "delivered": "The Book and the letters have been carried.",
}


def _fmt(v: dict) -> str:
    unit = "min" if v["day_seconds"] < core.DAY else "days"
    lines = [
        "☤ Psychopomp — Hermes carries your words across time.",
        f"Switch: {'armed' if v['armed'] else 'at rest'} · {PHASES[v['phase']]} "
        f"(silent {v['silent_days']} of {v['silence_days']} {unit})",
        f"Trusted contact: {v['trusted']['name'] or '—'} ({len(v['trusted']['channels'])} channel(s))",
        f"Book: {len(v['book']['pages'])} page(s)" + (f" · a {v['book']['due']} page is due" if v["book"]["due"] else ""),
        f"Sealed letters: {len(v['letters'])}",
    ]
    return "\n".join(lines)


def run(raw: str) -> str:
    """/psychopomp [status|arm|disarm|invite|rehearse|confirm CODE|doctor|test|reset]"""
    parts = (raw or "").strip().split()
    verb = parts[0].lower() if parts else "status"
    if verb == "rehearse":
        with store.locked_state() as s:
            _sync(s)
        return store.start_rehearsal()[0]
    if verb == "confirm" and len(parts) > 1:
        return store.confirm_rehearsal(parts[1])
    with store.locked_state() as s:
        _sync(s)
        if verb == "arm":
            s["armed"] = True
            core.heartbeat(s)
            core._log(s, time.time(), "Armed.")
        elif verb == "disarm":
            s["armed"] = False
            core._log(s, time.time(), "Put to rest.")
        elif verb == "reset":
            core.heartbeat(s)
            s["phase"] = "watching"
        elif verb == "invite":
            code = core.invite(s)
        view = core.public_view(s)
        snapshot = json.loads(json.dumps(s))
    store.notify_desktop()
    if verb == "invite":
        return ("Forward this to your trusted contact:\n\n"
                f"“I've chosen you as my trusted contact in Psychopomp. Please open a chat with my Hermes "
                f"(the same bot I use) and send it this message: {code}”\n\n"
                "When they do, Hermes will remember how to reach them.")
    if verb == "doctor":
        issues = store.doctor(snapshot)
        return "All good. The switch is ready." if not issues else "Psychopomp doctor:\n- " + "\n- ".join(issues)
    if verb == "test":
        out = []
        for c in view["owner"]["channels"]:
            try:
                store.send_to(c, "Psychopomp test: this is where I will reach you.")
                out.append(f"✓ {c}")
            except Exception as exc:
                out.append(f"✗ {c}: {exc}")
        return "Test message:\n" + ("\n".join(out) or "No channels set for you yet.")
    if verb not in ("status", "arm", "disarm", "reset"):
        return "Usage: /psychopomp [status|arm|disarm|invite|rehearse|confirm CODE|doctor|test|reset]"
    return _fmt(view)


# --- tools for the agent ---------------------------------------------------------

TOOLS = {
    "psychopomp_status": {
        "description": "Psychopomp status: switch phase, silence, trusted contact, Book pages, and the envelopes "
                       "of sealed letters (never their words).",
        "parameters": {"type": "object", "properties": {}},
    },
    "psychopomp_write_page": {
        "description": "Add an approved page to the user's Book: the weekly look-back you wrote together, or the "
                       "yearly review. ONLY call after the user has read the final text and said yes.",
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string", "description": "e.g. 'Week of 9 November: the week we shipped'"},
            "text": {"type": "string", "description": "The page exactly as the user approved it"},
            "kind": {"type": "string", "enum": ["week", "year"]},
        }, "required": ["title", "text"]},
    },
    "psychopomp_read_book": {
        "description": "Read the user's most recent Book pages, for continuity in the weekly page or the yearly review.",
        "parameters": {"type": "object", "properties": {"last": {"type": "integer", "default": 8}}},
    },
    "psychopomp_seal_letter": {
        "description": "Seal a letter Hermes carries to someone only if the user goes silent for good and their "
                       "trusted contact confirms. Help write it in the user's voice. ONLY call after the user "
                       "approved the final text. After sealing, its words are never shown again.",
        "parameters": {"type": "object", "properties": {
            "to_name": {"type": "string"},
            "body": {"type": "string"},
            "subject": {"type": "string"},
            "to_target": {"type": "string", "description": "Optional channel: telegram:<id>, email:<address>. "
                                                           "Empty: the trusted contact passes it on."},
        }, "required": ["to_name", "body"]},
    },
}


def _tool(name):
    def handler(args: dict, **_kw) -> str:
        try:
            with store.locked_state() as s:
                if name == "psychopomp_status":
                    out = core.public_view(s)
                    out["book"]["pages"] = [{"title": p["title"], "kind": p["kind"], "written_at": p["written_at"]}
                                            for p in out["book"]["pages"]]
                elif name == "psychopomp_write_page":
                    out = core.write_page(s, args.get("title", ""), args.get("text", ""), args.get("kind", "week"))
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

def _cli_setup(parser):
    parser.add_argument("verb", nargs="*", default=["status"])


def _cli_run(args):
    if args.verb[:1] == ["rehearse"]:  # a CLI process must stay alive while the rehearsal plays
        msg, thread = store.start_rehearsal()
        print(msg)
        if thread:
            thread.join()
            print(run("status"))
        return
    print(run(" ".join(args.verb)))


def register(ctx):
    global _ctx
    _ctx = ctx
    for name, spec in TOOLS.items():
        ctx.register_tool(name=name, toolset="psychopomp", schema={"name": name, **spec},
                          handler=_tool(name), emoji="☤")
    ctx.register_hook("pre_llm_call", _on_llm_call)
    ctx.register_hook("pre_gateway_dispatch", _on_gateway_message)
    ctx.register_command("psychopomp", run, description="Your Book, your letters, your switch",
                         args_hint="[status|arm|invite|rehearse|doctor|test]")
    ctx.register_cli_command("psychopomp", "Psychopomp: your Book, your letters, your switch", _cli_setup, _cli_run)

    stop = threading.Event()
    threading.Thread(target=_ticker, args=(stop,), name="psychopomp-ticker", daemon=True).start()
    ctx.on_unload(stop.set)
