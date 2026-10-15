# Nishabdha: proof before action

Pitch: **A copied voice cannot copy your permissions.** Verify caller evidence, prove the bank agent's application identity, and execute only the authorized action.

## Four-minute presentation

1. **Prove the bank (30s).** Enter the staff key, start an authorized outbound session in Fraud desk, then independently open Customer app and Verify bank session. The signature proves the configured app session, not arbitrary telephone audio. Four separate states show caller evidence, bank identity, permission and outcome.
2. **Attempt impersonation (40s).** Send a consented cloned clip as a new utterance. Inspect actual DetectifAI outputs in Fraud desk. Missing/flagged evidence holds/refuses the action; do not promise a particular detector score.
3. **Authorize a transfer (60s).** With sponsor APIs and an enrolled genuine customer, request a transfer to an exact saved beneficiary. Review source/amount/destination, approve with a passkey and show one debit plus its receipt. Staff assists initial passkey registration. The browser origin must match the configured origin/RP ID.
4. **Attempt substitution (30s).** Run the isolated attack harness. Its approved-transaction tampering scenario changes amount, destination and beneficiary ID after a real test passkey assertion. Each fails with an unchanged balance. This is a simulated gateway test; no public fault-injection endpoint exists.
5. **Let the permitted AI act (45s).** Authorize an assistant; separately Try a transfer and Try reading a balance before creating the ticket. Both fail. Create its ticket, then Replay; no second ticket appears. Authorize a new grant and revoke it before use to show revocation. This is a signed API demonstration with browser speech disclosure, not agent-to-agent telephony.
6. **Verify the proof (35s).** Refresh my decisions, download a receipt and export the bank key separately from the known app. Open the independent verifier, enter the trusted origin and import both files. An altered payload fails verification. Signatures attest to application records, not perfect detection or real settlement.

## Before sponsor access

UI, bank proofs, passkeys, restricted delegate, receipts and isolated tests work without DetectifAI. Successful voice transfers require actual sponsor evidence. Typed turns cannot inherit earlier voice verification; demo mock results cannot authorize transfers. The false-negative test supplies high simulated voice scores but omits customer approval, then checks unchanged balance.

```powershell
.\.venv\Scripts\python.exe scripts/adversarial_demo.py
node scripts/check_receipt_verifier.cjs
```

The harness announces **SIMULATED AUTHORIZATION SCENARIOS — not a DetectifAI accuracy evaluation** and runs nine groups/seventeen parametrized cases in pytest's fresh temporary database. It writes `data/adversarial-results.json` and an HTML report alongside it, suitable for showing the judges. It neither reads nor resets normal app data.

## Memory rehearsal

```powershell
.\.venv\Scripts\python.exe scripts/rehearse.py --duration 1800
.\.venv\Scripts\python.exe scripts/rehearse.py --duration 15 --interval 3 --preload-audio-seconds 1200 --output data/audio-memory-stress.json
```

Both start isolated servers/databases with speech providers disabled. The first maintains three WebSocket sessions with typed turns for thirty minutes. The second rapidly supplies twenty minutes of synthetic silence per session to exercise bounded recording buffers and disconnect cleanup. Accelerated silence is a memory stress test, not realistic speech or model latency. Checks cover unchanged balances, live sessions, health and a 400 MiB process-tree budget. Windows measurements include venv children and peak working sets during recording cleanup; Linux reports sampled RSS.

Call recordings are bounded to twenty minutes. Call end writes existing PCM directly to WAV in a background thread and clears its buffer, avoiding full-call float conversion/copies. Render disables local ML fallbacks before creating providers, under either entrypoint. Local measurements do not establish hosted stability.

## When API access arrives

Configure secrets in the server environment; validate auth, enrollment, audio format, score semantics/direction, thresholds, errors and timeout against the participant contract. `scripts/check_detectifai.py` helps discover the contract; its same-clip check is integration sanity, not accuracy evaluation.

Use disjoint consented tuning/evaluation clips: genuine, wrong-speaker, cloned, partial manipulation, noisy/compressed and multilingual. Record counts, audio hashes, provider/version, both scores/statuses, capture transport, gateway outcome, actual mutations and end-to-end latency. Separate real observations from fault injection/backups. Do not infer word-level manipulation location from chunk scores.

Free Render state and signing keys can disappear after restart/deploy. Rehearse provisioning at the exact deployed origin; retain exported public keys for historical receipts and keep a local demo backup.
