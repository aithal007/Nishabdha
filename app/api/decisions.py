"""Authenticated decision exports. No recordings, tokens or detector scores."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.decisions import DecisionRecord, envelope
from app.db import get_db
from app.models import Customer
from app.security import require_app_customer, require_staff

router = APIRouter(tags=["decision receipts"])
AppCustomer = Annotated[Customer, Depends(require_app_customer)]
Database = Annotated[AsyncSession, Depends(get_db)]


@router.get("/api/app/decisions")
async def customer_decisions(c: AppCustomer, db: Database):
    rows = (
        await db.execute(
            select(DecisionRecord)
            .where(DecisionRecord.customer_id == c.id)
            .order_by(DecisionRecord.created_at.desc())
            .limit(30)
        )
    ).scalars()
    return {"decisions": [envelope(row) for row in rows]}


@router.get("/api/app/decisions/{decision_id}")
async def customer_decision(decision_id: str, c: AppCustomer, db: Database):
    row = await db.get(DecisionRecord, decision_id)
    if not row or row.customer_id != c.id:
        raise HTTPException(404, "decision not found")
    return envelope(row)


@router.get("/api/decisions", dependencies=[Depends(require_staff)])
async def staff_decisions(db: Database):
    rows = (
        await db.execute(
            select(DecisionRecord).order_by(DecisionRecord.created_at.desc()).limit(100)
        )
    ).scalars()
    return {"decisions": [envelope(row) for row in rows]}
