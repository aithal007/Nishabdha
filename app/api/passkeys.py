"""Staff-provisioned passkeys and exact-action customer approval."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import passkeys
from app.core.security_models import FrozenTransfer, PasskeyApproval
from app.core.transactions import digest
from app.db import get_db
from app.models import ActionRequest, Customer, StepUp, utcnow
from app.security import require_app_customer, require_staff

router = APIRouter(prefix="/api", tags=["passkeys"])


class VerifyBody(BaseModel):
    approval_id: str = Field(max_length=64)
    credential: dict


class OptionsBody(BaseModel):
    purpose: str = Field(pattern="^(transfer|delegation)$")
    stepup_id: str | None = None
    binding_hash: str = Field(default="", max_length=64)


@router.post(
    "/admin/customers/{customer_id}/passkeys/options",
    dependencies=[Depends(require_staff)],
)
async def register_options(customer_id: str, db: AsyncSession = Depends(get_db)):
    c = await db.get(Customer, customer_id)
    if not c:
        raise HTTPException(404, "Customer not found.")
    return await passkeys.registration_options(db, c)


@router.post("/app/passkeys/options")
async def options(
    body: OptionsBody,
    c: Customer = Depends(require_app_customer),
    db: AsyncSession = Depends(get_db),
):
    if body.purpose == "transfer":
        st = await db.get(StepUp, body.stepup_id)
        frozen = await db.get(FrozenTransfer, st.action_id) if st else None
        if (
            not st
            or st.customer_id != c.id
            or st.status != "pending"
            or st.expires_at <= utcnow()
            or not frozen
        ):
            raise HTTPException(409, "No current transfer approval.")
        if (
            frozen.expires_at <= utcnow()
            or digest(frozen.snapshot) != frozen.action_hash
        ):
            raise HTTPException(409, "Transaction changed or expired.")
        return await passkeys.authentication_options(
            db, c.id, "transfer", frozen.action_hash, st.action_id
        )
    if len(body.binding_hash) != 64 or any(
        ch not in "0123456789abcdef" for ch in body.binding_hash
    ):
        raise HTTPException(400, "A SHA-256 delegation binding is required.")
    return await passkeys.authentication_options(
        db, c.id, "delegation", body.binding_hash
    )


async def _verify(
    body: VerifyBody,
    c: Customer,
    db: AsyncSession,
):
    approval = await passkeys.verify(db, c.id, body.approval_id, body.credential)
    action_id = approval.action_id
    if approval.purpose == "transfer":
        frozen = await db.get(FrozenTransfer, action_id)
        if (
            not frozen
            or frozen.expires_at <= utcnow()
            or digest(frozen.snapshot) != approval.binding_hash
        ):
            await db.rollback()
            raise HTTPException(409, "Transaction changed or expired.")
        steps = await db.execute(
            update(StepUp)
            .where(
                StepUp.action_id == action_id,
                StepUp.customer_id == c.id,
                StepUp.status == "pending",
                StepUp.expires_at > utcnow(),
            )
            .values(status="approved")
        )
        if steps.rowcount != 1:
            await db.rollback()
            raise HTTPException(409, "Approval already resolved.")
    await db.commit()
    if approval.purpose == "transfer":
        from app.core.session import get_session

        sess = get_session(frozen.call_id)
        if not sess:
            raise HTTPException(409, "Call ended; no transfer executed.")
        step = (
            (await db.execute(select(StepUp).where(StepUp.action_id == action_id)))
            .scalars()
            .first()
        )
        async with sess._turn_lock:
            await sess.stepup_resolved("approved", via="passkey", stepup_id=step.id)
        # Verification and execution are separate outcomes. The live session may
        # have ended, changed requests, or rejected execution after approval.
        # Reload state written by the gateway's independent transaction.
        db.expire_all()
        action = await db.get(ActionRequest, action_id)
        if not action or action.status != "executed":
            raise HTTPException(
                409,
                {
                    "message": "Passkey verified, but no transfer executed.",
                    "action_id": action_id,
                    "status": action.status if action else "unavailable",
                    "result": action.result if action else None,
                },
            )
        return {
            "approval_id": body.approval_id,
            "verified": True,
            "status": "executed",
            "purpose": "transfer",
            "action_id": action_id,
            "result": action.result,
        }
    return {
        "approval_id": approval.id,
        "verified": True,
        "status": "approved",
        "purpose": approval.purpose,
    }


@router.post("/app/passkeys/verify")
async def verify(
    body: VerifyBody,
    c: Customer = Depends(require_app_customer),
    db: AsyncSession = Depends(get_db),
):
    customer_id = c.id
    try:
        return await _verify(body, c, db)
    except HTTPException as exc:
        from app.core.decisions import record_decision

        await db.rollback()
        approval = await db.get(PasskeyApproval, body.approval_id)
        if approval and approval.customer_id == customer_id:
            frozen = (
                await db.get(FrozenTransfer, approval.action_id)
                if approval.action_id
                else None
            )
            record = await record_decision(
                db,
                customer_id=customer_id,
                request_id=approval.action_id or approval.id,
                call_id=frozen.call_id if frozen else None,
                operation="transfer_funds"
                if approval.purpose == "transfer"
                else "passkey_" + approval.purpose,
                actor_type="customer_app",
                outcome="denied",
                reason=str(exc.detail),
                action_hash=approval.binding_hash,
            )
            await db.commit()
            exc.headers = {**(exc.headers or {}), "X-Decision-ID": record.id}
        raise
