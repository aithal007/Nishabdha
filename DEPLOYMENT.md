# Deployment notes: Nishabdha

The security update requires one worker, persistent SQLite storage and a persistent bank signing key. Set `BANK_ORIGIN` to the exact HTTPS application origin and `WEBAUTHN_RP_ID` to its hostname before registering passkeys. Staff provisioning and strong staff/audit secrets are required. Review [SECURITY.md](docs/SECURITY.md) and provider hosting terms before deploying; the historical free-tier examples below are not verified pricing or availability guarantees.

This guide explains how to deploy **UNCLONE Voice Banking Guard** (with continuous deepfake detection, voice biometric verification, autonomous threat research, web scraping, and grounded RAG) **completely for free**.

---

## 🏆 Option 1: Hugging Face Spaces (Recommended — 100% Free Forever)

**Why this is the best free option:**
- **Specs:** **16 GB RAM**, **2 vCPUs**, and 50 GB storage — completely free without a credit card.
- **Microphone Support:** Automatic HTTPS URL (`https://your-space.hf.space`), which modern browsers require for microphone audio streaming.
- **WebSocket Friendly:** Full bi-directional streaming support for live voice calls and fraud desk feeds.

### Steps:

1. **Sign Up / Log In**: Go to [Hugging Face](https://huggingface.co) and sign in.
2. **Create New Space**:
   - Click your profile icon at top-right → **New Space**.
   - **Space Name:** `unclone-voice-guard` (or your preferred name).
   - **License:** `mit` or `apache-2.0`.
   - **Space SDK:** Select **Docker** → **Blank**.
   - **Space Hardware:** Select **CPU Basic (2 vCPU · 16 GB RAM · Free)**.
   - Click **Create Space**.
3. **Push Code**:
   ```bash
   git remote add space https://huggingface.co/spaces/<YOUR_USERNAME>/unclone-voice-guard
   git push space main
   ```
   *(Or drag-and-drop the files via the Hugging Face web interface).*
4. **Configure Secrets**:
   - Go to **Settings** → **Variables and secrets**.
   - Add Secret: `GROQ_API_KEY` = `your_free_groq_key` (Get free at [console.groq.com](https://console.groq.com/keys)).
   - Add Secret (Optional): `STAFF_API_KEY` = `your_secure_password`.
   - Add Secret (Optional): `DETECTIFAI_API_KEY` = `venue_key_when_available`.
5. **Done!** Your Space builds in ~2 minutes and runs at `https://<YOUR_USERNAME>-unclone-voice-guard.hf.space`.

---

## ☁️ Option 2: Render Free Web Service

Render offers free web services using Docker containers.

### Steps:
1. Push your repository to **GitHub** or **GitLab**.
2. Sign in to [Render.com](https://render.com).
3. Click **New +** → **Web Service**.
4. Select your `UnClone` repository.
5. In settings:
   - **Environment:** `Docker` (Render will automatically detect `Dockerfile` and `render.yaml`).
   - **Plan:** `Free`.
   - **Health Check Path:** `/health`.
6. Add Environment Variables:
   - `GROQ_API_KEY`: Your Groq API key.
   - `APP_ENV`: `demo`.
7. Click **Create Web Service**.

> **Note on Render Free Tier:** Render spins down free containers after 15 minutes of inactivity; the next request will take ~40 seconds to warm up. For instant continuous availability without sleep, Option 1 (Hugging Face Spaces) is recommended.

---

## ⚡ Option 3: Railway / Koyeb Free Tiers

1. Connect your GitHub repository.
2. Railway and Koyeb automatically read the root `Dockerfile` and launch `python run.py`.
3. Set `PORT` (automatically injected by Railway/Koyeb) and `GROQ_API_KEY`.
4. The service will be live on an HTTPS domain with automatic SSL certificates.

---

## 🛠️ Free Engines Summary

| Feature | Primary Provider | Fallback / Zero-Cost Mode | Cost |
|---|---|---|---|
| **LLM & RAG** | Groq (`qwen/qwen3.8-27b`) | Rule-based semantic extractor + FTS5 BM25 | Free (Groq free tier) |
| **Speech-to-Text (STT)** | Groq Whisper Large-v3-Turbo | faster-whisper CPU | Free |
| **Text-to-Speech (TTS)** | Microsoft `edge-tts` (Neural en-IN, hi-IN, kn-IN) | Browser Web Speech API | Free |
| **Speaker Verification** | DetectifAI API | SpeechBrain ECAPA-TDNN (local CPU) | Free |
| **Deepfake Detection** | DetectifAI API | MelodyMachine wav2vec2 classifier (local CPU) | Free |
| **Web Research & Search** | DuckDuckGo HTML / Wikipedia API | Offline Cached Knowledge Base | Free |
| **Knowledge Store** | SQLite3 FTS5 + BM25 + Vector Cosine | In-memory / file SQLite | Free |
