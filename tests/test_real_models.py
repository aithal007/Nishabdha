"""Realistic run with the actual local backup models (SpeechBrain ECAPA + wav2vec2 anti-spoof ensemble).
Run:  TEST_VOICE=local pytest tests/test_real_models.py -s      (first run downloads ~1.5 GB of models)"""
from __future__ import annotations

import os

import pytest

from .conftest import STAFF, wav
from .helpers import card, challenge_words, enroll, first, names, start_call, turn

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(os.environ.get("TEST_VOICE") != "local", reason="set TEST_VOICE=local")]


async def test_real_genuine_customer_passes(client, stt):
    await enroll(client, "cus_ananya")  # speaker 1089, clips 0-2
    cid, h = await start_call(client, "cus_ananya")
    stt.say("please block my debit card")
    ev = await turn(client, cid, h, "real_1089_3.wav")
    probs = [e["data"]["chunk"]["speaker_prob"] for e in ev if e["event"] == "trust_update"]
    print("genuine stream speaker probs", probs)
    assert first(ev, "challenge_issued"), names(ev)
    stt.say(challenge_words(cid))
    ev = await turn(client, cid, h, "real_1089_4.wav")
    d = first(ev, "decision")
    print("genuine decision", d)
    assert d["outcome"] == "allow"
    assert (await card(client, "cus_ananya", "4521"))["status"] == "blocked"


async def test_real_impostor_refused(client, stt):
    await enroll(client, "cus_ananya")
    cid, h = await start_call(client, "cus_ananya")
    stt.say("change my card ending 4521 limit to 200000")
    ev = await turn(client, cid, h, "real_121_0.wav")  # a different real person
    if first(ev, "challenge_issued"):
        stt.say(challenge_words(cid))
        ev = await turn(client, cid, h, "real_121_1.wav")
    d = first(ev, "decision")
    print("impostor decision", d)
    assert d["outcome"] in ("refuse", "stepup")
    assert "action_executed" not in names(ev)


async def test_real_tts_voice_caught(client, stt):
    await enroll(client, "cus_ananya")
    cid, h = await start_call(client, "cus_ananya")
    caught = False
    for f in ("tts_0.wav", "tts_1.wav", "tts_2.wav"):
        stt.say("send 1000 rupees to Amma")
        ev = await turn(client, cid, h, f)
        synth = [e["data"]["chunk"]["synthetic_prob"] for e in ev if e["event"] == "trust_update"]
        print(f, "synthetic probs", synth)
        assert "action_executed" not in names(ev)
        if first(ev, "segment_flagged") or first(ev, "action_refused"):
            caught = True
            break
    assert caught
    t = (await client.get("/api/tickets", headers=STAFF)).json()["tickets"]
    assert any(x["call_id"] == cid for x in t)


async def test_real_enrollment_scores(client):
    r = await client.post("/api/admin/voice-check", headers=STAFF, files={"file": ("x.wav", wav("real_1089_5.wav"), "audio/wav")}, data={"customer_id": "cus_ananya"})
    assert r.status_code == 200
