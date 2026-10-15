"""Durable, privacy-minimized decisions; signatures attest to application records."""

import hashlib
from datetime import datetime

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.config import get_settings
from app.core.agent_identity import origin, sign_record
from app.db import Base, session_scope
from app.models import new_id, utcnow

POLICY_VERSION = 3
MESSAGES = {
    "verification_required": "Current voice verification is incomplete. Retry or contact bank support.",
    "approval_required": "Review the exact request in your bank app and approve with your passkey.",
    "transaction_changed": "The transaction changed or expired. Start a new request.",
    "session_restricted": "This session cannot perform the request. Contact bank support.",
    "scope_denied": "This assistant does not have permission for that operation.",
    "grant_unavailable": "The assistant permission expired, was revoked, or has already been used.",
    "invalid_proof": "The signed request could not be verified or was replayed.",
    "passkey_invalid": "Passkey verification failed or expired. Request a fresh approval in the bank app.",
    "policy_denied": "The request does not meet bank policy. Contact bank support.",
    "challenge_required": "Complete the supplementary voice challenge.",
    "checks_passed": "Verification checks passed. Any required action approval still applies.",
    "executed": "The authorized action completed.",
}


class DecisionRecord(Base):
    __tablename__ = "decision_records"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    customer_id: Mapped[str | None] = mapped_column(String(40), index=True)
    call_id: Mapped[str | None] = mapped_column(String(40), index=True)
    request_id: Mapped[str] = mapped_column(String(80), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    signature: Mapped[str] = mapped_column(String(8192))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


def reason_code(reason: str, outcome: str) -> str:
    """Map internal reasons to a finite vocabulary; never expose detector thresholds."""
    r = reason.lower()
    if outcome == "executed":
        return "executed"
    if "scope" in r:
        return "scope_denied"
    if "grant" in r and any(
        x in r for x in ("expired", "revoked", "consumed", "unavailable")
    ):
        return "grant_unavailable"
    if "proof" in r or "replay" in r:
        return "invalid_proof"
    if "passkey" in r and any(x in r for x in ("failed", "expired", "used", "unknown")):
        return "passkey_invalid"
    if "changed" in r or "transaction approval expired" in r:
        return "transaction_changed"
    if "locked" in r or "ended" in r or "synthetic" in r or "mismatch" in r:
        return "session_restricted"
    if "passkey" in r or outcome == "stepup":
        return "approval_required"
    if outcome == "challenge":
        return "challenge_required"
    if outcome == "hold" or any(
        x in r for x in ("verification", "evidence", "detectifai")
    ):
        return "verification_required"
    return "checks_passed" if outcome == "allow" else "policy_denied"


def envelope(row: DecisionRecord) -> dict:
    return {"payload": row.payload, "signature": row.signature}


async def record_decision(
    db: AsyncSession,
    *,
    customer_id: str | None,
    request_id: str,
    operation: str,
    actor_type: str,
    outcome: str,
    reason: str = "",
    call_id: str | None = None,
    action_hash: str | None = None,
    evidence: dict | None = None,
) -> DecisionRecord:
    evidence = evidence or {}
    if action_hash is None:
        from app.core.security_models import FrozenTransfer

        frozen = await db.get(FrozenTransfer, request_id)
        if frozen and frozen.customer_id == customer_id:
            action_hash = frozen.action_hash
    code = reason_code(reason, outcome)
    mode = (
        "simulated"
        if get_settings().app_env == "test" or evidence.get("provenance") == "mock"
        else "application"
    )
    if evidence.get("provenance") == "detectifai" and get_settings().app_env != "test":
        mode = "provider"
    row = DecisionRecord(
        id=new_id("decision"),
        customer_id=customer_id,
        call_id=call_id,
        request_id=request_id,
        payload={},
        signature="",
    )
    row.payload = {
        "schema": "nishabdha.decision.v1",
        "decision_id": row.id,
        "iss": origin(),
        "request_id": request_id,
        "operation": operation,
        "actor_type": actor_type,
        "action_hash": action_hash,
        "subject_ref": hashlib.sha256(f"{origin()}:{customer_id}".encode()).hexdigest()
        if customer_id
        else None,
        "policy_version": POLICY_VERSION,
        "outcome": outcome,
        "banking_mode": "simulated",
        "reason_codes": [code],
        "message": MESSAGES[code],
        "recorded_at": utcnow().isoformat() + "Z",
        "mode": mode,
        "evidence": {
            k: evidence[k]
            for k in (
                "status",
                "provenance",
                "audio_hash",
                "utterance_id",
                "track",
                "checked_at",
                "speaker_source",
                "spoof_source",
                "capture_mode",
            )
            if k in evidence
        },
    }
    row.signature = sign_record(row.payload)
    db.add(row)
    await db.flush()
    return row


async def persist_decision(**kwargs) -> dict:
    async with session_scope() as db:
        row = await record_decision(db, **kwargs)
        return envelope(row)
