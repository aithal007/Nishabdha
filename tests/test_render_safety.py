import os

from run import _apply_render_memory_safety


def test_render_uses_memory_safe_defaults_without_overriding_groq(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("VOICE_PRIMARY", "local")
    monkeypatch.setenv("VOICE_FALLBACK", "local")
    monkeypatch.setenv("STT_PROVIDER", "local")
    monkeypatch.setenv("STT_FALLBACK", "local")
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("NISHABHA_ALLOW_LOCAL_MODELS", "false")

    _apply_render_memory_safety()

    assert os.getenv("APP_ENV") == "demo"
    assert os.getenv("VOICE_PRIMARY") == "detectifai"
    assert os.getenv("VOICE_FALLBACK") == "mock"
    assert os.getenv("STT_PROVIDER") == "groq"
    assert os.getenv("STT_FALLBACK") == "none"
    assert os.getenv("LLM_PROVIDER") == "groq"


def test_render_disables_unconfigured_cloud_models(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("NISHABHA_ALLOW_LOCAL_MODELS", "false")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("STT_PROVIDER", raising=False)
    monkeypatch.delenv("STT_FALLBACK", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("VOICE_PRIMARY", raising=False)
    monkeypatch.delenv("VOICE_FALLBACK", raising=False)

    _apply_render_memory_safety()

    assert os.getenv("APP_ENV") == "demo"
    assert os.getenv("VOICE_FALLBACK") == "mock"
    assert os.getenv("STT_PROVIDER") == "none"
    assert os.getenv("STT_FALLBACK") == "none"
    assert os.getenv("LLM_PROVIDER") == "none"
