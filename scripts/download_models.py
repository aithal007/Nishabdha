"""Pre-download every local model BEFORE the hackathon (venue Wi-Fi is unreliable).

    python scripts/download_models.py

Downloads: SpeechBrain ECAPA (speaker), anti-spoof model(s), faster-whisper (STT fallback).
Then checks edge-tts, Groq and DetectifAI connectivity.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from app.config import get_settings  # noqa: E402


def step(name, fn):
    t = time.time()
    try:
        out = fn()
        print(f"  [OK]   {name} ({time.time() - t:.1f}s) {out or ''}")
        return True
    except Exception as e:
        print(f"  [FAIL] {name}: {type(e).__name__}: {e}")
        return False


def main():
    s = get_settings()
    print(f"Model folder: {s.model_dir}")
    noise = (np.random.default_rng(0).standard_normal(16000 * 3) * 0.05).astype(np.float32)
    ok = True

    from app.providers.local_models import LocalSpeaker, LocalSpoof

    ok &= step("speaker model (ECAPA)", lambda: LocalSpeaker(s).embed(noise).shape)
    ok &= step(f"anti-spoof model(s) {s.spoof_model_list}", lambda: LocalSpoof(s).raw_scores(noise))

    def whisper():
        from faster_whisper import WhisperModel

        m = WhisperModel(s.local_whisper_model, device="cpu", compute_type="int8", download_root=str(s.model_dir / "whisper"))
        list(m.transcribe(noise, beam_size=1)[0])
        return s.local_whisper_model

    ok &= step("faster-whisper (STT fallback)", whisper)

    async def tts():
        from app.providers.tts import TTS

        sp = await TTS(s).speak("Hello from Unclone Bank", "en")
        if sp.client_tts:
            raise RuntimeError("edge-tts unavailable (run: pip install -U edge-tts)")
        return f"{len(sp.audio_mp3)} bytes"

    step("edge-tts (internet)", lambda: asyncio.run(tts()))

    async def groq():
        if not s.groq_api_key:
            raise RuntimeError("GROQ_API_KEY not set in .env")
        from app.providers.llm import LLM

        return await LLM(s).json_chat("Return JSON {\"ok\": true}", "ping")

    if s.llm_provider == "groq" or s.stt_provider == "groq":
        step("Groq API key", lambda: asyncio.run(groq()))
    if s.detectifai_base_url:
        print("  DetectifAI configured - run scripts/check_detectifai.py with a voice clip")
    else:
        print("  DetectifAI not configured yet (fill DETECTIFAI_* in .env on day 1)")
    print("\nAll local models ready." if ok else "\nSome downloads failed - fix before the event!")


if __name__ == "__main__":
    main()
