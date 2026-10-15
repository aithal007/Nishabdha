"""Additive security schema: legacy customer/account history remains untouched."""

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models import new_id, utcnow


class SecurityMigration(Base):
    __tablename__ = "security_migrations"
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class FrozenTransfer(Base):
    __tablename__ = "frozen_transfers"
    action_id: Mapped[str] = mapped_column(
        ForeignKey("action_requests.id"), primary_key=True
    )
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    call_id: Mapped[str] = mapped_column(ForeignKey("calls.id"))
    snapshot: Mapped[dict] = mapped_column(JSON)
    action_hash: Mapped[str] = mapped_column(String(64))
    evidence: Mapped[dict] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    receipt: Mapped[dict] = mapped_column(JSON, default=dict)


class PasskeyCredential(Base):
    __tablename__ = "passkey_credentials"
    id: Mapped[str] = mapped_column(String(1024), primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    public_key: Mapped[bytes] = mapped_column(LargeBinary)
    sign_count: Mapped[int] = mapped_column(Integer, default=0)


class PasskeyApproval(Base):
    __tablename__ = "passkey_approvals"
    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: new_id("pka")
    )
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    purpose: Mapped[str] = mapped_column(String(20))
    binding_hash: Mapped[str] = mapped_column(String(64))
    challenge: Mapped[bytes] = mapped_column(LargeBinary)
    action_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)
