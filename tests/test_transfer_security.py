import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.banking import ActionError
from app.core.security_models import FrozenTransfer, PasskeyApproval
from app.core.transactions import execute_transfer, freeze_transfer
from app.db import session_scope
from app.models import Account, ActionRequest, Call, Payee, StepUp, Transaction, utcnow

from .passkey_device import provision

pytestmark = pytest.mark.asyncio
APP = {"X-App-Token": "app-ananya-demo"}


async def proposal():
    async with session_scope() as db:
        call = Call(
            customer_id="cus_ananya", direction="inbound", lang="en", status="active"
        )
        db.add(call)
        await db.flush()
        action = ActionRequest(
            call_id=call.id,
            customer_id="cus_ananya",
            intent="transfer_funds",
            tier=2,
            params={"payee_name": "Amma", "amount_rupees": 100},
        )
        db.add(action)
        await db.flush()
        cid, aid = call.id, action.id
    evidence = {
        "call_id": cid,
        "action_id": aid,
        "audio_hash": "a" * 64,
        "checked_at": utcnow().isoformat(),
        "speaker_source": "mock",
        "spoof_source": "mock",
        "speaker_prob": 0.95,
        "synthetic_prob": 0.02,
    }
    return cid, aid, evidence


async def approve_frozen(client, device, aid):
    async with session_scope() as db:
        frozen = await db.get(FrozenTransfer, aid)
        from app.core import passkeys

        opts = await passkeys.authentication_options(
            db, "cus_ananya", "transfer", frozen.action_hash, aid
        )
    credential = device.authenticate(opts["options"])
    async with session_scope() as db:
        from app.core import passkeys

        await passkeys.verify(db, "cus_ananya", opts["approval_id"], credential)
        frozen = await db.get(FrozenTransfer, aid)
        db.add(
            StepUp(
                call_id=frozen.call_id,
                action_id=aid,
                customer_id="cus_ananya",
                channel="registered_app",
                code_hash="",
                status="approved",
                expires_at=utcnow() + timedelta(seconds=120),
            )
        )


async def test_transfer_passkey_real_signature_and_concurrent_retry(client):
    device = await provision(client)
    cid, aid, e = await proposal()
    await freeze_transfer(
        aid, "cus_ananya", cid, {"payee_name": "Amma", "amount_rupees": 100}, e
    )
    with pytest.raises(ActionError, match="passkey"):
        await execute_transfer(aid, "cus_ananya", cid)
    await approve_frozen(client, device, aid)
    results = await asyncio.gather(
        *(execute_transfer(aid, "cus_ananya", cid) for _ in range(2))
    )
    assert results[0] == results[1]
    async with session_scope() as db:
        account = await db.get(Account, "acc_ananya")
        assert account.balance_paise == 12450000 - 10000
        debits = list(
            (
                await db.execute(
                    select(Transaction).where(
                        Transaction.description == "Transfer to Amma"
                    )
                )
            ).scalars()
        )
        assert len(debits) == 1
        frozen = await db.get(FrozenTransfer, aid)
        assert frozen.receipt["signature"]


async def test_transfer_changed_parameters_cancel_approval(client):
    cid, aid, e = await proposal()
    await freeze_transfer(
        aid, "cus_ananya", cid, {"payee_name": "Amma", "amount_rupees": 100}, e
    )
    with pytest.raises(ActionError, match="changed"):
        await freeze_transfer(
            aid, "cus_ananya", cid, {"payee_name": "Amma", "amount_rupees": 200}, e
        )
    async with session_scope() as db:
        assert (await db.get(ActionRequest, aid)).status == "cancelled"


async def test_transfer_duplicate_names_require_selection(client):
    async with session_scope() as db:
        db.add(
            Payee(
                customer_id="cus_ananya",
                name="Amma",
                account_number="12345678900",
                active_from=utcnow() - timedelta(days=1),
            )
        )
    cid, aid, e = await proposal()
    with pytest.raises(ActionError, match="ambiguous"):
        await freeze_transfer(
            aid, "cus_ananya", cid, {"payee_name": "Amma", "amount_rupees": 100}, e
        )


async def test_transfer_tamper_and_stale_evidence_block(client):
    device = await provision(client)
    cid, aid, e = await proposal()
    e["checked_at"] = (utcnow() - timedelta(minutes=5)).isoformat()
    with pytest.raises(ActionError, match="verification"):
        await freeze_transfer(
            aid, "cus_ananya", cid, {"payee_name": "Amma", "amount_rupees": 100}, e
        )
    e["checked_at"] = utcnow().isoformat()
    await freeze_transfer(
        aid, "cus_ananya", cid, {"payee_name": "Amma", "amount_rupees": 100}, e
    )
    await approve_frozen(client, device, aid)
    async with session_scope() as db:
        f = await db.get(FrozenTransfer, aid)
        f.snapshot = {**f.snapshot, "amount_paise": 1}
    with pytest.raises(ActionError, match="changed"):
        await execute_transfer(aid, "cus_ananya", cid)
    async with session_scope() as db:
        assert (await db.get(Account, "acc_ananya")).balance_paise == 12450000


async def test_passkey_rejects_wrong_origin_user_verification_replay(client):
    device = await provision(client)
    for origin, uv in [
        ("https://attacker.example", True),
        ("http://localhost:8000", False),
    ]:
        p = (
            await client.post(
                "/api/app/passkeys/options",
                headers=APP,
                json={"purpose": "delegation", "binding_hash": "b" * 64},
            )
        ).json()
        result = await client.post(
            "/api/app/passkeys/verify",
            headers=APP,
            json={
                "approval_id": p["approval_id"],
                "credential": device.authenticate(p["options"], origin, uv),
            },
        )
        assert result.status_code == 400
    p = (
        await client.post(
            "/api/app/passkeys/options",
            headers=APP,
            json={"purpose": "delegation", "binding_hash": "b" * 64},
        )
    ).json()
    body = {
        "approval_id": p["approval_id"],
        "credential": device.authenticate(p["options"]),
    }
    assert (
        await client.post("/api/app/passkeys/verify", headers=APP, json=body)
    ).status_code == 200
    assert (
        await client.post("/api/app/passkeys/verify", headers=APP, json=body)
    ).status_code == 409


async def test_demo_token_cannot_provision_passkey(client):
    r = await client.post(
        "/api/admin/customers/cus_ananya/passkeys/options", headers=APP
    )
    assert r.status_code == 401


async def test_competing_transfers_cannot_overdraw(client):
    device = await provision(client)
    async with session_scope() as db:
        account = await db.get(Account, "acc_ananya")
        account.balance_paise = 5000000
    requests = []
    for _ in range(2):
        cid, aid, e = await proposal()
        await freeze_transfer(
            aid, "cus_ananya", cid, {"payee_name": "Amma", "amount_rupees": 40000}, e
        )
        await approve_frozen(client, device, aid)
        requests.append((aid, cid))
    results = await asyncio.gather(
        *(execute_transfer(aid, "cus_ananya", cid) for aid, cid in requests),
        return_exceptions=True,
    )
    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, ActionError) for result in results) == 1
    async with session_scope() as db:
        assert (await db.get(Account, "acc_ananya")).balance_paise == 1000000


async def test_expired_and_wrong_customer_passkey_challenges(client):
    device = await provision(client)
    p = (
        await client.post(
            "/api/app/passkeys/options",
            headers=APP,
            json={"purpose": "delegation", "binding_hash": "c" * 64},
        )
    ).json()
    body = {
        "approval_id": p["approval_id"],
        "credential": device.authenticate(p["options"]),
    }
    wrong = await client.post(
        "/api/app/passkeys/verify", headers={"X-App-Token": "app-rahul-demo"}, json=body
    )
    assert wrong.status_code == 404
    async with session_scope() as db:
        challenge = await db.get(PasskeyApproval, p["approval_id"])
        challenge.expires_at = utcnow() - timedelta(seconds=1)
    assert (
        await client.post("/api/app/passkeys/verify", headers=APP, json=body)
    ).status_code == 409


async def test_security_migration_preserves_history_invalidates_legacy_approvals(
    client,
):
    from app.core.security_models import SecurityMigration
    from app.db import init_db

    cid, aid, _ = await proposal()
    async with session_scope() as db:
        migration = await db.get(SecurityMigration, 2)
        if migration:
            await db.delete(migration)
        step = StepUp(
            call_id=cid,
            action_id=aid,
            customer_id="cus_ananya",
            channel="registered_app",
            code_hash="",
            expires_at=utcnow() + timedelta(seconds=120),
        )
        db.add(step)
        await db.flush()
        sid = step.id
        before = len(list((await db.execute(select(Transaction))).scalars()))
    await init_db()
    await init_db()
    async with session_scope() as db:
        assert (await db.get(ActionRequest, aid)).status == "cancelled"
        assert (await db.get(StepUp, sid)).status == "expired"
        assert (await db.get(Account, "acc_ananya")).balance_paise == 12450000
        assert len(list((await db.execute(select(Transaction))).scalars())) == before


async def test_approval_denial_race_resolves_once(client):
    cid, aid, _ = await proposal()
    async with session_scope() as db:
        action = await db.get(ActionRequest, aid)
        action.intent = "card_limit_change"
        st = StepUp(
            call_id=cid,
            action_id=aid,
            customer_id="cus_ananya",
            channel="registered_app",
            code_hash="",
            expires_at=utcnow() + timedelta(seconds=120),
        )
        db.add(st)
        await db.flush()
        sid = st.id
    results = await asyncio.gather(
        *(
            client.post(f"/api/app/stepups/{sid}/{verb}", headers=APP)
            for verb in ("approve", "deny")
        )
    )
    assert sorted(r.status_code for r in results) == [200, 409]
