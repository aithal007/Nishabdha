"""WebAuthn ceremonies with server-side transaction binding and one-use challenges."""

import json
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select, update
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    UserVerificationRequirement,
)

from app.config import get_settings
from app.core.security_models import PasskeyApproval, PasskeyCredential
from app.models import Customer, utcnow


async def registration_options(db, customer: Customer) -> dict:
    s = get_settings()
    credentials = (
        await db.execute(
            select(PasskeyCredential).where(
                PasskeyCredential.customer_id == customer.id
            )
        )
    ).scalars()
    options = generate_registration_options(
        rp_id=s.webauthn_rp_id,
        rp_name="Nishabdha Bank",
        user_id=customer.id.encode(),
        user_name=customer.name,
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(c.id))
            for c in credentials
        ],
        authenticator_selection=AuthenticatorSelectionCriteria(
            user_verification=UserVerificationRequirement.REQUIRED
        ),
    )
    approval = PasskeyApproval(
        customer_id=customer.id,
        purpose="registration",
        binding_hash="",
        challenge=options.challenge,
        expires_at=utcnow() + timedelta(seconds=120),
    )
    db.add(approval)
    await db.commit()
    return {"approval_id": approval.id, "options": json.loads(options_to_json(options))}


async def authentication_options(
    db, customer_id: str, purpose: str, binding_hash: str, action_id=None
) -> dict:
    credentials = list(
        (
            await db.execute(
                select(PasskeyCredential).where(
                    PasskeyCredential.customer_id == customer_id
                )
            )
        ).scalars()
    )
    if not credentials:
        raise HTTPException(
            409, "Ask staff to provision your passkey before approving transactions."
        )
    options = generate_authentication_options(
        rp_id=get_settings().webauthn_rp_id,
        allow_credentials=[
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(c.id))
            for c in credentials
        ],
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    approval = PasskeyApproval(
        customer_id=customer_id,
        purpose=purpose,
        binding_hash=binding_hash,
        action_id=action_id,
        challenge=options.challenge,
        expires_at=utcnow() + timedelta(seconds=120),
    )
    db.add(approval)
    await db.commit()
    return {"approval_id": approval.id, "options": json.loads(options_to_json(options))}


async def verify(
    db, customer_id: str, approval_id: str, credential: dict
) -> PasskeyApproval:
    s = get_settings()
    approval = await db.get(PasskeyApproval, approval_id)
    if not approval or approval.customer_id != customer_id:
        raise HTTPException(404, "Unknown passkey challenge.")
    if approval.verified or approval.consumed or approval.expires_at <= utcnow():
        raise HTTPException(409, "Passkey challenge expired or already used.")
    try:
        if approval.purpose == "registration":
            result = verify_registration_response(
                credential=credential,
                expected_challenge=approval.challenge,
                expected_rp_id=s.webauthn_rp_id,
                expected_origin=s.bank_origin,
                require_user_verification=True,
            )
            key_id = bytes_to_base64url(result.credential_id)
            if await db.get(PasskeyCredential, key_id):
                raise ValueError("Credential already registered")
            db.add(
                PasskeyCredential(
                    id=key_id,
                    customer_id=customer_id,
                    public_key=result.credential_public_key,
                    sign_count=result.sign_count,
                )
            )
        else:
            key = await db.get(PasskeyCredential, credential.get("id", ""))
            if not key or key.customer_id != customer_id:
                raise ValueError("Unknown credential")
            # Reserve the credential counter and challenge in the same transaction.
            result = verify_authentication_response(
                credential=credential,
                expected_challenge=approval.challenge,
                expected_rp_id=s.webauthn_rp_id,
                expected_origin=s.bank_origin,
                credential_public_key=key.public_key,
                credential_current_sign_count=key.sign_count,
                require_user_verification=True,
            )
            counter = await db.execute(
                update(PasskeyCredential)
                .where(
                    PasskeyCredential.id == key.id,
                    PasskeyCredential.sign_count == key.sign_count,
                )
                .values(sign_count=result.new_sign_count)
            )
            if counter.rowcount != 1:
                raise ValueError("Concurrent credential use; retry")
    except Exception as exc:
        await db.rollback()
        raise HTTPException(400, "Passkey verification failed.") from exc
    claimed = await db.execute(
        update(PasskeyApproval)
        .where(
            PasskeyApproval.id == approval_id,
            PasskeyApproval.verified.is_(False),
            PasskeyApproval.consumed.is_(False),
            PasskeyApproval.expires_at > utcnow(),
        )
        .values(verified=True)
    )
    if claimed.rowcount != 1:
        await db.rollback()
        raise HTTPException(409, "Challenge already used.")
    await db.flush()
    return approval


async def consume_delegation_approval(
    db, customer_id: str, approval_id: str, binding_hash: str
) -> bool:
    result = await db.execute(
        update(PasskeyApproval)
        .where(
            PasskeyApproval.id == approval_id,
            PasskeyApproval.customer_id == customer_id,
            PasskeyApproval.purpose == "delegation",
            PasskeyApproval.binding_hash == binding_hash,
            PasskeyApproval.verified.is_(True),
            PasskeyApproval.consumed.is_(False),
            PasskeyApproval.expires_at > utcnow(),
        )
        .values(consumed=True)
    )
    return result.rowcount == 1
