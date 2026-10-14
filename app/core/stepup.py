"""Step-up approval + bank-calling codes (features 9 and 11).

Rules enforced here:
  * the approval goes ONLY to the customer's registered app/device (the "old number"); the step-up
    module never receives a new mobile number, so it physically cannot send the OTP there
  * codes are stored as HMAC hashes, expire, are single-use and lock after N wrong attempts
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import BankCallNotice, StepUp, utcnow


def _hash(stepup_id: str, code: str) -> str:
    key = get_settings().audit_hmac_secret.encode()
    return hmac.new(key, f"{stepup_id}:{code}".encode(), hashlib.sha256).hexdigest()


def new_code(n: int = 6) -> str:
    return "".join(secrets.choice("0123456789") for _ in range(n))


async def create_stepup(db: AsyncSession, call_id: str, action_id: str, customer_id: str) -> tuple[StepUp, str]:
    s = get_settings()
    code = new_code(6)
    st = StepUp(call_id=call_id, action_id=action_id, customer_id=customer_id, channel="registered_app", code_hash="", expires_at=utcnow() + timedelta(seconds=s.otp_ttl_s))
    db.add(st)
    await db.flush()
    st.code_hash = _hash(st.id, code)
    return st, code


def code_matches(st: StepUp, code: str) -> bool:
    """Pure comparison - does not count an attempt."""
    return hmac.compare_digest(st.code_hash, _hash(st.id, code or ""))


def check_code(st: StepUp, code: str) -> str:
    """Mutates attempts/status. Returns approved | wrong | expired | locked | closed."""
    s = get_settings()
    if st.status != "pending":
        return "closed"
    if utcnow() > st.expires_at:
        st.status = "expired"
        return "expired"
    st.attempts += 1
    if hmac.compare_digest(st.code_hash, _hash(st.id, code or "")):
        st.status = "approved"
        return "approved"
    if st.attempts >= s.otp_max_attempts:
        st.status = "locked"
        return "locked"
    return "wrong"


async def active_stepup(db: AsyncSession, stepup_id: str) -> StepUp | None:
    return (await db.execute(select(StepUp).where(StepUp.id == stepup_id))).scalar_one_or_none()


async def create_bank_call_notice(db: AsyncSession, customer_id: str, call_id: str | None, reason: str) -> BankCallNotice:
    s = get_settings()
    # one active notice per customer: older ones end
    for old in (await db.execute(select(BankCallNotice).where(BankCallNotice.customer_id == customer_id, BankCallNotice.status == "active"))).scalars():
        old.status = "ended"
    n = BankCallNotice(customer_id=customer_id, call_id=call_id, code=new_code(4), reason=reason[:200], expires_at=utcnow() + timedelta(seconds=s.bank_call_code_ttl_s))
    db.add(n)
    await db.flush()
    return n


async def current_bank_call(db: AsyncSession, customer_id: str) -> BankCallNotice | None:
    n = (
        await db.execute(
            select(BankCallNotice).where(BankCallNotice.customer_id == customer_id, BankCallNotice.status == "active").order_by(BankCallNotice.created_at.desc()).limit(1)
        )
    ).scalar_one_or_none()
    if n and n.expires_at < utcnow():
        n.status = "expired"
        return None
    return n
