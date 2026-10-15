# Security implementation

## Runtime and migration

Run one Uvicorn worker and persist `DATA_DIR`. SQLite uses WAL and `BEGIN IMMEDIATE` for transfer writes. Additive security tables preserve historical records; migration v2 expires legacy pending approvals and cancels legacy unexecuted actions. Keep the bank signing key with the database backup. Do not rotate it accidentally on restart.

Use `BANK_ORIGIN=http://localhost:8000` and `WEBAUTHN_RP_ID=localhost` locally. Hosting requires a fixed HTTPS origin and matching RP ID. Neither is derived from request headers. Registration requires staff authorization.

## Approval API

- Staff: `POST /api/admin/customers/{id}/passkeys/options` creates registration options and an approval ID.
- Customer: `POST /api/app/passkeys/verify` with `{approval_id, credential}` validates registration or authentication. Customer routes use `X-App-Token`; staff routes use `X-Staff-Key`.
- `GET /api/app/pending` returns stored immutable transaction details, `action_hash` and `requires_passkey` beside existing step-up fields.
- `POST /api/app/passkeys/options` with `{purpose:"transfer",stepup_id}` issues a challenge bound to the frozen action. Token-only `/stepups/{id}/approve` returns 403 for transfers.
- Delegation uses `{purpose:"delegation",binding_hash}` and the same verification endpoint. Its approval can be consumed once for the matching grant.

WebAuthn verifies challenge, RP ID, origin, credential ownership and user verification. The application maps the challenge to immutable displayed transaction details; WebAuthn cannot prove that a person understood the screen.

## Transfer boundary

The frozen object binds customer, source account, exact beneficiary ID/destination, amount in integer paise, currency, session, expiry, version and nonce. Fuzzy name suggestions cannot execute transfers. Changed details invalidate approval. Missing or stale DetectifAI evidence holds voice transfers; local fallback does not silently acquire sponsor assurance.

Every transfer also requires a verified passkey approval. The gateway atomically checks and consumes it, conditionally debits sufficient funds, records the transaction and result, and persists a signed receipt. The action ID is the idempotency key. Concurrent retries cannot repeat the debit. Approve/deny state transitions use conditional updates.

## Agent interfaces

`GET /.well-known/jwks.json` publishes the configured origin's signing key. Authenticated `GET /api/app/bank-call/{notice_id}/proof` returns a signed outbound-session record. The customer app must already trust the bank origin. A caller-supplied key, link, logo or short code is not a trust anchor.

`POST /api/app/agents/delegation-binding` takes `{holder_jwk}` and returns the canonical grant binding. Obtain and verify a delegation passkey assertion, then `POST /api/app/agents/grants` with `{holder_jwk,approval_id}`. Permission is fixed to one support ticket for ten minutes. Revoke through `/api/app/agents/grants/{id}/revoke`.

The holder obtains `/api/agents/grants/{id}/nonce`, signs the request using its ES256 key, then calls `/execute` with `{proof,action,subject}`. The server verifies the configured audience, key, freshness, nonce, grant, body hash, scope and revocation before atomically consuming permission. `scripts/delegate_demo.py` documents the client flow.

## Limits and evaluation

Session signatures verify an application session, not arbitrary telephone audio. Timing and digit challenges do not reliably defeat interactive clones or relays. Voice results are fraud evidence, not legal identity proof. Signatures attest to records; retain a signed checkpoint separately to detect later log-tail deletion. Key compromise, poisoned enrollment and compromised trusted UI remain outside prototype assurance.

Evaluate with consented genuine, wrong-speaker, synthetic, noisy and multilingual clips, separating tuning from held-out samples. Record provider/version, format, duration, score direction, configured threshold, both provider outputs, application decision, mutation count and end-to-end latency. Report collected counts and limitations; do not present mock tests as detection benchmarks. Live DetectifAI measurements require credentials and are not fabricated.

Demo sequence: real customer transfer with passkey; clone held/refused; signed bank-session verification; valid synthetic delegate ticket; delegate transfer denied; replay/tamper denied; provider outage held. Clearly label fixtures and keep a recorded backup.
