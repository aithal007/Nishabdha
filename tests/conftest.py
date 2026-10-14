"""Test setup. Env vars are set BEFORE the app is imported (settings + DB engine are created at import).

TEST_VOICE=mock  (default) fast deterministic engine with forced scores
TEST_VOICE=local real SpeechBrain ECAPA + wav2vec2 anti-spoof models on real/TTS audio (slow, realistic)
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

ASSETS = Path(__file__).parent / "assets"
_TMP = tempfile.mkdtemp(prefix="unclone_test_")
os.environ.update(
    {
        "APP_ENV": "test",
        "DATA_DIR": _TMP,
        "DATABASE_URL": "",
        "STAFF_API_KEY": "staff-test",
        "AUDIT_HMAC_SECRET": "audit-test",
        "VOICE_PRIMARY": os.environ.get("TEST_VOICE", "mock"),
        "VOICE_FALLBACK": "none",
        "DETECTIFAI_BASE_URL": "",
        "STT_PROVIDER": "none",
        "STT_FALLBACK": "none",
        "TTS_PROVIDER": "none",
        "LLM_PROVIDER": "none",
        "MODEL_DIR": os.environ.get("TEST_MODEL_DIR", str(Path(__file__).resolve().parents[1] / "models")),
    }
)

import asyncio  # noqa: E402

import numpy as np  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.audio import decode_any  # noqa: E402
from app.core import session as session_mod  # noqa: E402
from app.db import init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.providers.stt import Transcript  # noqa: E402
from app.providers.voice_engine import get_voice_engine  # noqa: E402
from app.seed import reset_demo  # noqa: E402

STAFF = {"X-Staff-Key": "staff-test"}


class ScriptedSTT:
    """Real audio goes to the voice engines; the transcript comes from the test script."""

    def __init__(self):
        self.queue: list[str] = []

    def say(self, *texts: str):
        self.queue.extend(texts)

    async def transcribe(self, audio, call_lang="en", **kw):
        text = self.queue.pop(0) if self.queue else ""
        return Transcript(text, call_lang, "scripted", 1)


@pytest.fixture(scope="session")
def event_loop_policy():
    return asyncio.DefaultEventLoopPolicy()


@pytest_asyncio.fixture
async def stt(monkeypatch):
    fake = ScriptedSTT()
    monkeypatch.setattr(session_mod, "get_stt", lambda: fake)
    return fake


@pytest_asyncio.fixture
async def client():
    await init_db()
    await reset_demo()
    eng = get_voice_engine()
    eng.mock.force_speaker = None
    eng.mock.force_spoof = None
    eng.mock.speaker_queue.clear()
    eng.mock.spoof_queue.clear()
    eng._ref_cache.clear()
    for b in eng.breakers.values():
        b.ok()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", timeout=300) as c:
        yield c
    for s in list(session_mod.SESSIONS.values()):
        await s.end("test_teardown")


def wav(name: str) -> bytes:
    return (ASSETS / name).read_bytes()


def audio(name: str) -> np.ndarray:
    return decode_any(wav(name))


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TMP, ignore_errors=True)
