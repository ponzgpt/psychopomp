"""Desktop backend: /api/plugins/psychopomp/* for desktop/plugin.js."""

from __future__ import annotations

import sys
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psychopomp_core as core  # noqa: E402
import psychopomp_store as store  # noqa: E402

router = APIRouter()


@router.get("/state")
async def state():
    with store.locked_state() as s:
        return core.public_view(s)


@router.post("/seal")
async def seal(body: dict):
    try:
        with store.locked_state() as s:
            env = core.seal_letter(s, body.get("to_name", ""), body.get("body", ""),
                                   body.get("subject", ""), body.get("to_target", ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    store.notify_desktop()
    return env


@router.post("/withdraw")
async def withdraw(body: dict):
    with store.locked_state() as s:
        ok = core.unseal(s, body.get("id", ""))
    store.notify_desktop()
    return {"ok": ok}


@router.post("/arm")
async def arm(body: dict):
    with store.locked_state() as s:
        s["armed"] = bool(body.get("armed"))
        if s["armed"]:
            core.heartbeat(s)
        core._log(s, time.time(), "Armed." if s["armed"] else "Disarmed.")
        view = core.public_view(s)
    store.notify_desktop()
    return view


@router.post("/rehearse")
async def rehearse(body: dict):
    msg, thread = store.start_rehearsal(mirror=bool(body.get("mirror")), need_channel=False)
    return {"message": msg, "started": thread is not None}


@router.post("/rehearsal/stop")
async def rehearsal_stop():
    return {"ok": store.stop_rehearsal()}


@router.post("/rehearsal/confirm")
async def rehearsal_confirm(body: dict):
    return {"message": store.confirm_rehearsal(body.get("code", ""))}


@router.post("/invite")
async def invite():
    with store.locked_state() as s:
        code = core.invite(s)
    store.notify_desktop()
    return {"code": code}
