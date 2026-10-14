"""Call lifecycle REST API + REST turn fallback (upload an utterance file instead of streaming)."""
from __future__ import annotations

import asyncio
import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audio import SR, AudioError, decode_any
from app.config import get_settings
from app.core.evidence import build_report, verify_report
from app.core.session import SESSIONS, CallSession, get_session
from app.core.stepup import create_bank_call_notice
from app.db import get_db, session_scope
from app.events import call_topic, customer_topic, hub
from app.i18n import speak_digits, t
from app.models import Call, Customer
from app.security import check_call_token, is_staff, require_staff

router = APIRouter(prefix="/api", tags=["calls"])


class CallCreate(BaseModel):
    customer_id: str | None = Field(None, description="Known customer (e.g. from caller ID / app). Treated as a CLAIM - voice still proves it.")
    caller_number: str | None = Field(None, description="Caller ID; matched to a registered mobile if present")
    lang: str = Field("en", pattern="^(en|hi|kn)$")
    channel: str = Field("web", max_length=20)
    greet: bool = True


class BankCallCreate(BaseModel):
    customer_id: str
    reason: str = Field("Account security check", max_length=200)
    lang: str | None = Field(None, pattern="^(en|hi|kn)$")


class TextTurn(BaseModel):
    text: str = Field(..., min_length=1, max_length=1000)


async def _open_session(db: AsyncSession, *, customer_id, caller_number, lang, channel, direction) -> tuple[Call, CallSession, str]:
    if customer_id and await db.get(Customer, customer_id) is None:
        raise HTTPException(404, "customer not found")  # validate BEFORE creating a live session
    token = secrets.token_urlsafe(24)
    call = Call(direction=direction, channel=channel, caller_number=(caller_number or "")[-15:], lang=lang, meta={"token": token})
    db.add(call)
    await db.commit()
    sess = CallSession(call_id=call.id, lang=lang, direction=direction)
    SESSIONS[call.id] = sess
    sess.start()
    cid = customer_id
    if not cid and caller_number:
        digits = "".join(ch for ch in caller_number if ch.isdigit())[-10:]
        c = (await db.execute(select(Customer).where(Customer.phone == digits))).scalar_one_or_none()
        cid = c.id if c else None
    if cid and not await sess.load_customer(cid):
        await sess.end("invalid_customer")
        raise HTTPException(404, "customer not found")
    await sess.emit("call_started", {"direction": direction, "channel": channel, "lang": lang, "customer_id": sess.customer_id}, to_caller=False)
    return call, sess, token


def _call_links(call_id: str, token: str) -> dict:
    return {"call_id": call_id, "call_token": token, "ws_url": f"/ws/call/{call_id}?token={token}"}


@router.post("/calls")
async def create_call(body: CallCreate, db: AsyncSession = Depends(get_db)):
    """Start an inbound call. Returns the call token for the WebSocket / REST turns."""
    call, sess, token = await _open_session(db, customer_id=body.customer_id, caller_number=body.caller_number, lang=body.lang, channel=body.channel, direction="inbound")
    if sess.customer_id:
        await hub.publish(customer_topic(sess.customer_id), "call_connected", {"call_id": call.id, "message": "You are connected to Unclone Bank's verified phone line."})
    if body.greet:
        # greeting is spoken when the caller's WebSocket connects (so the audio isn't lost); REST clients get it via /events
        sess.greet_pending = True
    return {**_call_links(call.id, token), "customer_id": sess.customer_id, "enrolled": sess.enrolled}


@router.post("/bank-calls", dependencies=[Depends(require_staff)])
async def create_bank_call(body: BankCallCreate, db: AsyncSession = Depends(get_db)):
    """Two-way trust: the bank calls the customer. A one-time code appears in the customer's app first,
    and the agent says the same code - so the customer can tell a real bank call from an impersonator."""
    cust = await db.get(Customer, body.customer_id)
    if cust is None:
        raise HTTPException(404, "customer not found")
    lang = body.lang or cust.preferred_lang
    call, sess, token = await _open_session(db, customer_id=cust.id, caller_number=None, lang=lang, channel="outbound", direction="outbound")
    async with session_scope() as s2:
        n = await create_bank_call_notice(s2, cust.id, call.id, body.reason)
        notice = {"notice_id": n.id, "code": n.code, "reason": n.reason, "expires_at": n.expires_at.isoformat() + "Z", "call_id": call.id}
    await hub.publish(customer_topic(cust.id), "incoming_bank_call", notice)
    sess.greet_text = t("greeting_outbound", lang, name=cust.name.split()[0], code_spoken=speak_digits(notice["code"], lang))
    sess.greet_pending = True
    await sess.emit("bank_verify_code", {"notice_id": notice["notice_id"], "direction": "outbound"}, to_caller=False)
    return {**_call_links(call.id, token), "notice_id": notice["notice_id"]}


async def _session_or_404(call_id: str) -> CallSession:
    sess = get_session(call_id)
    if sess is None:
        raise HTTPException(409, "call is not active")
    return sess


class _Collector:
    def __init__(self):
        self.events: list[dict] = []

    async def __call__(self, kind: str, data: dict):
        self.events.append({"event": kind, "data": data})


class _TopicTap:
    """Pretends to be a WebSocket on the call topic, to return internal (fraud-desk) events to staff callers."""

    def __init__(self):
        self.events: list[dict] = []

    async def send_text(self, msg: str):
        import json

        m = json.loads(msg)
        self.events.append({"event": m["event"], "data": m["data"]})


async def _with_collector(sess: CallSession, coro_fn, staff: bool = False, timeout: float = 120.0) -> dict:
    col = _Collector()
    tap = _TopicTap() if staff else None
    sess.senders.append(col)
    if tap:
        await hub.subscribe(call_topic(sess.call_id), tap)
    try:
        if getattr(sess, "greet_pending", False):
            await sess.greet()
        await coro_fn()
        await sess.drain(timeout)
        await asyncio.sleep(0)  # let scheduled refusal tasks start
        await sess.drain(timeout)
        if sess._turn_lock.locked():
            async with sess._turn_lock:
                pass
    finally:
        if col in sess.senders:
            sess.senders.remove(col)
        if tap:
            await hub.unsubscribe(call_topic(sess.call_id), tap)
    out = {"events": col.events}
    if tap:
        out["internal"] = tap.events  # every event incl. fraud-desk-only ones (staff only - never reveal detection to the caller)
    return out


@router.post("/calls/{call_id}/turn")
async def audio_turn(
    call_id: str,
    file: UploadFile = File(..., description="One caller utterance (wav/mp3/webm/ogg)"),
    x_call_token: str | None = Header(None),
    x_staff_key: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """REST fallback for one utterance: runs the same pipeline as the WebSocket (continuous checks + turn)."""
    await check_call_token(db, call_id, x_call_token)
    sess = await _session_or_404(call_id)
    s = get_settings()
    raw = await file.read(s.max_upload_bytes + 1)
    if len(raw) > s.max_upload_bytes:
        raise HTTPException(413, "audio file too large")
    try:
        x = await asyncio.to_thread(decode_any, raw)
    except AudioError as e:
        raise HTTPException(400, str(e))
    if x.size < SR * 0.3:
        raise HTTPException(400, "audio too short")

    return await _with_collector(sess, lambda: sess.ingest_whole_utterance(x), staff=is_staff(x_staff_key))


@router.post("/calls/{call_id}/text")
async def text_turn(call_id: str, body: TextTurn, x_call_token: str | None = Header(None), x_staff_key: str | None = Header(None), db: AsyncSession = Depends(get_db)):
    """Typed turn (testing/accessibility). Typed input carries no voice evidence, so sensitive actions fall back to app approval."""
    await check_call_token(db, call_id, x_call_token)
    sess = await _session_or_404(call_id)
    return await _with_collector(sess, lambda: sess.handle_text(body.text), staff=is_staff(x_staff_key))


@router.post("/calls/{call_id}/greet")
async def greet(call_id: str, x_call_token: str | None = Header(None), db: AsyncSession = Depends(get_db)):
    await check_call_token(db, call_id, x_call_token)
    sess = await _session_or_404(call_id)
    return await _with_collector(sess, lambda: asyncio.sleep(0))


@router.post("/calls/{call_id}/end")
async def end_call(call_id: str, x_call_token: str | None = Header(None), x_staff_key: str | None = Header(None), db: AsyncSession = Depends(get_db)):
    await check_call_token(db, call_id, x_call_token, x_staff_key)
    sess = get_session(call_id)
    if sess:
        await sess.end("caller_hangup")
    return {"ended": True}


@router.post("/calls/{call_id}/terminate", dependencies=[Depends(require_staff)])
async def terminate_call(call_id: str):
    """Fraud desk kills a live call."""
    sess = get_session(call_id)
    if sess is None:
        raise HTTPException(409, "call is not active")
    await sess.say(t("call_locked", sess.lang), kind="refusal")
    await sess.end("terminated_by_fraud_desk")
    return {"terminated": True}


@router.get("/calls", dependencies=[Depends(require_staff)])
async def list_calls(limit: int = Query(50, ge=1, le=500), status: str | None = None, db: AsyncSession = Depends(get_db)):
    q = select(Call).order_by(Call.started_at.desc()).limit(limit)
    if status:
        q = q.where(Call.status == status)
    rows = (await db.execute(q)).scalars().all()
    out = []
    for c in rows:
        live = get_session(c.id)
        out.append({
            "id": c.id, "customer_id": c.customer_id, "direction": c.direction, "status": c.status, "risk_state": live.trust.risk_state if live else c.risk_state,
            "trust": live.trust.trust if live else c.trust, "outcome": c.outcome, "lang": live.lang if live else c.lang,
            "started_at": c.started_at.isoformat() + "Z", "ended_at": c.ended_at.isoformat() + "Z" if c.ended_at else None, "live": live is not None,
        })
    return {"calls": out}


@router.get("/calls/{call_id}", dependencies=[Depends(require_staff)])
async def get_call(call_id: str, db: AsyncSession = Depends(get_db)):
    c = await db.get(Call, call_id)
    if c is None:
        raise HTTPException(404, "call not found")
    live = get_session(call_id)
    return {
        "id": c.id, "customer_id": c.customer_id, "direction": c.direction, "status": c.status, "outcome": c.outcome,
        "risk_state": c.risk_state, "trust": c.trust, "live": live is not None,
        "live_state": {**live.trust.snapshot(), "pressure": round(live.pressure.level, 3), "pressure_cues": live.pressure.cues,
                       "pending": None if not live.pending else {"action_id": live.pending.action_id, "intent": live.pending.intent, "stage": live.pending.stage}} if live else None,
    }


@router.get("/calls/{call_id}/report", dependencies=[Depends(require_staff)])
async def call_report(call_id: str):
    r = await build_report(call_id)
    if r is None:
        raise HTTPException(404, "call not found")
    return r


@router.post("/reports/verify", dependencies=[Depends(require_staff)])
async def report_verify(report: dict):
    """Paste a previously downloaded report: proves it was not altered."""
    return verify_report(report)


def _safe_clip(name: str) -> Path:
    base = (get_settings().data_dir / "clips").resolve()
    p = (base / name).resolve()
    if p.parent != base or not p.name.endswith(".wav") or not p.exists():
        raise HTTPException(404, "clip not found")
    return p


@router.get("/calls/{call_id}/clips/{name}", dependencies=[Depends(require_staff)])
async def get_clip(call_id: str, name: str):
    if not name.startswith(call_id + "_"):
        raise HTTPException(404, "clip not found")
    return FileResponse(_safe_clip(name), media_type="audio/wav")


@router.get("/calls/{call_id}/recording", dependencies=[Depends(require_staff)])
async def get_recording(call_id: str):
    return FileResponse(_safe_clip(f"{call_id}_full.wav"), media_type="audio/wav")
