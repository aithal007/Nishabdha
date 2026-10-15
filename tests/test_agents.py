import asyncio
import json
import secrets
import time
from datetime import timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import select

from app.core.agent_identity import _load_key, digest, origin, public_jwk, sign_record
from app.core.agent_models import AgentGrant, AgentSupportTicket
from app.db import session_scope
from app.models import BankCallNotice, Call, utcnow

from .passkey_device import provision

AUTH = {"X-App-Token": "app-ananya-demo"}


async def grant_for(client):
    device = await provision(client)
    key = ec.generate_private_key(ec.SECP256R1())
    jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key.public_key()))
    r = await client.post(
        "/api/app/agents/delegation-binding", headers=AUTH, json={"holder_jwk": jwk}
    )
    assert r.status_code == 200, r.text
    binding = r.json()["binding_hash"]
    r = await client.post(
        "/api/app/passkeys/options",
        headers=AUTH,
        json={"purpose": "delegation", "binding_hash": binding},
    )
    assert r.status_code == 200, r.text
    approval = r.json()
    r = await client.post(
        "/api/app/passkeys/verify",
        headers=AUTH,
        json={
            "approval_id": approval["approval_id"],
            "credential": device.authenticate(approval["options"]),
        },
    )
    assert r.status_code == 200, r.text
    data = {"holder_jwk": jwk, "approval_id": approval["approval_id"]}
    r = await client.post("/api/app/agents/grants", headers=AUTH, json=data)
    assert r.status_code == 200, r.text
    return key, r.json()["grant_id"], data


async def request_for(client, key, grant_id, action="support_ticket.create", **changes):
    r = await client.post(f"/api/agents/grants/{grant_id}/nonce")
    assert r.status_code == 200, r.text
    body = {"action": action, "subject": "Please explain my card statement"}
    now = int(time.time())
    claims = {
        "iat": now,
        "exp": now + 60,
        "aud": origin(),
        "jti": secrets.token_urlsafe(16),
        "grant_id": grant_id,
        "nonce": r.json()["nonce"],
        "body_hash": digest(body),
    }
    claims.update(changes)
    return {**body, "proof": jwt.encode(claims, key, algorithm="ES256")}


@pytest.mark.asyncio
async def test_real_passkey_holder_and_atomic_one_use(client):
    key, grant, data = await grant_for(client)
    assert (
        await client.post("/api/app/agents/grants", headers=AUTH, json=data)
    ).status_code == 403
    body = await request_for(client, key, grant)
    results = await asyncio.gather(
        *(
            client.post(f"/api/agents/grants/{grant}/execute", json=body)
            for _ in range(2)
        )
    )
    assert sorted(r.status_code for r in results) == [200, 403]
    result = next(r.json() for r in results if r.status_code == 200)
    receipt = jwt.decode(
        result["receipt"],
        jwt.algorithms.ECAlgorithm.from_jwk(public_jwk()),
        algorithms=["ES256"],
    )
    assert receipt["ticket_id"] == result["ticket_id"]
    async with session_scope() as db:
        assert len(list((await db.execute(select(AgentSupportTicket))).scalars())) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "attack",
    [
        "wrong_key",
        "wrong_audience",
        "expired",
        "tampered_body",
        "scope",
        "revoked",
        "expired_grant",
    ],
)
async def test_reject_invalid_authority(client, attack):
    key, grant, _ = await grant_for(client)
    changes = {}
    if attack == "wrong_key":
        key = ec.generate_private_key(ec.SECP256R1())
    if attack == "wrong_audience":
        changes["aud"] = "https://evil.invalid"
    if attack == "expired":
        changes.update(iat=int(time.time()) - 120, exp=int(time.time()) - 60)
    body = await request_for(
        client,
        key,
        grant,
        action="transfer" if attack == "scope" else "support_ticket.create",
        **changes,
    )
    if attack == "tampered_body":
        body["subject"] = "Changed after signing"
    if attack == "revoked":
        r = await client.post(f"/api/app/agents/grants/{grant}/revoke", headers=AUTH)
        assert r.status_code == 200
    if attack == "expired_grant":
        async with session_scope() as db:
            g = await db.get(AgentGrant, grant)
            g.expires_at = utcnow() - timedelta(seconds=1)
    r = await client.post(f"/api/agents/grants/{grant}/execute", json=body)
    assert r.status_code == 403, r.text
    async with session_scope() as db:
        assert not list((await db.execute(select(AgentSupportTicket))).scalars())


@pytest.mark.asyncio
async def test_customer_token_alone_is_not_delegation(client):
    key = ec.generate_private_key(ec.SECP256R1())
    jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key.public_key()))
    assert (
        await client.post(
            "/api/app/agents/grants", headers=AUTH, json={"holder_jwk": jwk}
        )
    ).status_code == 403


@pytest.mark.asyncio
async def test_bank_proof_is_bound_to_live_owned_outbound_call(client):
    async with session_scope() as db:
        call = Call(customer_id="cus_ananya", direction="outbound")
        db.add(call)
        await db.flush()
        notice = BankCallNotice(
            customer_id="cus_ananya",
            call_id=call.id,
            code="123456",
            reason="Requested support callback",
            expires_at=utcnow() + timedelta(minutes=5),
        )
        db.add(notice)
        await db.flush()
        notice_id, call_id = notice.id, call.id
    path = f"/api/app/bank-call/{notice_id}/proof"
    assert (await client.get(path)).status_code == 401
    assert (
        await client.get(path, headers={"X-App-Token": "app-rahul-demo"})
    ).status_code == 404
    r = await client.get(path, headers=AUTH)
    assert r.status_code == 200, r.text
    proof = jwt.decode(
        r.json()["proof"],
        jwt.algorithms.ECAlgorithm.from_jwk(public_jwk()),
        algorithms=["ES256"],
        issuer=origin(),
        audience="cus_ananya",
    )
    assert proof["call_id"] == call_id
    async with session_scope() as db:
        call = await db.get(Call, call_id)
        call.status = "ended"
    assert (await client.get(path, headers=AUTH)).status_code == 404


def test_key_persists_across_reload():
    first = public_jwk()
    _load_key.cache_clear()
    assert public_jwk() == first
    signed = sign_record({"test": True})
    assert jwt.decode(
        signed, jwt.algorithms.ECAlgorithm.from_jwk(first), algorithms=["ES256"]
    )["test"]
