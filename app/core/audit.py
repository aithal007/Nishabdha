"""Tamper-evident audit log (feature 8): each entry stores SHA-256(prev_hash + entry) and an HMAC.
Editing, deleting or reordering any row breaks `verify_chain()`."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from datetime import datetime

from sqlalchemy import select

from app.config import get_settings
from app.db import session_scope
from app.models import AuditEntry, utcnow

GENESIS = "0" * 64
_lock = asyncio.Lock()


def _num(o):
    """1.0 -> 1 so hashes survive a round-trip through JavaScript (which has no int/float distinction)."""
    if isinstance(o, float) and o.is_integer():
        return int(o)
    if isinstance(o, dict):
        return {k: _num(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_num(v) for v in o]
    return o


def canonical(obj) -> str:
    obj = json.loads(json.dumps(obj, default=str))
    return json.dumps(_num(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def normalize(payload: dict) -> dict:
    return json.loads(canonical(payload or {}))


def entry_hash(prev_hash: str, ts: datetime, call_id: str | None, kind: str, payload: dict) -> str:
    body = canonical({"ts": ts.isoformat(), "call_id": call_id, "kind": kind, "payload": payload})
    return hashlib.sha256((prev_hash + body).encode()).hexdigest()


def sign(h: str) -> str:
    return hmac.new(get_settings().audit_hmac_secret.encode(), h.encode(), hashlib.sha256).hexdigest()


async def append(kind: str, payload: dict, call_id: str | None = None) -> AuditEntry:
    payload = normalize(payload)
    async with _lock:  # serialize appends so the chain never forks
        async with session_scope() as db:
            last = (await db.execute(select(AuditEntry).order_by(AuditEntry.seq.desc()).limit(1))).scalar_one_or_none()
            prev = last.hash if last else GENESIS
            ts = utcnow()
            h = entry_hash(prev, ts, call_id, kind, payload)
            e = AuditEntry(ts=ts, call_id=call_id, kind=kind, payload=payload, prev_hash=prev, hash=h, sig=sign(h))
            db.add(e)
        return e


async def verify_chain() -> dict:
    async with session_scope() as db:
        rows = (await db.execute(select(AuditEntry).order_by(AuditEntry.seq))).scalars().all()
    prev = GENESIS
    for r in rows:
        h = entry_hash(prev, r.ts, r.call_id, r.kind, r.payload)
        if r.prev_hash != prev or r.hash != h or not hmac.compare_digest(r.sig, sign(h)):
            return {"valid": False, "entries": len(rows), "broken_at_seq": r.seq, "kind": r.kind}
        prev = r.hash
    return {"valid": True, "entries": len(rows), "head": prev}


async def call_head(call_id: str) -> dict:
    """Last audit entry for a call - quoted in the evidence report so the report is anchored to the chain."""
    async with session_scope() as db:
        r = (
            await db.execute(select(AuditEntry).where(AuditEntry.call_id == call_id).order_by(AuditEntry.seq.desc()).limit(1))
        ).scalar_one_or_none()
        n = len((await db.execute(select(AuditEntry.seq).where(AuditEntry.call_id == call_id))).all())
    return {"entries": n, "last_seq": r.seq if r else None, "last_hash": r.hash if r else None}
