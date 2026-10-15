"""Reject oversized decoded utterances before allocating a whole compressed recording."""

import io
import wave

import pytest

from app.audio import AudioError, decode_any

from .helpers import start_call


def silence(seconds):
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(bytes(32000 * seconds))
    return output.getvalue()


def test_decode_duration_rejected_before_read(monkeypatch):
    import soundfile

    class LargeRecording:
        samplerate = 16000
        channels = 1
        frames = 16000 * 3600

        def __init__(self, source):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, **kwargs):
            raise AssertionError("oversized audio must be rejected before decoding")

    monkeypatch.setattr(soundfile, "SoundFile", LargeRecording)
    with pytest.raises(AudioError, match="utterance"):
        decode_any(b"small compressed input", max_seconds=15)


def test_exact_decode_boundary_is_accepted():
    assert decode_any(silence(1), max_seconds=1).size == 16000
    with pytest.raises(AudioError, match="utterance"):
        decode_any(silence(2), max_seconds=1)


@pytest.mark.asyncio
async def test_uploaded_utterance_over_vad_limit_is_rejected(client):
    cid, headers = await start_call(client, "cus_ananya", greet=False)
    response = await client.post(
        f"/api/calls/{cid}/turn",
        headers=headers,
        files={"file": ("too-long.wav", silence(16), "audio/wav")},
    )
    assert response.status_code == 400
    assert "utterance" in response.json()["detail"]
