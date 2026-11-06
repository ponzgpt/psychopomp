"""Psychopomp — Hermes carries your words across time.

A dead man's switch for Hermes Agent. You seal letters. Every time you talk to
Hermes, on any surface, the switch resets. If you fall silent, Hermes checks
in with you; if you never answer, it asks your trusted contact for a code; only
then does it carry your letters to the people you wrote them for.
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
_ctx = None


# --- settings -----------------------------------------------------------------

def _settings() -> dict:
    if _ctx is None:
        return {}
    return {k: _ctx.get_config(k, default) for k, (default, _) in store.SETTINGS.items()}


def _sync(state: dict) -> None:
    store.apply_settings(state, _settings())


# --- the heartbeat: any turn on any surface ----------------------------------

def _on_llm_call(platform=None, **_kw):
    if platform in ("cron",):  # Hermes' own scheduled jobs are not you
        return None
    try:
        with store.locked_state() as s:
            was = s["phase"]
            actions = core.heartbeat(s)
        if actions or was != "watching":
            threading.Thread(target=store.perform, args=(actions,), daemon=True).start()
            store.notify_desktop()
    except Exception as exc:  # never block a turn
        log.warning("psychopomp heartbeat failed: %s", exc)
    return None


# --- omni input: a code on any channel, before the gateway's sender check -----

async def _on_gateway_message(event=None, gateway=None, **_kw):
    try:
        src = event.source
        platform = getattr(src.platform, "value", src.platform)
        sender = f"{platform}:{src.user_id}"
        with store.locked_state() as s:
            actions, handled = core.inbound(s, sender, event.text or "")
        if not handled:
            if actions:
                await asyncio.to_thread(store.perform, actions)
            return None
        replies = [a for a in actions if a["type"] == "send" and a["target"] == sender]
        rest = [a for a in actions if a not in replies]
        adapter = (gateway.adapters or {}).get(src.platform) if gateway else None
        reply = replies[0]["text"] if replies else (
            "Thank you. I will carry the letters now." if rest else "Received.")
        if adapter:
            await adapter.send(src.chat_id, reply)
        threading.Thread(target=store.perform, args=(rest,), daemon=True).start()
        return {"action": "skip", "reason": "psychopomp confirmation"}
    except Exception as exc:
        log.warning("psychopomp inbound check failed: %s", exc)
        return None


# --- the ticker -------------------------------------------------------------

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

def _fmt(view: dict) -> str:
    phases = {
        "watching": "Watching. All is well.",
        "checking_in": f"Checking in with you ({view['checkins_sent']}/{view['checkins']}).",
        "awaiting_trusted": f"Waiting for {view['trusted']['name'] or 'your trusted contact'} to confirm.",
        "delivered": "Delivered. The letters have been carried.",
    }
    unit = "min" if view["day_seconds"] < core.DAY else "days"
    lines = [
        "Psychopomp — Hermes carries your words across time.",
        f"Switch: {'ARMED' if view['armed'] else 'not armed'} · {phases[view['phase']]}",
        f"Silence: {view['silent_days']} of {view['silence_days']} {unit}",
        f"Letters sealed: {len(view['letters'])}"
        + "".join(f"\n  ✉ {l['to_name']} — {l['subject']}" + (" (delivered)" if l["delivered_at"] else "")
                  for l in view["letters"]),
    ]
    return "\n".join(lines)


def run(raw: str) -> str:
    """/psychopomp [status|arm|disarm|doctor|test] — same verbs as `hermes psychopomp`."""
    verb = (raw or "status").strip().split()[0].lower() if (raw or "").strip() else "status"
    with store.locked_state() as s:
        _sync(s)
        if verb == "arm":
            s["armed"] = True
            core.heartbeat(s)
            core._log(s, time.time(), "Armed.")
        elif verb == "disarm":
            s["armed"] = False
            core._log(s, time.time(), "Disarmed.")
        elif verb == "reset":  # after a delivery, start over
            core.heartbeat(s)
            s["phase"] = "watching"
        view = core.public_view(s)
        state_copy = json.loads(json.dumps(s))
    store.notify_desktop()
    if verb == "doctor":
        issues = store.doctor(state_copy)
        return "All good. The switch is ready." if not issues else "Psychopomp doctor:\n- " + "\n- ".join(issues)
    if verb == "test":
        out = []
        for c in view["owner"]["channels"]:
            try:
                store.send_to(c, "Psychopomp test: this is where I will check in with you.")
                out.append(f"✓ {c}")
            except Exception as exc:
                out.append(f"✗ {c}: {exc}")
        return "Test check-in:\n" + ("\n".join(out) or "No owner channels set.")
    if verb not in ("status", "arm", "disarm", "reset"):
        return "Usage: /psychopomp [status|arm|disarm|doctor|test|reset]"
    return _fmt(view)


# --- tools for the agent -------------------------------------------------------

STATUS_SCHEMA = {
    "name": "psychopomp_status",
    "description": "Show the Psychopomp dead man's switch: armed or not, phase, days of silence, "
                   "and the envelopes of sealed letters (never their contents).",
    "parameters": {"type": "object", "properties": {}},
}

SEAL_SCHEMA = {
    "name": "psychopomp_seal_letter",
    "description": (
        "Seal a letter that Hermes will email to someone only if the user goes silent, ignores every "
        "check-in, and their trusted contact confirms. Help the user write it in their own voice, "
        "using what you know of them and of the recipient. ONLY call this after the user has read "
        "the final text and explicitly said to seal it. After sealing, the text is never shown again."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "to_name": {"type": "string", "description": "Who the letter is for"},
            "to_email": {"type": "string", "description": "Recipient email address"},
            "subject": {"type": "string"},
            "body": {"type": "string", "description": "The final letter, exactly as the user approved it"},
        },
        "required": ["to_name", "to_email", "body"],
    },
}


def _status_tool(args: dict, **_kw) -> str:
    with store.locked_state() as s:
        return json.dumps(core.public_view(s))


def _seal_tool(args: dict, **_kw) -> str:
    try:
        with store.locked_state() as s:
            env = core.seal_letter(s, args.get("to_name", ""), args.get("to_email", ""),
                                   args.get("subject", ""), args.get("body", ""))
        store.notify_desktop()
        return json.dumps({"sealed": env, "note": "Sealed. Its words are now hidden, even from Hermes."})
    except ValueError as exc:
        return json.dumps({"error": str(exc)})


# --- registration -------------------------------------------------------------

def _cli_setup(parser):
    parser.add_argument("verb", nargs="?", default="status",
                        choices=["status", "arm", "disarm", "doctor", "test", "reset"])


def _cli_run(args):
    print(run(args.verb))


def register(ctx):
    global _ctx
    _ctx = ctx
    ctx.register_tool(name="psychopomp_status", toolset="psychopomp", schema=STATUS_SCHEMA,
                      handler=_status_tool, emoji="🕯️")
    ctx.register_tool(name="psychopomp_seal_letter", toolset="psychopomp", schema=SEAL_SCHEMA,
                      handler=_seal_tool, emoji="✉️")
    ctx.register_hook("pre_llm_call", _on_llm_call)
    ctx.register_hook("pre_gateway_dispatch", _on_gateway_message)
    ctx.register_command("psychopomp", run, description="Your dead man's switch: status, arm, doctor",
                         args_hint="[status|arm|disarm|doctor|test|reset]")
    ctx.register_cli_command("psychopomp", "Psychopomp dead man's switch", _cli_setup, _cli_run)

    stop = threading.Event()
    threading.Thread(target=_ticker, args=(stop,), name="psychopomp-ticker", daemon=True).start()
    ctx.on_unload(stop.set)
