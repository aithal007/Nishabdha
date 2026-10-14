# UNCLONE: Voice Banking Guard (backend)

This is a voice banking agent. It answers routine questions, and it blocks sensitive actions until the caller is proven to be the real customer. A cloned voice gets refused and escalated before any money moves.

Built for the **UNCLONE hackathon**, Track 03 "Unclone Agents" (BMSCE x DetectifAI, 16–17 Oct 2026).

---

## Quick start (Windows, CPU)

1. Install **Python 3.11** from python.org. Tick "Add to PATH".
2. Double-click **`setup.bat`**. It creates the venv, installs everything and downloads about 1.5 GB of models. **Do this at home, before the event.**
3. Get a free key at https://console.groq.com/keys and put `GROQ_API_KEY=...` in `.env`. Also change `STAFF_API_KEY` and `AUDIT_HMAC_SECRET`.
4. Double-click **`run.bat`**. The API runs on http://localhost:8000 and the interactive docs are at http://localhost:8000/docs.
5. Optional: double-click `test.bat` to run all tests (about 90).

### Open the app

Go to **http://localhost:8000**. It's one page with three tabs:
- **Call:** talk to the bank with your mic, or type. "Play an audio file as the caller" sends a recorded or cloned clip.
- **Phone app:** the customer's phone. It shows approvals, "is the bank calling me?" and cards, and has Voice ID setup.
- **Fraud desk:** enter the staff key at the top. It shows live trust, red flagged segments, decisions, tickets and the signed evidence report.

The mic needs `localhost` or https. To use it from another laptop on Wi-Fi, open the page on the machine running the server.

### Terminal tools (no browser needed)

Run each command in its own terminal:

```bat
python scripts\cli.py desk                                  :: fraud-desk live feed
python scripts\cli.py app --customer cus_ananya             :: simulated phone (type a / d to approve / deny)
python scripts\cli.py enroll --customer cus_ananya --mic    :: register your voice (reads 4 phrases)
python scripts\cli.py call --customer cus_ananya --mic      :: talk to the bank (Enter = start/stop)
```

Demo customers (seeded): `cus_ananya` (EN, 2 cards), `cus_rahul` (HI), `cus_lakshmi` (KN). App tokens are `app-<name>-demo`.

---

## Day 1 at the venue: plug in DetectifAI (≈10 minutes)

1. Read their API docs. Fill the `DETECTIFAI_*` lines in `.env`: base URL, key, endpoint paths, field names, and **where the score sits in the JSON** (e.g. `data.similarity`). You also set whether the score is a percentage and whether the deepfake score means "real" or "fake".
2. Record two short clips (yours, and a teammate's) and run:
   `python scripts\check_detectifai.py --audio me.wav --audio2 teammate.wav`
   It prints the raw JSON and the parsed scores. Your own clip should score HIGH, the other person LOW, and real voices should score low on synthetic.
3. Restart `run.bat`. `GET /api/health` should show `"chain": ["detectifai", "local"]`.
4. Calibrate the local backup to the room mic: send 5–10 genuine clips to `POST /api/admin/calibrate-spoof`. Put the suggested value into `LOCAL_SPOOF_THRESHOLD`.
5. **Re-enroll** demo voices after DetectifAI is configured, so both engines hold a voiceprint.

Usually no code change is needed. If their API is shaped very differently, only `app/providers/detectifai.py → _request()` needs editing.

---

## The 12 features and where they live

| # | Feature | How it works | Code |
|---|---|---|---|
| 1 | Voice enrollment | 3–5 phrases go through a quality gate (speech length, loudness, clipping, noise). Clips are **screened for deepfakes before enrolling**, so nobody can register a clone. Enrolling needs staff or the customer's own app token. | `core/enrollment.py` |
| 2 | Risk tiers | The LLM only *classifies* intent. The tier comes from a fixed table in code, so prompt injection can't lower security. Tier 0 is FAQ, Tier 1 is balance/transactions/freeze, Tier 2 is unfreeze/block/limit/international/mobile/payee/transfer. | `core/policy.py` |
| 3 | Continuous checks | Every ~3 s of *speech* (silence excluded) gets a speaker check and a deepfake check in parallel. The background worker never blocks the conversation. | `core/session.py`, `providers/voice_engine.py` |
| 4 | Liveness challenge | 4 random digits, which work in EN/HI/KN. The answer's own audio is checked as well. Answer timing is measured on the server, which catches slow real-time voice-conversion pipelines and replays. A wrong answer gets a retry with *new* digits. Reciting long digit strings is rejected. | `core/liveness.py` |
| 5 | Trust fusion | Rolling speaker-match EMA × (1 − recent synthetic risk), fused with the challenge score (weighted higher). The result is **allow / challenge / step-up / refuse**, with reasons in plain words. If the engines are down, it fails closed. | `core/trust.py` → `decide()` |
| 6 | Refuse + escalate | A fixed refusal script (no LLM) plays. The action is put on hold, a ticket is opened with audio clips, and the customer's app gets "we stopped an attempt…". The call stays locked for sensitive actions. | `session._refuse` |
| 7 | Mid-call swap | A clean baseline followed by a sharp drop in speaker score (CUSUM), or a synthetic segment after a genuine start, means the voice was swapped. The call is locked and the segment is marked red. | `TrustState._swap_check` |
| 8 | Proof report | Every score, decision, challenge and step-up, a timeline, a waveform with red ranges, and a SHA-256 + HMAC signature. The audit log is **hash-chained**, so any DB edit is detected. | `core/evidence.py`, `core/audit.py` |
| 9 | Two-way trust | When the bank calls out, a 4-digit code appears in the customer's app and the agent speaks the same code. The customer can also ask "is this really the bank?" mid-call. If the app shows nothing, the caller is an impersonator. | `POST /api/bank-calls`, `/api/app/bank-call` |
| 10 | Pressure tactics | Instant multilingual lexicon (police / arrest / safe account / urgency / secrecy / OTP / AnyDesk / coaching) plus the LLM's score. High pressure plays a warning and forces step-up. | `core/pressure.py` |
| 11 | OTP channel rules | Approval goes **only** to the registered app. The step-up module never even sees a new number. For money movement and mobile changes, the code **cannot be read out on the call** (that blocks OTP relay); only the in-app Approve button counts. Codes are hashed, expire, are single-use, and lock after 3 tries. New payees have a 24 h cooling period and transfers are capped per call. | `core/stepup.py`, `core/banking.py` |
| 12 | Fraud desk | Live WebSocket feed, live calls with trust, tickets (confirm fraud → lock the customer's voice channel, which also applies to live calls), terminate a call, download clips and recordings, verify the audit chain. | `api/staff.py`, `/ws/dashboard` |
| 13 | Autonomous Research & Grounded RAG | Scrapes web advisories and banking regulations (RBI guidelines, digital arrest scam alerts, voice clone threats) via DuckDuckGo and clean article extraction. Extracts structured claims with epistemic tags into an indexed SQLite FTS5 store, providing grounded RAG with verbatim citations and verification for callers and fraud analysts. | `knowledge/pipeline.py`, `knowledge/rag.py`, `api/knowledge.py` |

**Extra safety**
- A "block my card" request **freezes the card instantly** (reversible and protective) and then gates the permanent block.
- Detection scores are **never sent to the caller**, so an attacker can't tune a clone against them.
- Typed input has no voice evidence, so it can only end in an app approval.
- Grounded RAG verifies every cited statement against stored verbatim evidence before presenting it to callers or staff.


---

## Engines (all free)

| Job | Primary | Automatic fallback |
|---|---|---|
| Speaker verification | DetectifAI | SpeechBrain ECAPA (local CPU). In tests: FAR 0.3%, FRR 0% on 3 s chunks |
| Deepfake detection | DetectifAI | wav2vec2 classifier (local CPU), high precision but weak recall |
| Speech-to-text | Groq Whisper large-v3-turbo | faster-whisper `small` (local) |
| LLM (intent/pressure) | Groq qwen3.8-27b (auto-fallback gpt-oss-120b/20b) (OpenAI / Claude / Gemini switchable) | keyword rules (EN/HI/KN + fuzzy) |
| Text-to-speech | edge-tts (en-IN / hi-IN / kn-IN neural voices) | browser speechSynthesis (`client_tts: true`) |

Every remote engine has a timeout and a circuit breaker, so a dead API is skipped instead of slowing every turn.

### Limits to know before the demo

- **Local deepfake detection is weak.** We benchmarked 5 open models on 3 s chunks. The best one flags about 30% of TTS chunks at about 1% false alarms. DetectifAI is the real detector. Without it, clones are mostly caught by the speaker match, liveness timing and step-up, not by the deepfake score.
- **A good clone of the enrolled customer's voice** gets past speaker match by design. Only the deepfake detector (DetectifAI) and the timing check stop it. Test this with DetectifAI on day 1.
- **Local Whisper is weak for Hindi and very weak for Kannada.** Keep Groq configured, and test the venue Wi-Fi.
- **Liveness timing works only on the WebSocket path.** The REST `/turn` fallback can't time answers.

---

## Run the tests

```bash
pytest -q                                       # 95 automated tests (biometrics, RAG, policy, security)
set TEST_VOICE=local && pytest tests\test_real_models.py -s   # real ECAPA + anti-spoof models
```

The tests cover: genuine caller verification, impostor mismatch, synthetic voice clone rejection, mid-call speaker swap (CUSUM), prompt injection immunity, social pressure detection, OTP brute-force limits, verbal OTP-relay blackout defense, payee cooling periods, per-call transaction caps, customer app denial, tampered audit logs, tampered evidence reports, 11-domain vector search, zero-hallucination citation verification, and DetectifAI failover.

Frontend contract: see **docs/API.md**.
Free cloud deployment guide: see **DEPLOYMENT.md**.

---

## 🗺️ Developer Handoff: What is Done vs What is Left

If you just cloned this repository or are collaborating on this project, here is the exact breakdown of the codebase architecture, what is completed, and what is remaining.

### 🎯 Feature Priority Hierarchy
1. **CORE / PRIMARY FEATURE (Voice Banking Guard)**:
   - An intelligent voice agent that speaks to the caller, understands intent, and proves who they are before taking any action.
   - Continuous multi-layered anti-fraud defense: speaker verification, synthetic deepfake detection, and active liveness timing to catch neural voice clones.
   - Ready to connect to the venue DetectifAI API on Day 1.
2. **SUB / ADDITIONAL FEATURE (Vector RAG & Autonomous Research)**:
   - A specialized vector database RAG system strictly seeded across **11 target financial & clone-threat domains**.
   - If an out-of-domain topic is queried, the **Autonomous Research Agent** automatically scrapes the web in the background, extracts verifiable claims, indexes them with vector embeddings, and answers with verifiable citations.

---

### ✅ WHAT IS COMPLETED (Ready & Fully Functional)

#### 1. Core Voice Security & Banking Engine
- [x] **Real-time Audio Pipeline (`app/audio.py`, `app/api/ws.py`)**: WebRTC VAD, continuous 16kHz and 48kHz audio ingestion, Opus/PCM streaming, and speech chunk segmentation (1.5s–3.0s).
- [x] **Continuous Biometric Checks (`app/core/session.py`)**: Parallel background speaker match and deepfake screening every ~3 seconds of speech without pausing the conversation.
- [x] **Liveness Challenge & Latency Check (`app/core/liveness.py`)**: Random 4-digit spoken challenges with millisecond server-side voice onset measurement (detects 800ms–2500ms neural voice cloning delays).
- [x] **Trust Fusion & Swap Detection (`app/core/trust.py`)**: Rolling speaker match EMA $\times$ synthetic penalty, fused with challenge score. CUSUM statistical change-point detection catches mid-call speaker swaps.
- [x] **Strict Risk Policy Tiers (`app/core/policy.py`)**: Tier 0 (FAQ/Info), Tier 1 (Balance/Statements/Card Freeze), Tier 2 (Transfers, Limit Change, Mobile Number Update, Payee Registration). Policy is hardcoded in Python to prevent LLM prompt injection escalation.
- [x] **Verbal OTP Blackout (`app/core/stepup.py`)**: Spoken OTPs are strictly disallowed on the phone line for sensitive actions (defeating OTP-relay fraud); approval must be executed via the registered mobile app.
- [x] **Protective Instant Card Freeze (`app/core/banking.py`)**: Reporting a lost/stolen card immediately executes a reversible protective freeze on the call, gating permanent cancellation behind verification.
- [x] **Social Engineering Pressure Detection (`app/core/pressure.py`)**: Multilingual lexicon (police, arrest, ED, CBI, customs, safe account, urgency) fused with LLM analysis. High pressure forces step-up authentication.
- [x] **Two-Way Trust Verification (`app/api/calls.py`)**: Generates synchronized 4-digit verification codes visible on the customer's phone app when the bank calls out.
- [x] **Cryptographic Hash-Chained Audit Ledger (`app/core/audit.py`, `evidence.py`)**: SHA-256 HMAC hash chain of all events, decisions, and scores with tamper detection (`GET /api/audit/verify`) and downloadable evidence packages.
- [x] **Live Fraud Desk (`app/api/staff.py`, `/ws/dashboard`)**: Live WebSocket dashboard showing real-time trust metrics, active calls, flagged audio clips, ticket management, and one-click channel locking / call termination.

#### 2. Vector Database, Grounded RAG & Autonomous Research (`app/knowledge/`)
- [x] **Dense Vector Embeddings (`app/knowledge/embedder.py`)**: Generates 256-dimensional float32 vector embeddings for semantic similarity and cosine matching.
- [x] **Hybrid Vector Knowledge Store (`app/knowledge/store.py`)**: SQLite vector database storing float32 embeddings, document text, and FTS5 BM25 full-text indexing.
- [x] **Pre-Seeded 11 Target Domains (`app/knowledge/seed_data.py`)**: Fully populated with authoritative guidelines and fraud intelligence for:
  1. *Banks* (RBI zero liability circular, 3-day notification, 10-day shadow credit, 90-day dispute ceiling)
  2. *NBFCs* (Digital lending rules, illegal loan app scams, recovery agent calling hours 8 AM–7 PM)
  3. *Insurers* (IRDAI spurious call alerts, fake unclaimed bonus scams, fraudulent surrender transfers)
  4. *UPI Users* (The Golden Rule: entering a PIN only debits money; QR code scams; fake screenshot apps)
  5. *Finance Teams* (CEO/CFO voice cloning wire fraud, mandatory dual authorization, vendor account change checks)
  6. *Voice Fraud Impersonation* (Neural TTS architectures, acoustic spectral anomalies, pipeline latency signatures)
  7. *KYC* (Video KYC deepfake bypass, virtual webcams, live geo-tagging, mule account syndicates)
  8. *Hiring* (Deepfake candidate impersonation in remote job interviews, proxy interview screening)
  9. *Exams* (Online proctored exam voice proxy cheating, oral defense voice clone defense)
  10. *Remote Work* (IT helpdesk vishing, MFA fatigue coercion, zero trust phone rules)
  11. *When Anybody Can Be Cloned* (Family emergency bail scams, virtual kidnapping audio extortion, family secret codeword protocol)
- [x] **Zero-Hallucination Grounded RAG (`app/knowledge/rag.py`)**: Returns answers with explicit citation tags (`[c1]`, `[d1]`) citing source URLs and domains. Includes lexical verification ensuring all statements are supported.
- [x] **Autonomous Web Research Fallback (`app/knowledge/pipeline.py`, `search.py`, `scraper.py`)**: If a query is outside the 11 pre-stored domains, the backend automatically plans search tasks, queries DuckDuckGo/Wikipedia, scrapes pages with `trafilatura`, extracts claims, generates vector embeddings, and indexes them into the database before answering.
- [x] **Caller Integration (`app/core/nlu.py`)**: Voice banking callers asking informational or policy questions receive cited, grounded spoken summaries from the RAG knowledge base.
- [x] **Interactive Frontend (`app/static/index.html`)**: Added a 4th tab ("Knowledge Base & RAG") with quick topic buttons, interactive RAG query interface with citation pills, autonomous deep research runner, and claims ledger explorer.

#### 3. Free Deployment Architecture
- [x] **Universal Entrypoint (`run.py`)**: Reads `$PORT` dynamically for container clouds.
- [x] **Hugging Face Spaces (`Dockerfile`)**: Configured with non-root user permissions, port `7860`, and PyTorch CPU (100% free forever on 16 GB RAM).
- [x] **Render Web Service (`render.yaml`)**: Configured for 1-click Docker deployment with health check at `/health`.
- [x] **Comprehensive Guide (`DEPLOYMENT.md`)**: Complete step-by-step instructions for zero-cost deployment.

---

### ⏳ WHAT IS LEFT (To Do on Day 1 at the Venue)

These items require event-specific parameters or live hardware available at the hackathon venue:

1. **Plug in DetectifAI Live Credentials (≈ 10 Minutes)**:
   - When the organizers provide API credentials, update these fields in your `.env`:
     ```ini
     DETECTIFAI_BASE_URL=https://api.detectifai.com
     DETECTIFAI_API_KEY=your_venue_api_key_here
     ```
   - Check the response format using:
     `python scripts\check_detectifai.py --audio me.wav --audio2 teammate.wav`
   - If the endpoint paths or field names differ from the defaults, update `DETECTIFAI_ENROLL_PATH`, `DETECTIFAI_VERIFY_PATH`, or `DETECTIFAI_VERIFY_SCORE_PATH` in `.env`. No code edits should be required.
2. **Room Microphone Acoustic Calibration**:
   - The local deepfake model is calibrated to standard studio audio. Record 5–10 genuine spoken clips using the venue microphone and send them to:
     `POST /api/admin/calibrate-spoof`
   - Copy the suggested threshold into `LOCAL_SPOOF_THRESHOLD` in `.env`.
3. **Re-Enroll Demo Voices with DetectifAI Connected**:
   - Re-enroll your team members' genuine voices using the UI or:
     `python scripts\cli.py enroll --customer cus_ananya --mic`
   - This ensures both the local ECAPA engine and DetectifAI store live voiceprints.
4. **Prepare Cloned Audio Clips for the Live Pitch**:
   - Generate 2–3 synthetic clone clips of your enrolled team member's voice using ElevenLabs, PlayHT, or open-source TTS.
   - During the live pitch, use the "Play an audio file as caller" button on the **Call** tab to demonstrate:
     - How the deepfake detector catches synthetic audio.
     - How the liveness digit challenge catches replay and latency.
     - How the fraud desk immediately receives a red alert and creates an evidence ticket.

---

### 🔮 OPTIONAL POST-HACKATHON / PRODUCTION ENHANCEMENTS

If you or another developer choose to take this project to enterprise production:
- **Telephony PSTN Integration**: Connect the WebSocket endpoint (`/ws/call`) to Twilio Media Streams, Asterisk, or FreeSWITCH to receive inbound calls from real mobile phone numbers.
- **Production Database**: Replace SQLite with PostgreSQL + `pgvector` for distributed multi-region horizontal scaling.
- **Mobile Push Delivery**: Replace the simulated in-browser phone WebSocket with Apple Push Notification service (APNs) and Firebase Cloud Messaging (FCM) for native iOS and Android apps.
- **Enterprise IAM & SSO**: Integrate corporate Single Sign-On (SAML/OAuth2) for staff authentication on the Fraud Desk.

