"""Live streaming path: PCM16 over WebSocket, server VAD, playback timing for liveness, customer-app socket."""

from __future__ import annotations

import json
import time

import pytest

from fastapi.testclient import TestClient

from app.audio import float_to_pcm16
from app.core import session as session_mod
from app.i18n import speak_digits
from app.main import app
from app.providers.voice_engine import get_voice_engine

from .conftest import STAFF, ScriptedSTT, audio, wav


@pytest.fixture(autouse=True)
def reset_websocket_voice_fixture():
    # TestClient tests do not use the async `client` fixture; don't inherit the
    # preceding test's simulated clone scores when enrolling a genuine caller.
    engine = get_voice_engine()
    engine.mock.force_speaker = engine.mock.force_spoof = None
    engine.mock.speaker_queue.clear()
    engine.mock.spoof_queue.clear()
    engine._ref_cache.clear()
    for breaker in engine.breakers.values():
        breaker.ok()


def _recv_until(ws, pred, limit=60):
    seen = []
    for _ in range(limit):
        m = json.loads(ws.receive_text())
        seen.append(m)
        if pred(m):
            return m, seen
    raise AssertionError(f"event not received; got {[x['event'] for x in seen]}")


def _stream(ws, x, packet_s=0.1):
    step = int(16000 * packet_s)
    for i in range(0, x.size, step):
        ws.send_bytes(float_to_pcm16(x[i : i + step]))


def test_ws_full_call(monkeypatch):
    stt = ScriptedSTT()
    monkeypatch.setattr(session_mod, "get_stt", lambda: stt)
    with TestClient(app) as c:
        assert c.post("/api/demo/reset", headers=STAFF).status_code == 200
        files = [
            ("files", (f, wav(f), "audio/wav"))
            for f in ["real_1089_0.wav", "real_1089_1.wav", "real_1089_2.wav"]
        ]
        assert (
            c.post(
                "/api/customers/cus_ananya/enroll", headers=STAFF, files=files
            ).status_code
            == 200
        )
        m = get_voice_engine().mock
        m.force_speaker, m.force_spoof = 0.93, 0.03

        # bad token is rejected
        j = c.post("/api/calls", json={"customer_id": "cus_ananya"}).json()
        try:
            with c.websocket_connect(f"/ws/call/{j['call_id']}?token=wrong") as bad:
                bad.receive_text()
            raise AssertionError("bad token accepted")
        except Exception as e:  # starlette raises WebSocketDisconnect
            assert "4401" in repr(e) or "Disconnect" in type(e).__name__

        # customer app socket receives events for its own customer only
        with (
            c.websocket_connect(
                "/ws/customer/cus_ananya?token=app-ananya-demo"
            ) as app_ws,
            c.websocket_connect(j["ws_url"]) as ws,
        ):
            assert json.loads(app_ws.receive_text())["event"] == "hello"
            sess = session_mod.SESSIONS[j["call_id"]]
            sess.seg.end_frames = (
                100  # 3 s - LibriSpeech clips have long pauses; we end turns explicitly
            )
            ready = json.loads(ws.receive_text())
            assert ready["event"] == "ready"
            greet, _ = _recv_until(ws, lambda m: m["event"] == "agent_say")
            ws.send_text(
                json.dumps(
                    {"type": "playback", "id": greet["data"]["id"], "state": "ended"}
                )
            )

            stt.say("please block my debit card")
            _stream(ws, audio("real_1089_3.wav"))
            ws.send_text(json.dumps({"type": "end_utterance"}))
            chal, _ = _recv_until(
                ws,
                lambda m: (
                    m["event"] == "agent_say" and m["data"]["kind"] == "challenge"
                ),
            )
            digits = sess.pending.challenge_digits
            assert speak_digits(digits, "en") in chal["data"]["text"]
            ws.send_text(
                json.dumps(
                    {"type": "playback", "id": chal["data"]["id"], "state": "ended"}
                )
            )
            time.sleep(0.8)  # human reaction time
            stt.say(speak_digits(digits, "en").replace(",", ""))
            _stream(ws, audio("real_1089_4.wav"))
            ws.send_text(json.dumps({"type": "end_utterance"}))
            done, seen = _recv_until(
                ws,
                lambda m: (
                    m["event"] == "agent_say"
                    and m["data"]["kind"] in ("result", "refusal", "stepup")
                ),
            )
            assert done["data"]["kind"] == "result", [
                x["data"].get("text") for x in seen if x["event"] == "agent_say"
            ]
            # internal detection events never reach the caller socket
            assert not any(
                x["event"]
                in ("segment_flagged", "decision", "challenge_result", "ticket_created")
                for x in seen
            )
            act, _ = _recv_until(app_ws, lambda m: m["event"] == "account_activity")
            assert act["data"]["intent"] == "card_block"
            ws.send_text(json.dumps({"type": "hangup"}))

        for _ in range(
            100
        ):  # call teardown (saving recording) runs after the socket closes
            rep = c.get(f"/api/calls/{j['call_id']}/report", headers=STAFF).json()
            if rep["call"]["status"] == "ended":
                break
            time.sleep(0.1)
        ch = rep["liveness_challenges"][0]
        assert ch["status"] == "passed"
        # Server playback estimates may overlap a prompt; telemetry does not establish liveness.
        assert ch["latency_s"] is not None, ch
        assert rep["call"]["status"] == "ended"
        assert rep["waveform"]["duration_s"] and rep["waveform"]["duration_s"] > 8
        assert (
            c.get(f"/api/calls/{j['call_id']}/recording", headers=STAFF).status_code
            == 200
        )


def test_ws_dashboard_requires_key():
    with TestClient(app) as c:
        try:
            with c.websocket_connect("/ws/dashboard?staff_key=nope") as ws:
                ws.receive_text()
            raise AssertionError("dashboard open without key")
        except Exception as e:
            assert "Disconnect" in type(e).__name__
        with c.websocket_connect("/ws/dashboard?staff_key=staff-test") as ws:
            assert json.loads(ws.receive_text())["event"] == "hello"
            j = c.post("/api/calls", json={"customer_id": "cus_rahul"}).json()
            ev, _ = _recv_until(ws, lambda m: m["event"] == "call_started")
            assert ev["data"]["call_id"] == j["call_id"]


def test_ws_48k_browser_audio(monkeypatch):
    """Browsers capture at 48 kHz in odd packet sizes - the stateful resampler must keep the pipeline working."""
    from scipy.signal import resample_poly

    stt = ScriptedSTT()
    monkeypatch.setattr(session_mod, "get_stt", lambda: stt)
    with TestClient(app) as c:
        c.post("/api/demo/reset", headers=STAFF)
        files = [
            ("files", (f, wav(f), "audio/wav"))
            for f in ["real_1089_0.wav", "real_1089_1.wav", "real_1089_2.wav"]
        ]
        c.post("/api/customers/cus_ananya/enroll", headers=STAFF, files=files)
        m = get_voice_engine().mock
        m.force_speaker, m.force_spoof = 0.93, 0.03
        j = c.post("/api/calls", json={"customer_id": "cus_ananya"}).json()
        with c.websocket_connect(j["ws_url"]) as ws:
            session_mod.SESSIONS[j["call_id"]].seg.end_frames = 100
            ws.send_text(json.dumps({"type": "config", "sample_rate": 48000}))
            _recv_until(ws, lambda m: m["event"] == "agent_say")
            x48 = resample_poly(audio("real_1089_3.wav"), 3, 1).astype("float32")
            stt.say("unfreeze my debit card")
            for i in range(0, x48.size, 2048):
                ws.send_bytes(float_to_pcm16(x48[i : i + 2048]))
            ws.send_text(json.dumps({"type": "end_utterance"}))
            chal, _ = _recv_until(
                ws,
                lambda m: (
                    m["event"] == "agent_say" and m["data"]["kind"] == "challenge"
                ),
            )
            assert chal
            ws.send_text(json.dumps({"type": "hangup"}))
