"""Text-to-speech via edge-tts (free Microsoft neural voices: en-IN / hi-IN / kn-IN).

If edge-tts fails (no internet / Microsoft changes its endpoint - old edge-tts versions get HTTP 403,
keep it upgraded) the reply is sent as text with `client_tts=True` so the frontend speaks it with the
browser's speechSynthesis. The call never goes silent.
"""
from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from dataclasses import dataclass

from app.config import Settings, get_settings
from app.providers.base import CircuitBreaker

log = logging.getLogger("unclone.tts")


@dataclass
class Speech:
    text: str
    lang: str
    audio_mp3: bytes | None
    voice: str
    source: str  # edge | client

    @property
    def client_tts(self) -> bool:
        return self.audio_mp3 is None


class TTS:
    def __init__(self, s: Settings | None = None, cache_size: int = 256):
        self.s = s or get_settings()
        self._cache: OrderedDict[tuple[str, str], bytes] = OrderedDict()
        self._cache_size = cache_size
        self.breaker = CircuitBreaker("edge_tts", 2, 60.0)

    async def _edge(self, text: str, voice: str) -> bytes:
        import edge_tts

        buf = bytearray()
        async for chunk in edge_tts.Communicate(text, voice).stream():
            if chunk.get("type") == "audio":
                buf.extend(chunk["data"])
        if not buf:
            raise RuntimeError("edge-tts returned no audio")
        return bytes(buf)

    async def speak(self, text: str, lang: str = "en") -> Speech:
        voice = self.s.voice_for(lang)
        key = (voice, text)
        if key in self._cache:
            self._cache.move_to_end(key)
            return Speech(text, lang, self._cache[key], voice, "edge")
        if self.s.tts_provider == "none" or self.breaker.is_open or not text.strip():
            return Speech(text, lang, None, voice, "client")
        try:
            audio = await asyncio.wait_for(self._edge(text, voice), self.s.tts_timeout_s)
            self.breaker.ok()
            self._cache[key] = audio
            if len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
            return Speech(text, lang, audio, voice, "edge")
        except Exception as e:
            self.breaker.fail(e)
            log.warning("TTS failed, falling back to client speech: %s", e)
            return Speech(text, lang, None, voice, "client")


_tts: TTS | None = None


def get_tts() -> TTS:
    global _tts
    if _tts is None:
        _tts = TTS()
    return _tts
