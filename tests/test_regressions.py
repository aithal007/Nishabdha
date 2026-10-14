"""Regression tests for issues found in the adversarial review."""
from __future__ import annotations

import pytest

from app.core import session as session_mod
from app.providers.voice_engine import get_voice_engine

from .conftest import STAFF
from .helpers import challenge_words, enroll, first, names, start_call, text, turn

pytestmark = pytest.mark.asyncio


def genuine():
    m = get_voice_engine().mock
    m.force_speaker, m.force_spoof = 0.92, 0.04


async def test_typed_tier1_does_not_loop(client, stt):
    await enroll(client, "cus_ananya")
    genuine()
    cid, h = await start_call(client, "cus_ananya")
    ev = await text(client, cid, h, "what is my balance")
    assert first(ev, "challenge_issued")
    ev = await text(client, cid, h, challenge_words(cid))
    assert first(ev, "decision")["outcome"] == "stepup"
    assert "challenge_issued" not in names(ev)


async def test_fraud_desk_lock_applies_to_live_call(client, stt):
    await enroll(client, "cus_ananya")
    genuine()
    cid, h = await start_call(client, "cus_ananya")
    stt.say("hello")
    await turn(client, cid, h, "real_1089_3.wav")
    sess = session_mod.SESSIONS[cid]
    await sess.create_ticket("high", ["manual"], None, [])
    t = (await client.get("/api/tickets", headers=STAFF)).json()["tickets"][0]
    await client.patch(f"/api/tickets/{t['id']}", headers=STAFF, json={"status": "confirmed_fraud", "lock_customer_voice": True})
    stt.say("freeze my debit card")
    ev = await turn(client, cid, h, "real_1089_4.wav")
    assert "action_executed" not in names(ev)


async def test_unknown_customer_no_session_leak(client):
    before = len(session_mod.SESSIONS)
    r = await client.post("/api/calls", json={"customer_id": "cus_nope"})
    assert r.status_code == 404
    assert len(session_mod.SESSIONS) == before


async def test_stepup_expired_after_refusal(client, stt):
    cid, h = await start_call(client, "cus_rahul")
    stt.say("change my card limit to 100000")
    ev = await turn(client, cid, h, "real_1188_0.wav")
    st = first(ev, "stepup_sent")
    sess = session_mod.SESSIONS[cid]
    from app.core.policy import Decision

    async with sess._turn_lock:
        await sess._refuse(Decision("refuse", 0.0, ["test"]))
    r = await client.post(f"/api/app/stepups/{st['stepup_id']}/approve", headers={"X-App-Token": "app-rahul-demo"})
    assert r.status_code == 409
    pend = (await client.get("/api/app/pending", headers={"X-App-Token": "app-rahul-demo"})).json()
    assert pend["stepups"] == []


async def test_per_call_transfer_cap(client, stt):
    cid, h = await start_call(client, "cus_ananya")  # not enrolled -> app approvals
    for i, amt in enumerate((40000, 20000)):
        stt.say(f"send {amt} rupees to Amma")
        ev = await turn(client, cid, h, f"real_1089_{i + 3}.wav")
        st = first(ev, "stepup_sent")
        await client.post(f"/api/app/stepups/{st['stepup_id']}/approve", headers={"X-App-Token": "app-ananya-demo"})
    me = (await client.get("/api/app/me", headers={"X-App-Token": "app-ananya-demo"})).json()
    assert me["accounts"][0]["balance_paise"] == 1_24_500_00 - 40000_00  # second transfer blocked by the cap


async def test_end_during_pending_is_clean(client, stt):
    await enroll(client, "cus_ananya")
    genuine()
    cid, h = await start_call(client, "cus_ananya")
    stt.say("unfreeze my debit card")
    await turn(client, cid, h, "real_1089_3.wav")
    r = await client.post(f"/api/calls/{cid}/end", headers=h)
    assert r.status_code == 200 and cid not in session_mod.SESSIONS
    rep = (await client.get(f"/api/calls/{cid}/report", headers=STAFF)).json()
    assert rep["actions"][0]["status"] == "cancelled"
