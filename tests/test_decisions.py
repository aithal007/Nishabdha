"""Signed outcome records must match actual authorization and remain customer scoped."""

import asyncio
import json

import jwt
import pytest
from sqlalchemy import select

from app.core.agent_identity import public_jwk
from app.core.banking import ActionError
from app.core.decisions import DecisionRecord
from app.core.security_models import FrozenTransfer
from app.core.transactions import execute_transfer, freeze_transfer
from app.db import session_scope
from app.models import Account

from .helpers import start_call, text
from .passkey_device import provision
from .test_agents import grant_for, request_for
from .test_transfer_security import approve_frozen, proposal

pytestmark = pytest.mark.asyncio
APP = {"X-App-Token": "app-ananya-demo"}


def verified(record):
    payload = jwt.decode(
        record["signature"],
        jwt.algorithms.ECAlgorithm.from_jwk(public_jwk()),
        algorithms=["ES256"],
    )
    assert payload == record["payload"]
    assert payload["schema"] == "nishabdha.decision.v1"
    assert payload["mode"] == "simulated"
    serialized = json.dumps(payload)
    for secret in (
        "app-ananya-demo",
        "50100012344521",
        "30214455667788",
        "speaker_prob",
        "synthetic_prob",
    ):
        assert secret not in serialized
    return payload


async def test_held_typed_request_has_owned_masked_receipt(client):
    cid, headers = await start_call(client, "cus_ananya")
    events = await text(client, cid, headers, "transfer 100 rupees to Amma")
    states = [e["data"] for e in events if e["event"] == "authority_state"]
    assert states and states[-1]["outcome"] == "hold"
    assert "speaker_prob" not in json.dumps(states)
    record = (await client.get("/api/app/decisions", headers=APP)).json()["decisions"][
        0
    ]
    payload = verified(record)
    assert payload["reason_codes"] == ["verification_required"]
    assert states[-1]["decision_id"] == payload["decision_id"]
    path = f"/api/app/decisions/{payload['decision_id']}"
    assert (await client.get(path)).status_code == 401
    assert (
        await client.get(path, headers={"X-App-Token": "app-rahul-demo"})
    ).status_code == 404
    assert (await client.get("/api/decisions")).status_code == 401
    assert (
        await client.get("/api/decisions", headers={"X-Staff-Key": "staff-test"})
    ).status_code == 200


async def test_detector_false_negative_cannot_replace_approval(client):
    """Explicit simulated false negative: high voice scores, no customer approval."""
    cid, aid, evidence = await proposal()
    await freeze_transfer(
        aid, "cus_ananya", cid, {"payee_name": "Amma", "amount_rupees": 100}, evidence
    )
    with pytest.raises(ActionError, match="passkey"):
        await execute_transfer(aid, "cus_ananya", cid)
    async with session_scope() as db:
        assert (await db.get(Account, "acc_ananya")).balance_paise == 12450000
    payload = verified(
        (await client.get("/api/app/decisions", headers=APP)).json()["decisions"][0]
    )
    assert payload["outcome"] == "denied"
    assert payload["reason_codes"] == ["approval_required"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("amount_paise", 50000),
        ("destination", "99999999999999"),
        ("payee_id", "different-payee"),
    ],
)
async def test_approved_amount_or_recipient_tamper_has_signed_refusal(
    client, field, value
):
    device = await provision(client)
    cid, aid, evidence = await proposal()
    await freeze_transfer(
        aid, "cus_ananya", cid, {"payee_name": "Amma", "amount_rupees": 100}, evidence
    )
    await approve_frozen(client, device, aid)
    async with session_scope() as db:
        frozen = await db.get(FrozenTransfer, aid)
        frozen.snapshot = {**frozen.snapshot, field: value}
    with pytest.raises(ActionError, match="changed"):
        await execute_transfer(aid, "cus_ananya", cid)
    async with session_scope() as db:
        assert (await db.get(Account, "acc_ananya")).balance_paise == 12450000
    record = (await client.get("/api/app/decisions", headers=APP)).json()["decisions"][
        0
    ]
    assert verified(record)["reason_codes"] == ["transaction_changed"]


async def test_retry_returns_same_durable_success_decision(client):
    device = await provision(client)
    cid, aid, evidence = await proposal()
    await freeze_transfer(
        aid, "cus_ananya", cid, {"payee_name": "Amma", "amount_rupees": 100}, evidence
    )
    await approve_frozen(client, device, aid)
    first, second = await asyncio.gather(
        *(execute_transfer(aid, "cus_ananya", cid) for _ in range(2))
    )
    assert first == second
    assert verified(first["data"]["decision_receipt"])["outcome"] == "executed"
    async with session_scope() as db:
        records = list(
            (
                await db.execute(
                    select(DecisionRecord).where(
                        DecisionRecord.request_id == aid,
                        DecisionRecord.payload["outcome"].as_string() == "executed",
                    )
                )
            ).scalars()
        )
        assert len(records) == 1
        assert (await db.get(Account, "acc_ananya")).balance_paise == 12440000


async def test_delegate_denial_ticket_and_replay_have_distinct_receipts(client):
    key, grant, _ = await grant_for(client)
    for operation in ("transfer_funds", "balance"):
        body = await request_for(client, key, grant, action=operation)
        denied = await client.post(f"/api/agents/grants/{grant}/execute", json=body)
        assert denied.status_code == 403
        record = (
            await client.get(
                f"/api/app/decisions/{denied.headers['X-Decision-ID']}", headers=APP
            )
        ).json()
        assert verified(record)["reason_codes"] == ["scope_denied"]
    body = await request_for(client, key, grant)
    accepted = await client.post(f"/api/agents/grants/{grant}/execute", json=body)
    assert accepted.status_code == 200
    assert verified(accepted.json()["decision_receipt"])["outcome"] == "executed"
    replay = await client.post(f"/api/agents/grants/{grant}/execute", json=body)
    assert (
        replay.status_code == 403
        and replay.headers["X-Decision-ID"] != accepted.json()["decision_id"]
    )
    records = (await client.get("/api/app/decisions", headers=APP)).json()["decisions"]
    assert len(records) == 4
    unavailable = await client.post(f"/api/agents/grants/{grant}/nonce")
    assert unavailable.status_code == 403
    record = (
        await client.get(
            f"/api/app/decisions/{unavailable.headers['X-Decision-ID']}", headers=APP
        )
    ).json()
    assert verified(record)["reason_codes"] == ["grant_unavailable"]
    async with session_scope() as db:
        assert (await db.get(Account, "acc_ananya")).balance_paise == 12450000


async def test_receipt_persistence_failure_rolls_back_debit(client, monkeypatch):
    from app.core import decisions

    device = await provision(client)
    cid, aid, evidence = await proposal()
    await freeze_transfer(
        aid, "cus_ananya", cid, {"payee_name": "Amma", "amount_rupees": 100}, evidence
    )
    await approve_frozen(client, device, aid)

    async def unavailable(*args, **kwargs):
        raise RuntimeError("receipt storage unavailable")

    monkeypatch.setattr(decisions, "record_decision", unavailable)
    with pytest.raises(RuntimeError, match="receipt storage"):
        await execute_transfer(aid, "cus_ananya", cid)
    async with session_scope() as db:
        assert (await db.get(Account, "acc_ananya")).balance_paise == 12450000


async def test_invalid_passkey_has_signed_refusal(client):
    from app.core import passkeys

    device = await provision(client)
    cid, aid, evidence = await proposal()
    await freeze_transfer(
        aid, "cus_ananya", cid, {"payee_name": "Amma", "amount_rupees": 100}, evidence
    )
    async with session_scope() as db:
        frozen = await db.get(FrozenTransfer, aid)
        options = await passkeys.authentication_options(
            db, "cus_ananya", "transfer", frozen.action_hash, aid
        )
    response = await client.post(
        "/api/app/passkeys/verify",
        headers=APP,
        json={
            "approval_id": options["approval_id"],
            "credential": device.authenticate(
                options["options"], origin="https://attacker.example"
            ),
        },
    )
    assert response.status_code == 400
    record = (
        await client.get(
            f"/api/app/decisions/{response.headers['X-Decision-ID']}", headers=APP
        )
    ).json()
    assert verified(record)["reason_codes"] == ["passkey_invalid"]
    async with session_scope() as db:
        assert (await db.get(Account, "acc_ananya")).balance_paise == 12450000


async def test_call_recording_saves_exact_pcm_without_float_roundtrip(
    client, monkeypatch
):
    import wave

    from app.core import session as sessions

    cid, headers = await start_call(client, "cus_ananya", greet=False)
    session = sessions.SESSIONS[cid]
    pcm = b"\xff\x7f\x00\x80\x01\x00\xff\xff" * 8000
    session._rec.extend(pcm)

    def no_float_copy(*args):
        raise AssertionError("Whole-call recording must not be converted to floats")

    monkeypatch.setattr(sessions, "pcm16_to_float", no_float_copy)
    response = await client.post(f"/api/calls/{cid}/end", headers=headers)
    assert response.status_code == 200
    assert not session._rec
    with wave.open(
        str(session.s.data_dir / "clips" / f"{cid}_full.wav"), "rb"
    ) as saved:
        assert saved.getframerate() == 16000 and saved.getsampwidth() == 2
        assert saved.readframes(saved.getnframes()) == pcm
