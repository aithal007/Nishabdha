"""Narrow agent delegation. Every execution requires a fresh holder signature."""

import secrets
import time
from datetime import timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent_identity import (
    delegation_binding,
    delegation_config,
    digest,
    origin,
    public_jwk,
    sign_record,
)
from app.core.agent_models import AgentGrant, AgentNonce, AgentSupportTicket
from app.core.decisions import envelope, persist_decision, record_decision
from app.db import SessionLocal, get_db
from app.models import AuditEntry, BankCallNotice, Call, Customer, utcnow
from app.security import require_app_customer, require_staff

router = APIRouter(tags=["agent identity"])


class GrantInput(BaseModel):
    holder_jwk: dict
    approval_id: str = ""


class ExecuteInput(BaseModel):
    proof: str = Field(max_length=8192)
    action: str = Field(default="support_ticket.create", max_length=64)
    subject: str = Field(min_length=1, max_length=200)


@router.get("/.well-known/jwks.json")
async def jwks():
    return {"keys": [public_jwk()], "issuer": origin()}


@router.get("/api/app/bank-call/{notice_id}/proof")
async def bank_proof(
    notice_id: str,
    c: Customer = Depends(require_app_customer),
    db: AsyncSession = Depends(get_db),
):
    n = await db.get(BankCallNotice, notice_id)
    call = await db.get(Call, n.call_id) if n and n.call_id else None
    if (
        not n
        or n.customer_id != c.id
        or n.status not in ("active", "confirmed")
        or n.expires_at <= utcnow()
        or not call
        or call.customer_id != c.id
        or call.direction != "outbound"
        or call.status != "active"
    ):
        raise HTTPException(404, "no authorized active outbound call")
    now = int(time.time())
    payload = {
        "iss": origin(),
        "aud": c.id,
        "sub": "bank-voice-agent",
        "type": "bank-session",
        "call_id": call.id,
        "notice_id": n.id,
        "reason": n.reason,
        "iat": now,
        "exp": min(
            now + 120, int(n.expires_at.replace(tzinfo=timezone.utc).timestamp())
        ),
        "jti": secrets.token_urlsafe(18),
    }
    payload.update(agent_type="ai", nonce=secrets.token_urlsafe(32))
    return {
        "proof": sign_record(payload),
        "claims": payload,
        "jwks_url": origin() + "/.well-known/jwks.json",
    }


@router.post("/api/app/agents/delegation-binding")
async def binding(body: GrantInput, c: Customer = Depends(require_app_customer)):
    try:
        return {
            "binding_hash": delegation_binding(body.holder_jwk),
            "config": delegation_config(body.holder_jwk),
        }
    except (ValueError, KeyError, jwt.PyJWTError) as exc:
        raise HTTPException(422, "invalid public holder key") from exc


@router.post("/api/app/agents/grants")
async def create_grant(body: GrantInput, c: Customer = Depends(require_app_customer)):
    from app.core.passkeys import consume_delegation_approval

    try:
        config = delegation_config(body.holder_jwk)
    except (ValueError, KeyError, jwt.PyJWTError) as exc:
        raise HTTPException(422, "invalid public holder key") from exc
    async with SessionLocal() as db:
        await db.execute(text("BEGIN IMMEDIATE"))
        if not await consume_delegation_approval(
            db, c.id, body.approval_id, digest(config)
        ):
            raise HTTPException(
                403, "fresh passkey approval bound to this holder and scope required"
            )
        grant = AgentGrant(
            customer_id=c.id,
            holder_jwk=config["holder_jwk"],
            expires_at=utcnow() + timedelta(seconds=600),
        )
        db.add(grant)
        await db.flush()
        await db.commit()
        return {
            "grant_id": grant.id,
            "scope": grant.scope,
            "max_uses": 1,
            "expires_at": grant.expires_at.isoformat() + "Z",
            "agent_type": "delegated_synthetic",
            "authorization": "passkey",
        }


@router.post("/api/app/agents/grants/{grant_id}/revoke")
async def revoke(grant_id: str, c: Customer = Depends(require_app_customer)):
    async with SessionLocal() as db:
        await db.execute(text("BEGIN IMMEDIATE"))
        grant = await db.get(AgentGrant, grant_id)
        if not grant or grant.customer_id != c.id:
            raise HTTPException(404, "grant not found")
        grant.revoked = True
        await db.commit()
    return {"grant_id": grant_id, "revoked": True}


@router.post("/api/agents/grants/{grant_id}/nonce")
async def nonce(grant_id: str, db: AsyncSession = Depends(get_db)):
    grant = await db.get(AgentGrant, grant_id)
    if not grant or grant.revoked or grant.uses >= 1 or grant.expires_at <= utcnow():
        owner = grant.customer_id if grant else None
        await db.rollback()
        signed = await persist_decision(
            customer_id=owner,
            request_id=grant_id,
            operation="delegate_request",
            actor_type="delegate_claim",
            outcome="denied",
            reason="grant unavailable",
        )
        from app.core import audit
        from app.events import DASHBOARD, hub

        decision = {
            "grant_id": grant_id,
            "action": "delegate_request",
            "outcome": "denied",
            "reason": "grant unavailable",
            "decision_id": signed["payload"]["decision_id"],
        }
        await audit.append(
            "agent_decision", {**decision, "signature": signed["signature"]}
        )
        await hub.publish(DASHBOARD, "ticket_agent_decision", decision)
        raise HTTPException(
            403,
            "grant unavailable",
            headers={
                "X-Decision-ID": signed["payload"]["decision_id"],
            },
        )
    n = AgentNonce(
        id=secrets.token_urlsafe(32),
        grant_id=grant.id,
        expires_at=utcnow() + timedelta(seconds=60),
    )
    db.add(n)
    await db.commit()
    return {"nonce": n.id, "audience": origin(), "expires_in": 60}


async def _execute_request(grant_id: str, body: ExecuteInput):
    async with SessionLocal() as db:
        await db.execute(text("BEGIN IMMEDIATE"))
        grant = await db.get(AgentGrant, grant_id)
        if (
            not grant
            or grant.revoked
            or grant.uses >= 1
            or grant.expires_at <= utcnow()
        ):
            raise HTTPException(403, "grant expired, revoked or consumed")
        if body.action != grant.scope:
            raise HTTPException(403, "action outside delegated scope")
        try:
            claims = jwt.decode(
                body.proof,
                jwt.algorithms.ECAlgorithm.from_jwk(grant.holder_jwk),
                algorithms=["ES256"],
                audience=origin(),
                options={
                    "require": [
                        "exp",
                        "iat",
                        "aud",
                        "jti",
                        "grant_id",
                        "nonce",
                        "body_hash",
                    ]
                },
            )
            if (
                claims["grant_id"] != grant.id
                or claims["body_hash"]
                != digest({"action": body.action, "subject": body.subject})
                or claims["exp"] - claims["iat"] > 60
                or time.time() - claims["iat"] > 60
            ):
                raise ValueError("invalid request binding")
            n = await db.get(AgentNonce, claims["nonce"])
            if not n or n.grant_id != grant.id or n.used or n.expires_at <= utcnow():
                raise ValueError("nonce unavailable")
        except (jwt.PyJWTError, ValueError, TypeError, KeyError) as exc:
            raise HTTPException(403, "invalid holder proof or replay") from exc
        n.used = True
        grant.uses += 1
        ticket = AgentSupportTicket(
            grant_id=grant.id, customer_id=grant.customer_id, subject=body.subject
        )
        db.add(ticket)
        await db.flush()
        result = {
            "ticket_id": ticket.id,
            "grant_id": grant.id,
            "action": body.action,
            "subject": body.subject,
            "customer_id": grant.customer_id,
            "agent_type": "delegated_synthetic",
            "status": "executed",
            "iss": origin(),
            "iat": int(time.time()),
        }
        receipt = sign_record(result)
        record = await record_decision(
            db,
            customer_id=grant.customer_id,
            request_id=grant.id,
            operation=body.action,
            actor_type="delegated_ai",
            outcome="executed",
            action_hash=digest({"action": body.action, "subject": body.subject}),
        )
        result.update(decision_id=record.id, decision_receipt=envelope(record))
        await db.commit()
        return {**result, "receipt": receipt}


@router.post("/api/agents/grants/{grant_id}/execute")
async def execute(grant_id: str, body: ExecuteInput):
    from app.core import audit
    from app.events import DASHBOARD, hub

    try:
        result = await _execute_request(grant_id, body)
        decision = {
            "grant_id": grant_id,
            "action": body.action,
            "outcome": "executed",
            "ticket_id": result["ticket_id"],
            "customer_id": result["customer_id"],
        }
    except HTTPException as exc:
        async with SessionLocal() as db:
            grant = await db.get(AgentGrant, grant_id)
            owner = grant.customer_id if grant else None
        signed = await persist_decision(
            customer_id=owner,
            request_id=grant_id,
            operation=body.action,
            actor_type="delegate_claim",
            outcome="denied",
            reason=str(exc.detail),
            action_hash=digest({"action": body.action, "subject": body.subject}),
        )
        decision = {
            "grant_id": grant_id,
            "action": body.action,
            "outcome": "denied",
            "reason": exc.detail,
            "decision_id": signed["payload"]["decision_id"],
        }
        exc.headers = {**(exc.headers or {}), "X-Decision-ID": decision["decision_id"]}
        await audit.append(
            "agent_decision", {**decision, "signature": sign_record(decision)}
        )
        await hub.publish(DASHBOARD, "ticket_agent_decision", decision)
        raise
    decision["decision_id"] = result["decision_id"]
    await audit.append(
        "agent_decision", {**decision, "signature": sign_record(decision)}
    )
    await hub.publish(DASHBOARD, "ticket_agent_decision", decision)
    return result


@router.get("/api/agents/support-tickets", dependencies=[Depends(require_staff)])
async def agent_tickets(db: AsyncSession = Depends(get_db)):
    tickets = (
        await db.execute(
            select(AgentSupportTicket)
            .order_by(AgentSupportTicket.created_at.desc())
            .limit(30)
        )
    ).scalars()
    decisions = (
        await db.execute(
            select(AuditEntry)
            .where(AuditEntry.kind == "agent_decision")
            .order_by(AuditEntry.seq.desc())
            .limit(30)
        )
    ).scalars()
    return {
        "tickets": [
            {
                "id": t.id,
                "customer_id": t.customer_id,
                "subject": t.subject,
                "grant_id": t.grant_id,
            }
            for t in tickets
        ],
        "decisions": [d.payload for d in decisions],
    }
