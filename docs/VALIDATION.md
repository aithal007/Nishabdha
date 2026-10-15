# Validation record

Validated locally on 15 October 2026 using Python 3.11.9 on Windows. Changes are in the local checkout; no remote push or deployment was performed.

## Results

- Original checkout baseline: 94 passed, 4 skipped, 1 failed. The pre-existing failure expected at least 30 knowledge chunks, but the original seeds produced 27.
- Updated full suite: **134 passed, 4 skipped** in 34.18 seconds (`python -m pytest -q`). The skipped tests require optional real voice models; application security tests use explicit test voice mocks.
- Browser security contract: **6 checks passed** (`node scripts/check_browser_security.cjs`) using real WebCrypto/P-256 verification, malformed/expired proofs, customer binding, canonical request hashes and simulated-mode disclosure.
- Inline application JavaScript parsed successfully; `node --check app/static/security.js` passed.
- Critical Python syntax/undefined-name check passed: `ruff check app tests --select E9,F63,F7,F82`.
- `git diff --check` passed. Broader repository lint rules include pre-existing style/security warnings and are not claimed clean.

## Covered behavior

Current-utterance evidence binding, stale/missing provider outcomes, mock isolation, typed requests, immutable playback timestamps, unauthorized bank notices, exact beneficiary selection, action tampering, passkey origin/user-verification/customer/expiry/replay checks, atomic repeated transfers, competing balance updates, approval-versus-denial races, preserved-history migration, synthetic delegate holder proofs/scope/revocation/expiry/replay, source ingestion authorization and quarantine, reviewed extractive answers, and served frontend/API contracts.

Virtual authenticators generate real signatures validated by the WebAuthn library; no test-only cryptographic verification bypass exists. Test voice scores are deliberately mocked and clearly separate from model accuracy.

## Remaining external validation

Actual DetectifAI request/response contract, enrollment behavior, score semantics/thresholds, quotas, real-audio accuracy and network latency require supplied credentials and API documentation. Hosted origin/RP settings and a physical browser authenticator require a deployment-specific smoke test. The JavaScript contract checks do not substitute for a full visual/browser or microphone/STT/TTS rehearsal.

Use `docs/SECURITY.md` for the consented held-out evaluation protocol and limitations. No detection benchmark, financial assurance certification, real payment execution or hackathon outcome is asserted.
