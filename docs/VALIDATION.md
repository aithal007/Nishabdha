# Validation record

## Authority and decision implementation — 16 October 2026

- Python suite: **156 passed, 4 skipped** in 35.67 seconds. Skips require optional real voice models. New coverage includes owned masked receipts, held typed turns, false-negative authorization resilience, approved amount/recipient tampering, atomic success receipts/retries, receipt-storage rollback, invalid passkey receipts, delegate scope/replay/nonce refusal, exact PCM recording, decoded-upload limits and Render identity defaults.
- Chromium: **7 scenarios passed** in 22.8 seconds, including real browser WebAuthn signatures via a virtual authenticator, separate delegate controls, exported receipt/key files, independent signature verification without network requests, tamper refusal, revocation, desktop/mobile layout, and automated accessibility checks. An isolated Windows connection-reset callback was logged while a browser connection closed; all scenarios and browser assertions completed successfully.
- Standalone WebCrypto checks: **8 receipt-verifier cases** and **6 existing browser-security cases** passed. The verifier rejects altered payloads, wrong issuer/key, unexpected algorithms and receipt-supplied keys; historical records remain verifiable.
- Isolated attack harness: **17 passed, 0 failed, 0 skipped**, covering nine scenario groups. It writes JSON and HTML reports under ignored `data/`. Voice scores and scripted transcripts are fixtures; this is not DetectifAI accuracy evaluation.
- Production TypeScript/Vite build passed. Critical Python syntax/undefined-name checks passed. No new runtime dependencies were introduced.
- Audio memory stress: three WebSocket sessions each received **1,200 seconds of synthetic silent PCM**, accelerated, then saved recordings on disconnect. The original recording conversion exceeded the **400 MiB** test budget; direct PCM-to-WAV saving passed with **245.94 MiB** peak aggregate process working sets including venv children and cleanup. Fifteen measured seconds produced 12 typed responses, p50 **78 ms**, p95 **2,578 ms**, including initial buffer-processing backlog. These are local Windows application measurements with providers disabled, not voice/model or hosted benchmarks. Raw output: `data/audio-memory-stress.json`.

Hosted smoke checks passed on `https://nishabdha.onrender.com` after deploying implementation commit `4c75dbc`: new compiled UI and independent verifier returned 200; bank issuer matched the HTTPS origin; unauthenticated customer/staff decision routes returned 401. A typed transfer was held, its balance remained unchanged, its signed receipt verified under the deployed key, and another customer received 404 for that receipt. Headless Chromium verified the hosted receipt, rejected a tampered copy and made zero verification network requests, with no page errors. This is a single hosted authorization smoke test, not an availability or model benchmark.

The **30-minute session rehearsal passed**: 1,800 seconds, three concurrent WebSocket sessions, **534 typed responses**, unchanged balances and preserved live sessions. Maximum sampled aggregate server process-tree RSS was **100.27 MiB**, with p50 **32 ms** and p95 **78 ms** application response latency. Providers were disabled. This long run began during integration; the final recording-save path was separately stress-tested, and final changes passed the functional and hosted checks above. These local Windows results do not establish hosted memory, speech latency or DetectifAI accuracy.

Live DetectifAI integration and a physical hosted passkey remain dependent on sponsor access and deployed-origin validation. Machine-readable results: [validation-2026-10-16.json](validation-2026-10-16.json).

## Earlier implementation validation

Validated locally on 15 October 2026 using Python 3.11.9 and Node 24 on Windows. Source and compiled frontend assets are published to the project repository; this record does not assert a hosted deployment or live vendor benchmark.

## Results

- Original checkout baseline: 94 passed, 4 skipped, 1 failed. The pre-existing failure expected at least 30 knowledge chunks, but the original seeds produced 27.
- Updated full suite: **137 passed, 4 skipped** in 21.93 seconds (`python -m pytest -q`). The skipped tests require optional real voice models; application security tests use explicit test voice mocks. The new cases verify the policy-agent SSE contract, ignored client tools/instructions, and bounded request input.
- Production frontend: `npm run build --prefix frontend` passed TypeScript checking and the Vite build. FastAPI serves the committed compiled assets.
- Chromium/Playwright: **7 browser scenarios passed** in 21.1 seconds. Coverage includes a live WebSocket typed turn, customer data/navigation, CopilotKit policy replies, exact-transfer review/cancellation, virtual-browser WebAuthn provisioning, delegate ticket/receipt verification plus transfer/replay refusal, mobile fit, signed outbound bank-session verification, and keyboard behavior.
- Axe automated checks found no WCAG 2 A/AA or 2.1 AA rule violations in the tested initial states of the four workspaces and policy assistant. This is limited automated coverage, not a complete accessibility conformance assessment.
- `npm audit`: **0 reported vulnerabilities** after overriding the affected transitive KaTeX version. The headless assistant does not use a math renderer.
- Browser security contract: **6 checks passed** (`node scripts/check_browser_security.cjs`) using real WebCrypto/P-256 verification, malformed/expired proofs, customer binding, canonical request hashes and simulated-mode disclosure.
- `node --check app/static/security.js` and `node --check app/static/workspace.js` passed.
- Critical Python syntax/undefined-name check passed: `ruff check app tests --select E9,F63,F7,F82`.
- `git diff --check` passed. Broader repository lint rules include pre-existing style/security warnings and are not claimed clean.

## Covered behavior

Current-utterance evidence binding, stale/missing provider outcomes, mock isolation, typed requests, immutable playback timestamps, unauthorized bank notices, exact beneficiary selection, action tampering, passkey origin/user-verification/customer/expiry/replay checks, atomic repeated transfers, competing balance updates, approval-versus-denial races, preserved-history migration, synthetic delegate holder proofs/scope/revocation/expiry/replay, source ingestion authorization and quarantine, reviewed extractive answers, and served frontend/API contracts.

Virtual authenticators generate real signatures validated by the WebAuthn library; no test-only cryptographic verification bypass exists. Test voice scores are deliberately mocked and clearly separate from model accuracy.

## Remaining external validation

Actual DetectifAI request/response contract, enrollment behavior, score semantics/thresholds, quotas, real-audio accuracy and network latency require supplied credentials and API documentation. Hosted origin/RP settings and a physical browser authenticator require a deployment-specific smoke test. The Chromium tests use an explicit demo mock provider, a virtual authenticator, and disabled STT/TTS providers. They do not establish live microphone/speech-provider performance. Desktop and mobile screenshots were inspected; the remaining live microphone/STT/TTS rehearsal requires configured providers and consented recordings.

Use `docs/SECURITY.md` for the consented held-out evaluation protocol and limitations. No detection benchmark, financial assurance certification, real payment execution or hackathon outcome is asserted.


## Track 3 presentation update (16 October 2026)

Reframed the opening experience around agent trust, renamed Approval center and Trust desk, prioritized signed agent identity and the support delegate, and placed account data/cards in optional simulated banking examples. Updated English call introductions, the independent verifier copy, README, architecture, and presentation guide. Underlying permissions, claims, routes, and authorization checks remain compatible.

Validation: production TypeScript/Vite build passed; all seven Chromium scenarios passed, including virtual passkey enrollment, bounded delegate actions, session proof verification, receipt verification/tamper rejection, mobile navigation, and accessibility checks. Thirteen targeted Python WebSocket/decision regressions and eight real-signature verifier checks passed. Desktop screenshot inspected. These checks do not establish live DetectifAI performance.
