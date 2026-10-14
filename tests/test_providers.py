"""Provider adapters against mocked HTTP (Groq / OpenAI / Anthropic / Gemini LLM + Groq STT)."""
from __future__ import annotations

import json

import httpx
import pytest

from app.config import get_settings
from app.providers.base import ProviderError
from app.providers.llm import LLM
from app.providers.stt import STT

from .conftest import audio

pytestmark = pytest.mark.asyncio
NLU_JSON = {"intent": "card_block", "params": {"card_kind": "debit"}, "pressure": 0.1, "pressure_cues": [], "reply": "", "lang": "hi"}


def _llm(provider: str, handler) -> LLM:
    s = get_settings().model_copy(update={"llm_provider": provider, f"{provider}_api_key": "k"})
    llm = LLM(s)
    llm._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return llm


@pytest.mark.parametrize("provider", ["groq", "openai", "anthropic", "gemini"])
async def test_llm_providers(provider):
    def handler(req: httpx.Request):
        body = json.loads(req.content)
        if provider in ("groq", "openai"):
            assert body["response_format"] == {"type": "json_object"}
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(NLU_JSON)}}]})
        if provider == "anthropic":
            assert req.headers["x-api-key"] == "k"
            return httpx.Response(200, json={"content": [{"type": "text", "text": "```json\n" + json.dumps(NLU_JSON) + "\n```"}]})
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(NLU_JSON)}]}}]})

    out = await _llm(provider, handler).json_chat("sys", "user")
    assert out["intent"] == "card_block"


async def test_llm_failure_opens_breaker():
    llm = _llm("groq", lambda r: httpx.Response(500))
    for _ in range(3):
        with pytest.raises(ProviderError):
            await llm.json_chat("s", "u")
    assert not llm.available


async def test_understand_uses_llm_and_falls_back(monkeypatch):
    from app.core import nlu

    good = _llm("groq", lambda r: httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(NLU_JSON)}}]}))
    monkeypatch.setattr(nlu, "get_llm", lambda: good)
    r = await nlu.understand("mera debit card band karo")
    assert r.intent == "card_block" and r.source == "llm" and r.lang == "hi"
    bad = _llm("groq", lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "not json at all"}}]}))
    monkeypatch.setattr(nlu, "get_llm", lambda: bad)
    r = await nlu.understand("please block my card")
    assert r.intent == "card_block" and r.source == "rules"


async def test_groq_stt_and_fallback_language():
    s = get_settings().model_copy(update={"stt_provider": "groq", "stt_fallback": "none", "groq_api_key": "k"})
    stt = STT(s)
    calls = []

    def handler(req):
        calls.append(req)
        if len(calls) == 1:
            return httpx.Response(200, json={"text": "ನನ್ನ ಕಾರ್ಡ್ ಬ್ಲಾಕ್ ಮಾಡಿ", "language": "kannada", "segments": [{"no_speech_prob": 0.01}]})
        return httpx.Response(200, json={"text": "hello", "language": "tamil", "segments": []})

    stt._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    tr = await stt.transcribe(audio("real_1089_3.wav"), "en")
    assert tr.lang == "kn" and "ಕಾರ್ಡ್" in tr.text
    tr = await stt.transcribe(audio("real_1089_3.wav"), "hi")  # unsupported language detected -> retried with call language
    assert tr.lang == "hi" and len(calls) == 3
