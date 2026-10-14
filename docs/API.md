# Frontend contract

Base URL: `http://<laptop-ip>:8000`. Interactive docs: `/docs`.

## Auth headers

| Who | Header | WebSocket query |
|---|---|---|
| Fraud desk / admin | `X-Staff-Key: <STAFF_API_KEY>` | `?staff_key=` |
| Customer phone app | `X-App-Token: app-ananya-demo` | `?token=` |
| One caller / one call | `X-Call-Token: <call_token>` | `?token=` |

## 1. Caller screen (the "phone call")

Start the call:

```http
POST /api/calls
{"customer_id": "cus_ananya", "lang": "en"}
```

- `customer_id` is optional. Without it, the agent asks for the registered mobile number.
- `caller_number` can be sent instead of `customer_id`.
- Response: `{"call_id", "call_token", "ws_url", "customer_id", "enrolled"}`

Then connect to `ws://host:8000{ws_url}`.

**Send (client → server)**
- **Binary frames:** raw PCM16 little-endian, mono, **16 kHz** by default, any size up to 64 KB (send ~100 ms per frame).
  - At another rate, send `{"type":"config","sample_rate":48000}` first. The server resamples without clicks.
  - Use `getUserMedia({audio:{echoCancellation:true, noiseSuppression:true}})` + AudioWorklet.
- `{"type":"playback","id":"m3","state":"ended"}`: send this when an agent clip finishes playing.
  - It makes liveness timing more accurate.
  - Even if the client never sends it, the server still estimates the timing.
- `{"type":"end_utterance"}`: optional push-to-talk release. Server VAD also ends turns after 0.7 s of silence.
- `{"type":"text","text":"..."}`: typed turn. It never unlocks sensitive actions by itself.
- `{"type":"hangup"}`, `{"type":"ping"}`

**Receive (server → client)** `{"event": ..., "data": {...}}`

| event | data |
|---|---|
| `ready` | expected audio format, `customer_id`, `enrolled`, `lang` |
| `agent_say` | `id`, `text`, `lang`, `kind` (greeting / normal / challenge / stepup / result / refusal / warning / goodbye), `audio_mp3_b64` (null → speak `text` with browser `speechSynthesis`, `client_tts:true`), `est_duration_s`, `challenge_id?`, `stepup_id?` |
| `transcript` | what the caller said: `text`, `lang`, `t_start`, `t_end` |
| `action_executed` | `intent`, `result.summary`, `result.data` |
| `call_ended` | `outcome` |
| `error` | `message` |

Detection scores are **never** sent to the caller socket. Show them on the fraud-desk view.

**REST fallback:** `POST /api/calls/{id}/turn` (multipart `file`, one utterance) or `/text`, with `X-Call-Token`. Returns `{"events":[...]}`. Add `X-Staff-Key` to also get `internal` (all events). Live timing isn't available over REST.

End the call with `POST /api/calls/{id}/end`.

## 2. Customer phone app

**Live updates:** connect to `ws://host:8000/ws/customer/{customer_id}?token=app-ananya-demo`.

| event | when | show |
|---|---|---|
| `stepup_request` | agent needs approval | `action`, `code` (6 digits), `reasons`, `warning`, `expires_at`; buttons Approve / This isn't me |
| `incoming_bank_call` | bank is calling the customer | `code` (4 digits), `reason`. "The agent will say this code." |
| `bank_call_verification` | caller asked "is this really the bank?" | `code` |
| `call_connected` | customer is on a verified bank line | `message` |
| `security_alert` | an attempt was blocked | `message` |
| `account_activity` | action completed | `summary` |
| `call_ended` | | |

**REST endpoints (all take `X-App-Token`)**
- `GET /api/app/me`: profile, balances, cards
- `GET /api/app/pending`: open approvals + current bank call (polling fallback)
- `POST /api/app/stepups/{id}/approve` and `/deny` (deny = critical fraud ticket)
- `GET /api/app/bank-call`: `{"genuine_bank_call": false, ...}` means whoever claims to be the bank is fake
- `POST /api/app/bank-call/{notice_id}/confirm` and `/report`
- `POST /api/app/cards/{last4}/freeze`: in-app kill switch

## 3. Fraud desk dashboard (staff key)

**Live updates:** connect to `ws://host:8000/ws/dashboard?staff_key=...` for every event of every call. Use `/ws/watch/{call_id}` for a single call.

| event | data |
|---|---|
| `call_started`, `identified`, `call_ended` | call lifecycle |
| `trust_update` | `chunk` {`seq`, `t_start`, `t_end`, `speaker_prob`, `synthetic_prob`, `flags`, `purpose`, `engine`}, `trust`, `speaker_ema`, `recent_synthetic`, `risk_state` (unknown / trusted / uncertain / suspicious / fraud), `locked`, `swap` |
| `segment_flagged` | `t_start`, `t_end`, `flags` (synthetic / synthetic_suspect / speaker_mismatch / voice_swap), `clip`. Draw the red waveform region from this. |
| `voice_swap` | `t_start`, `baseline`, `observed`, `reason` |
| `nlu`, `action_requested` | intent, tier, params |
| `decision` | `outcome` (allow / challenge / stepup / refuse), `trust`, `reasons[]`, `factors{}` |
| `protective_freeze`, `challenge_issued`, `challenge_result` (`passed`, `latency_s`, `speaker_prob`, `synthetic_prob`) | |
| `stepup_sent`, `stepup_result` | |
| `pressure_detected` | `score`, `level`, `cues[]` |
| `action_executed`, `action_failed`, `action_refused`, `action_cancelled` | |
| `ticket_created`, `ticket_updated`, `bank_call_verdict`, `voice_enrolled` | |
| `agent_say`, `transcript` | live captions (no audio) |

**REST endpoints**

| Endpoint | Purpose |
|---|---|
| `GET /api/dashboard/summary` | today's counts, open tickets, live calls with trust and pending action |
| `GET /api/calls?status=active` | call list |
| `GET /api/calls/{id}` | live state of one call |
| `POST /api/calls/{id}/terminate` | end a call from the desk |
| `GET /api/calls/{id}/report` | **evidence report**: `verdict`, `voice_checks[]`, `flagged_segments[]`, `waveform{envelope[300], flagged_ranges[]}`, `actions[]`, `liveness_challenges[]`, `step_ups[]`, `tickets[]`, `timeline[]`, `audit`, `integrity` |
| `POST /api/reports/verify` | post a report back; returns `{"valid": true/false}` |
| `GET /api/calls/{id}/clips/{name}`, `/recording` | wav audio |
| `GET /api/tickets?status=open` | ticket list |
| `PATCH /api/tickets/{id}` | body `{"status": "confirmed_fraud", "note": "", "lock_customer_voice": true}` |
| `GET /api/audit/verify` | `{"valid": true, ...}`; after tampering returns `broken_at_seq` |
| `GET /api/audit` | audit log entries |
| `POST /api/bank-calls` | body `{"customer_id", "reason"}`; the bank calls the customer (returns `ws_url` for the agent side) |

**Customers & enrollment**

| Endpoint | Purpose |
|---|---|
| `GET /api/customers` | customer list |
| `POST /api/customers` | create a customer |
| `GET /api/customers/{id}` | one customer |
| `GET /api/enrollment/phrases?lang=en` | phrases to read |
| `POST /api/audio/quality` | live "too quiet / noisy" check |
| `POST /api/customers/{id}/enroll` | multipart `files` ×3–5; staff key or the customer's app token |
| `DELETE /api/customers/{id}/enrollment` | remove enrollment |
| `POST /api/demo/reset` | wipe and reseed the demo bank |

**Admin**

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | engine chain, circuit breakers, keys present |
| `POST /api/admin/voice-check` | `file` (+ `customer_id`); raw scores for any clip, good for showing judges a clone |
| `POST /api/admin/calibrate-spoof` | `genuine` files; suggested local threshold |
