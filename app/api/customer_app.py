"""Simulated customer mobile app (feature 9 + 11): approve/deny step-ups, see who is calling."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.session import get_session
from app.core.stepup import current_bank_call
from app.db import get_db
from app.events import DASHBOARD, hub
from app.i18n import format_inr
from app.models import BankCallNotice, Card, Customer, StepUp, Ticket, utcnow
from app.security import require_app_customer

router = APIRouter(prefix="/api/app", tags=["customer app"])


@router.get("/me")
async def me(c: Customer = Depends(require_app_customer)):
    return {
        "id": c.id, "name": c.name, "phone_last4": c.phone[-4:], "lang": c.preferred_lang, "voice_enrolled": c.voice_enrolled, "voice_locked": c.voice_locked,
        "accounts": [{"number_last4": a.number[-4:], "kind": a.kind, "balance": format_inr(a.balance_paise), "balance_paise": a.balance_paise} for a in c.accounts],
        "cards": [{"last4": k.last4, "kind": k.kind, "status": k.status, "daily_limit_paise": k.daily_limit_paise, "international": k.international_enabled} for k in c.cards],
    }


@router.get("/pending")
async def pending(c: Customer = Depends(require_app_customer), db: AsyncSession = Depends(get_db)):
    """Pending approvals + current genuine bank call (poll fallback for the WebSocket)."""
    rows = (await db.execute(select(StepUp).where(StepUp.customer_id == c.id, StepUp.status == "pending"))).scalars().all()
    now = utcnow()
    steps = []
    for st in rows:
        if st.expires_at < now:
            st.status = "expired"
            continue
        sess = get_session(st.call_id)
        action = None
        if sess and sess.pending and sess.pending.stepup_id == st.id:
            from app.core.session import describe_action

            action = describe_action(sess.pending.intent, sess.pending.params)
        steps.append({"stepup_id": st.id, "call_id": st.call_id, "action": action, "expires_at": st.expires_at.isoformat() + "Z"})
    n = await current_bank_call(db, c.id)
    await db.commit()
    return {"stepups": steps, "bank_call": None if not n else {"notice_id": n.id, "code": n.code, "reason": n.reason, "call_id": n.call_id}}


async def _resolve(stepup_id: str, c: Customer, db: AsyncSession, approve: bool):
    st = await db.get(StepUp, stepup_id)
    if st is None or st.customer_id != c.id:
        raise HTTPException(404, "request not found")
    if st.status != "pending":
        raise HTTPException(409, f"request already {st.status}")
    if st.expires_at < utcnow():
        st.status = "expired"
        await db.commit()
        raise HTTPException(410, "request expired")
    st.status = "approved" if approve else "denied"
    await db.commit()
    await audit.append("stepup_app_response", {"stepup_id": st.id, "status": st.status, "customer_id": c.id}, st.call_id)
    sess = get_session(st.call_id)
    if sess:
        async with sess._turn_lock:
            await sess.stepup_resolved(st.status, via="app", stepup_id=st.id)
    return {"stepup_id": st.id, "status": st.status}


@router.post("/stepups/{stepup_id}/approve")
async def approve(stepup_id: str, c: Customer = Depends(require_app_customer), db: AsyncSession = Depends(get_db)):
    return await _resolve(stepup_id, c, db, True)


@router.post("/stepups/{stepup_id}/deny")
async def deny(stepup_id: str, c: Customer = Depends(require_app_customer), db: AsyncSession = Depends(get_db)):
    """'This isn't me' - instantly refuses the action on the call and raises a critical ticket."""
    return await _resolve(stepup_id, c, db, False)


@router.get("/bank-call")
async def bank_call(c: Customer = Depends(require_app_customer), db: AsyncSession = Depends(get_db)):
    """Is the bank REALLY calling me right now? If this returns null while someone on the phone claims to be
    the bank, it is an impersonator."""
    n = await current_bank_call(db, c.id)
    await db.commit()
    if not n:
        return {"genuine_bank_call": False, "message": "Unclone Bank is NOT calling you right now. If someone claims to be us, hang up."}
    return {"genuine_bank_call": True, "notice_id": n.id, "code": n.code, "reason": n.reason, "call_id": n.call_id}


@router.post("/bank-call/{notice_id}/{verdict}")
async def bank_call_verdict(notice_id: str, verdict: str, c: Customer = Depends(require_app_customer), db: AsyncSession = Depends(get_db)):
    """verdict = confirm (codes matched) | report (caller said a different code / pressured me)."""
    if verdict not in ("confirm", "report"):
        raise HTTPException(400, "verdict must be confirm or report")
    n = await db.get(BankCallNotice, notice_id)
    if n is None or n.customer_id != c.id:
        raise HTTPException(404, "notice not found")
    n.status = "confirmed" if verdict == "confirm" else "reported"
    if verdict == "report" and n.call_id:
        db.add(Ticket(call_id=n.call_id, customer_id=c.id, severity="high", reasons=["customer reported the bank-call verification code did not match"]))
    await db.commit()
    await audit.append("bank_call_verdict", {"notice_id": n.id, "verdict": verdict, "customer_id": c.id}, n.call_id)
    await hub.publish(DASHBOARD, "bank_call_verdict", {"notice_id": n.id, "verdict": verdict, "call_id": n.call_id, "customer_id": c.id})
    return {"status": n.status}


@router.post("/cards/{last4}/freeze")
async def app_freeze(last4: str, c: Customer = Depends(require_app_customer), db: AsyncSession = Depends(get_db)):
    """In-app kill switch for the real customer."""
    card = (await db.execute(select(Card).where(Card.customer_id == c.id, Card.last4 == last4))).scalar_one_or_none()
    if card is None:
        raise HTTPException(404, "card not found")
    if card.status == "active":
        card.status = "frozen"
    await db.commit()
    await audit.append("app_card_freeze", {"customer_id": c.id, "card": last4})
    return {"card": last4, "status": card.status}
