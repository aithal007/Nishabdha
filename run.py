"""Universal server entrypoint for Local and Free Cloud Deployments (Render, Hugging Face Spaces, Railway, Koyeb)."""
from __future__ import annotations

import os

import uvicorn

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")
    print(f"[*] Starting UNCLONE Voice Banking Guard on {host}:{port}")
    uvicorn.run("app.main:app", host=host, port=port, log_level="info")
