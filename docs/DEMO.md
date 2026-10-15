# Nishabdha: Unclone Agents

Pitch: **AI voice agents that verify you, prove themselves, and act only within your permission.** A copied voice cannot copy your permissions. Banking is an optional sensitive-action example, not the product category.

## Four-minute presentation

1. **Prove the agent (40s).** Start a staff-authorized outbound session in Trust desk. Independently open Approval center and select Verify agent session. The signed record identifies the application session and disclosed AI status; it does not authenticate arbitrary telephone audio.
2. **Verify the caller (45s).** Send a consented genuine or cloned utterance. Show speaker match and authenticity separately, using actual DetectifAI outputs when available. Missing or flagged required evidence holds/refuses protected actions. Do not promise a detector score.
3. **Let an authorized AI act (65s).** In Approval center, authorize the disclosed support assistant with a passkey. Its permission card allows one ticket for ten minutes. Try the out-of-scope transfer and balance requests: both fail. Create the ticket, then replay: no second ticket. A fresh grant can be revoked before use. Browser speech is a disclosure alongside signed API requests, not agent-to-agent telephony.
4. **Verify the decision (45s).** Download a decision receipt, obtain the service public key separately from the known app, and open the independent verifier. Check the signed record locally; tampering fails. The signature attests to the application's record, not detector accuracy.
5. **Optional sensitive-action challenge (45s).** Expand the simulated banking example. With sponsor evidence, approve one exact transfer using a passkey and show one debit. Use the isolated harness to demonstrate amount/recipient substitution rejection. Clearly announce simulated tests; there is no public force-pass endpoint. This is the authorization stress test, not the opening pitch.

## Before sponsor access

UI, agent-session proofs, passkeys, restricted delegate, receipts and isolated tests work without DetectifAI. Successful voice transfers require actual sponsor evidence. Typed turns cannot inherit earlier voice verification; demo mock results cannot authorize transfers. The false-negative test supplies high simulated voice scores but omits customer approval, then checks unchanged balance.

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
