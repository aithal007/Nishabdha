"""WebSockets.

/ws/call/{call_id}?token=...      caller audio in (binary PCM16 mono, 16 kHz default), agent events out
/ws/dashboard?staff_key=...       fraud-desk live feed (every call's events)
/ws/customer/{customer_id}?token= simulated customer phone app (step-up requests, bank-call codes, alerts)

Caller -> server JSON messages:
  {"type":"config","sample_rate":48000}         if not sending 16 kHz
  {"type":"end_utterance"}                       push-to-talk released (optional; server VAD also ends turns)
  {"type":"playback","id":"m3","state":"ended"}  agent audio finished playing (used to time liveness answers)
  {"type":"text","text":"..."}                   typed turn
  {"type":"hangup"} / {"type":"ping"}
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.audio import StreamResampler, float_to_pcm16, pcm16_to_float
from app.config import get_settings
from app.core.session import get_session
from app.db import session_scope
from app.events import DASHBOARD, call_topic, customer_topic, hub
from app.models import Call, Customer
from app.security import _eq, is_staff

log = logging.getLogger("unclone.ws")
router = APIRouter()


async def _reject(ws: WebSocket, code: int) -> None:
    """Accept then close with an app code (4401 bad key/token, 4409 call not active). Closing before accept
    makes the browser see a bare 1006 'connection failed', which the UI can't explain to the user."""
    await ws.accept()
    await ws.close(code=code)


class _WSSender:
    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.lock = asyncio.Lock()

    async def __call__(self, kind: str, data: dict):
        async with self.lock:
            await self.ws.send_text(json.dumps({"event": kind, "data": data}, default=str, ensure_ascii=False))


@router.websocket("/ws/call/{call_id}")
async def ws_call(ws: WebSocket, call_id: str, token: str = ""):
    async with session_scope() as db:
        call = await db.get(Call, call_id)
        ok = call is not None and _eq(token, (call.meta or {}).get("token"))
    sess = get_session(call_id)
    if not ok or sess is None:
        await _reject(ws, 4401 if not ok else 4409)
        return
    await ws.accept()
    s = get_settings()
    sender = _WSSender(ws)
    sess.senders.append(sender)
    resampler: StreamResampler | None = None
    await sender("ready", {"call_id": call_id, "expect": {"encoding": "pcm_s16le", "channels": 1, "sample_rate": 16000}, "customer_id": sess.customer_id, "enrolled": sess.enrolled, "lang": sess.lang})
    await sess.greet()
    reason = "caller_disconnected"
    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                b = msg["bytes"]
                if len(b) > s.max_ws_frame_bytes:
                    await sender("error", {"message": f"audio frame too large (max {s.max_ws_frame_bytes} bytes)"})
                    continue
                if resampler is not None:
                    b = float_to_pcm16(resampler.feed(pcm16_to_float(b)))
                await sess.feed_pcm16(b)
                continue
            try:
                m = json.loads(msg.get("text") or "{}")
            except json.JSONDecodeError:
                await sender("error", {"message": "invalid JSON"})
                continue
            typ = m.get("type")
            if typ == "config":
                sr = int(m.get("sample_rate") or 16000)
                if not 8000 <= sr <= 96000:
                    await sender("error", {"message": "unsupported sample_rate"})
                else:
                    resampler = None if sr == 16000 else StreamResampler(sr, 16000)
            elif typ == "end_utterance":
                await sess.end_of_utterance()
            elif typ == "playback":
                sess.playback_event(str(m.get("id", "")), str(m.get("state", "")))
            elif typ == "text":
                txt = str(m.get("text") or "")[:1000]
                if txt.strip():
                    sess.spawn_text(txt)
            elif typ == "hangup":
                reason = "caller_hangup"
                break
            elif typ == "ping":
                await sender("pong", {})
            if sess.ended:
                break
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("ws_call error")
    finally:
        if sender in sess.senders:
            sess.senders.remove(sender)
        if not sess.ended and not sess.senders:
            # shield: a client disconnect may cancel this handler, but the call must still be closed
            # cleanly (recording saved, status 'ended', session released)
            try:
                await asyncio.shield(asyncio.ensure_future(sess.end(reason)))
            except asyncio.CancelledError:
                pass
        try:
            await ws.close()
        except Exception:
            pass


async def _pump(ws: WebSocket, topics: list[str], hello: dict):
    await ws.accept()
    for tp in topics:
        await hub.subscribe(tp, ws)
    try:
        await ws.send_text(json.dumps({"event": "hello", "data": hello}, default=str))
        while True:
            msg = await ws.receive_text()
            if msg == "ping" or '"ping"' in msg:
                await ws.send_text(json.dumps({"event": "pong", "data": {}}))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        for tp in topics:
            await hub.unsubscribe(tp, ws)


@router.websocket("/ws/dashboard")
async def ws_dashboard(ws: WebSocket, staff_key: str = ""):
    if not is_staff(staff_key):
        await _reject(ws, 4401)
        return
    await _pump(ws, [DASHBOARD], {"role": "fraud_desk"})


@router.websocket("/ws/watch/{call_id}")
async def ws_watch(ws: WebSocket, call_id: str, staff_key: str = ""):
    if not is_staff(staff_key):
        await _reject(ws, 4401)
        return
    await _pump(ws, [call_topic(call_id)], {"call_id": call_id})


@router.websocket("/ws/customer/{customer_id}")
async def ws_customer(ws: WebSocket, customer_id: str, token: str = ""):
    async with session_scope() as db:
        c = (await db.execute(select(Customer).where(Customer.id == customer_id))).scalar_one_or_none()
        ok = c is not None and _eq(token, c.app_token)
    if not ok:
        await _reject(ws, 4401)
        return
    await _pump(ws, [customer_topic(customer_id)], {"customer_id": customer_id})
