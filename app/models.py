"""Database tables. Money is stored in paise (int) to avoid float errors. All timestamps are naive UTC."""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("cus"))
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(20), unique=True, index=True)  # registered mobile (E.164-ish digits)
    preferred_lang: Mapped[str] = mapped_column(String(5), default="en")
    app_token: Mapped[str] = mapped_column(String(64), default=lambda: secrets.token_urlsafe(24))  # simulated mobile app auth
    voice_enrolled: Mapped[bool] = mapped_column(Boolean, default=False)
    voice_locked: Mapped[bool] = mapped_column(Boolean, default=False)  # set after confirmed fraud
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    accounts: Mapped[list["Account"]] = relationship(back_populates="customer", lazy="selectin")
    cards: Mapped[list["Card"]] = relationship(back_populates="customer", lazy="selectin")


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("acc"))
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    number: Mapped[str] = mapped_column(String(20))
    kind: Mapped[str] = mapped_column(String(20), default="savings")
    balance_paise: Mapped[int] = mapped_column(Integer, default=0)
    customer: Mapped[Customer] = relationship(back_populates="accounts")


class Transaction(Base):
    __tablename__ = "transactions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("txn"))
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True)
    amount_paise: Mapped[int] = mapped_column(Integer)  # negative = debit
    description: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Card(Base):
    __tablename__ = "cards"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("card"))
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    last4: Mapped[str] = mapped_column(String(4))
    kind: Mapped[str] = mapped_column(String(10), default="debit")  # debit | credit
    status: Mapped[str] = mapped_column(String(12), default="active")  # active | frozen | blocked
    daily_limit_paise: Mapped[int] = mapped_column(Integer, default=50_000_00)
    international_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    customer: Mapped[Customer] = relationship(back_populates="cards")


class Payee(Base):
    __tablename__ = "payees"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("pay"))
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    account_number: Mapped[str] = mapped_column(String(20))
    ifsc: Mapped[str] = mapped_column(String(11), default="")
    active_from: Mapped[datetime] = mapped_column(DateTime)  # cooling period end
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class VoiceEnrollment(Base):
    __tablename__ = "voice_enrollments"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("enr"))
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    detectifai_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    local_embedding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)  # float32 ECAPA centroid
    sample_paths: Mapped[list] = mapped_column(JSON, default=list)
    quality: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Call(Base):
    __tablename__ = "calls"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("call"))
    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customers.id"), nullable=True, index=True)
    direction: Mapped[str] = mapped_column(String(10), default="inbound")
    channel: Mapped[str] = mapped_column(String(20), default="web")
    caller_number: Mapped[str] = mapped_column(String(20), default="")
    lang: Mapped[str] = mapped_column(String(5), default="en")
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | ended | terminated
    risk_state: Mapped[str] = mapped_column(String(16), default="unknown")  # unknown|trusted|suspicious|fraud
    outcome: Mapped[str] = mapped_column(String(32), default="")
    trust: Mapped[float] = mapped_column(Float, default=0.0)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CallEvent(Base):
    __tablename__ = "call_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    call_id: Mapped[str] = mapped_column(ForeignKey("calls.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    t_call: Mapped[float] = mapped_column(Float, default=0.0)  # seconds since call start
    kind: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class VoiceCheck(Base):
    __tablename__ = "voice_checks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    call_id: Mapped[str] = mapped_column(ForeignKey("calls.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    purpose: Mapped[str] = mapped_column(String(16), default="stream")  # stream | challenge
    t_start: Mapped[float] = mapped_column(Float)
    t_end: Mapped[float] = mapped_column(Float)
    speaker_prob: Mapped[float | None] = mapped_column(Float, nullable=True)
    synthetic_prob: Mapped[float | None] = mapped_column(Float, nullable=True)
    speaker_source: Mapped[str] = mapped_column(String(20), default="")
    spoof_source: Mapped[str] = mapped_column(String(20), default="")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    flags: Mapped[list] = mapped_column(JSON, default=list)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    clip_path: Mapped[str] = mapped_column(String(300), default="")


class ActionRequest(Base):
    __tablename__ = "action_requests"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("act"))
    call_id: Mapped[str] = mapped_column(ForeignKey("calls.id"), index=True)
    customer_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    intent: Mapped[str] = mapped_column(String(40))
    tier: Mapped[int] = mapped_column(Integer)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # pending | awaiting_challenge | awaiting_stepup | executed | refused | cancelled | failed
    decision: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Challenge(Base):
    __tablename__ = "challenges"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("chl"))
    call_id: Mapped[str] = mapped_column(ForeignKey("calls.id"), index=True)
    action_id: Mapped[str] = mapped_column(ForeignKey("action_requests.id"))
    digits: Mapped[str] = mapped_column(String(12))
    issued_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    prompt_done_t: Mapped[float | None] = mapped_column(Float, nullable=True)  # call-time when prompt finished playing
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(12), default="open")  # open | passed | failed | expired
    transcript: Mapped[str] = mapped_column(Text, default="")
    latency_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class StepUp(Base):
    __tablename__ = "stepups"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("stp"))
    call_id: Mapped[str] = mapped_column(ForeignKey("calls.id"), index=True)
    action_id: Mapped[str] = mapped_column(ForeignKey("action_requests.id"))
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"))
    channel: Mapped[str] = mapped_column(String(20), default="app")  # app (registered device) - never the new number
    code_hash: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(12), default="pending")  # pending|approved|denied|expired|locked
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Ticket(Base):
    __tablename__ = "tickets"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("tkt"))
    call_id: Mapped[str] = mapped_column(ForeignKey("calls.id"), index=True)
    customer_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    action_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    severity: Mapped[str] = mapped_column(String(10), default="high")  # low|medium|high|critical
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open|confirmed_fraud|false_positive|closed
    clip_paths: Mapped[list] = mapped_column(JSON, default=list)
    resolution_note: Mapped[str] = mapped_column(Text, default="")
    resolved_by: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class BankCallNotice(Base):
    """Two-way trust: the bank proves it is the bank (outbound-call code shown in the customer's app)."""

    __tablename__ = "bank_call_notices"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("bcn"))
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    call_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    code: Mapped[str] = mapped_column(String(8))
    reason: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(12), default="active")  # active|confirmed|reported|expired|ended
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class AuditEntry(Base):
    """Append-only, hash-chained, HMAC-signed log. Any edit/delete breaks verification."""

    __tablename__ = "audit_log"
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    call_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))
    sig: Mapped[str] = mapped_column(String(64))
