"""Persisted, bounded agent permissions and replay protection."""

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models import new_id, utcnow


class AgentGrant(Base):
    __tablename__ = "agent_grants"
    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id("grant")
    )
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    holder_jwk: Mapped[dict] = mapped_column(JSON)
    scope: Mapped[str] = mapped_column(String(40), default="support_ticket.create")
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    uses: Mapped[int] = mapped_column(Integer, default=0)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AgentNonce(Base):
    __tablename__ = "agent_nonces"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    grant_id: Mapped[str] = mapped_column(ForeignKey("agent_grants.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used: Mapped[bool] = mapped_column(Boolean, default=False)


class AgentSupportTicket(Base):
    __tablename__ = "agent_support_tickets"
    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id("support")
    )
    grant_id: Mapped[str] = mapped_column(ForeignKey("agent_grants.id"), unique=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"))
    subject: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
