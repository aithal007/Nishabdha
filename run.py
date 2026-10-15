"""Universal server entrypoint for Local and Free Cloud Deployments (Render, Hugging Face Spaces, Railway, Koyeb)."""
from __future__ import annotations

import os

import uvicorn


def _apply_render_memory_safety() -> None:
    """Keep a hosted demo from loading local ML models on small Render instances.

    The free Render plan has 512 MB of RAM. A service created outside a Blueprint
    can miss render.yaml's safe settings, so apply safe defaults at the actual
    process entrypoint. Operators can opt in to local models on larger instances.
    """
    if os.getenv("RENDER", "").lower() != "true":
        return
    if os.getenv("NISHABHA_ALLOW_LOCAL_MODELS", "").lower() == "true":
        return

    os.environ["APP_ENV"] = "demo"
    if os.getenv("VOICE_PRIMARY", "detectifai").lower() == "local":
        os.environ["VOICE_PRIMARY"] = "detectifai"
    if os.getenv("VOICE_FALLBACK", "local").lower() == "local":
        os.environ["VOICE_FALLBACK"] = "mock"

    groq_configured = bool(os.getenv("GROQ_API_KEY", "").strip())
    if os.getenv("STT_PROVIDER", "groq").lower() == "local":
        os.environ["STT_PROVIDER"] = "groq" if groq_configured else "none"
    if os.getenv("STT_FALLBACK", "local").lower() == "local":
        os.environ["STT_FALLBACK"] = "none"
    if os.getenv("STT_PROVIDER", "groq").lower() == "groq" and not groq_configured:
        os.environ["STT_PROVIDER"] = "none"
    if os.getenv("LLM_PROVIDER", "groq").lower() == "groq" and not groq_configured:
        os.environ["LLM_PROVIDER"] = "none"


if __name__ == "__main__":
    _apply_render_memory_safety()
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")
    print(f"[*] Starting UNCLONE Voice Banking Guard on {host}:{port}")
    uvicorn.run("app.main:app", host=host, port=port, log_level="info")
