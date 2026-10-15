from app.config import (
    Settings,
    apply_render_identity,
    apply_render_memory_safety,
    get_settings,
)


def test_render_identity_uses_only_platform_hostname_for_localhost_defaults():
    settings = Settings(
        _env_file=None, bank_origin="http://localhost:8000", webauthn_rp_id="localhost"
    )
    apply_render_identity(
        settings, {"RENDER_EXTERNAL_HOSTNAME": "nishabdha.onrender.com"}
    )
    assert settings.bank_origin == "https://nishabdha.onrender.com"
    assert settings.webauthn_rp_id == "nishabdha.onrender.com"


def test_render_identity_preserves_explicit_custom_origin_and_rejects_url_input():
    settings = Settings(
        _env_file=None,
        bank_origin="https://bank.example",
        webauthn_rp_id="bank.example",
    )
    apply_render_identity(
        settings, {"RENDER_EXTERNAL_HOSTNAME": "nishabdha.onrender.com"}
    )
    assert (
        settings.bank_origin == "https://bank.example"
        and settings.webauthn_rp_id == "bank.example"
    )
    settings = Settings(
        _env_file=None, bank_origin="http://localhost:8000", webauthn_rp_id="localhost"
    )
    apply_render_identity(
        settings,
        {"RENDER_EXTERNAL_HOSTNAME": "https://nishabdha.onrender.com/attacker"},
    )
    assert settings.bank_origin == "http://localhost:8000"
    apply_render_identity(
        settings,
        {
            "RENDER_EXTERNAL_HOSTNAME": "nishabdha.onrender.com",
            "BANK_ORIGIN": "http://localhost:8000",
        },
    )
    assert settings.bank_origin == "http://localhost:8000"


def test_render_uses_memory_safe_defaults_without_overriding_groq():
    settings = Settings(
        _env_file=None,
        app_env="dev",
        voice_primary="local",
        voice_fallback="local",
        stt_provider="local",
        stt_fallback="local",
        llm_provider="groq",
        groq_api_key="test-key",
    )

    activated = apply_render_memory_safety(settings, {"RENDER": "true"})

    assert activated
    assert settings.app_env == "demo"
    assert settings.voice_primary == "detectifai"
    assert settings.voice_fallback == "mock"
    assert settings.stt_provider == "groq"
    assert settings.stt_fallback == "none"
    assert settings.llm_provider == "groq"


def test_render_disables_unconfigured_cloud_models():
    settings = Settings(
        _env_file=None,
        app_env="dev",
        voice_fallback="local",
        stt_provider="groq",
        stt_fallback="local",
        llm_provider="groq",
        groq_api_key="",
    )

    activated = apply_render_memory_safety(settings, {"RENDER_SERVICE_ID": "srv-demo"})

    assert activated
    assert settings.app_env == "demo"
    assert settings.voice_fallback == "mock"
    assert settings.stt_provider == "none"
    assert settings.stt_fallback == "none"
    assert settings.llm_provider == "none"


def test_render_local_models_require_explicit_opt_in():
    settings = Settings(_env_file=None, voice_fallback="local")

    activated = apply_render_memory_safety(
        settings,
        {"RENDER": "true", "NISHABHA_ALLOW_LOCAL_MODELS": "true"},
    )

    assert not activated
    assert settings.voice_fallback == "local"


def test_cached_settings_apply_render_safety_before_provider_creation(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    for key in (
        "APP_ENV",
        "VOICE_PRIMARY",
        "VOICE_FALLBACK",
        "STT_PROVIDER",
        "STT_FALLBACK",
        "LLM_PROVIDER",
        "GROQ_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.app_env == "demo"
        assert settings.voice_fallback == "mock"
        assert settings.stt_fallback == "none"
        assert settings.stt_provider == "none"
    finally:
        get_settings.cache_clear()
