"""Auth helpers. Three principals:
  * staff (fraud desk / admin)      -> header X-Staff-Key (or ?staff_key= for WebSockets)
  * customer app (simulated phone)  -> header X-App-Token (or ?token=) bound to one customer
  * caller client for one call      -> X-Call-Token (or ?token=) returned when the call is created
"""
from __future__ import annotations

import hmac

from fastapi import Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.models import Call, Customer


def _eq(a: str | None, b: str | None) -> bool:
    return bool(a) and bool(b) and hmac.compare_digest(str(a), str(b))


def is_staff(key: str | None) -> bool:
    return _eq(key, get_settings().staff_api_key)


async def require_staff(x_staff_key: str | None = Header(None), staff_key: str | None = Query(None)) -> str:
    if not is_staff(x_staff_key or staff_key):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "staff key required (X-Staff-Key)")
    return "staff"


async def require_app_customer(
    x_app_token: str | None = Header(None), token: str | None = Query(None), db: AsyncSession = Depends(get_db)
) -> Customer:
    tok = x_app_token or token
    if not tok:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "app token required (X-App-Token)")
    from sqlalchemy import select

    c = (await db.execute(select(Customer).where(Customer.app_token == tok))).scalar_one_or_none()
    if c is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid app token")
    return c


async def check_call_token(db: AsyncSession, call_id: str, token: str | None, staff_key: str | None = None) -> Call:
    call = await db.get(Call, call_id)
    if call is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "call not found")
    if not (is_staff(staff_key) or _eq(token, (call.meta or {}).get("token"))):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "call token required (X-Call-Token)")
    return call
