# Deploy Nishabdha

Nishabdha is a hackathon prototype with simulated banking only. It has no real payment rails. Do not use it for real financial or identity decisions.

## Render preview

The repository includes `render.yaml` for a one-process Docker web service. It is configured as a UI/demo preview: speech recognition and the LLM are disabled, and the UI uses the explicitly disclosed demo voice mock when DetectifAI is not configured. Mock evidence cannot authorize a transfer. The free Render plan is suitable only for a temporary, non-production preview:

- It sleeps after inactivity and can take about a minute to wake.
- Its filesystem is ephemeral. Demo accounts, passkey registrations, approvals, receipts, uploaded audio, and the bank signing key can be reset when the service sleeps, restarts, or redeploys.
- Free services cannot attach persistent disks. A paid service with a persistent disk is needed to preserve the app's SQLite state and signing key across restarts. The SQLite app should remain a single process.

To create the preview, sign in to Render, create a Blueprint from `aithal007/Nishabdha`, and select the `master` branch. Review the free instance plan, then set the app's fixed public origin after Render assigns its hostname:

```text
BANK_ORIGIN=https://<your-render-hostname>
WEBAUTHN_RP_ID=<your-render-hostname>
```

Set these before enrolling or using passkeys. They must match the browser's HTTPS origin and hostname exactly. Do not use `localhost` in a hosted service.

## Provider configuration

The preview can load without vendor credentials, but it will not run live speech recognition, LLM responses, or sponsor verification. For a live voice demo, configure provider settings in Render's dashboard, never in Git:

- `DETECTIFAI_API_KEY` and `DETECTIFAI_BASE_URL`, plus the endpoint/field settings from the sponsor's actual API contract. The current adapter defaults are examples and must be checked against that contract.
- `GROQ_API_KEY` if enabling Groq speech-to-text and language features; change `STT_PROVIDER` and `LLM_PROVIDER` from `none` only after adding the key.
- Keep the generated `STAFF_API_KEY` and `AUDIT_HMAC_SECRET`; retrieve the staff key from the host's secret settings and share it only with the demo operator.

Without DetectifAI, voice verification is unavailable or degraded and voice-initiated transfers must remain held. Do not present mock/local checks as sponsor verification. A successful UI health check alone does not prove provider integration.

## Before sharing the URL

1. Confirm `/health` is healthy and the UI clearly identifies simulated banking and provider status.
2. Set `BANK_ORIGIN` and `WEBAUTHN_RP_ID` to the assigned HTTPS origin.
3. Verify DetectifAI enrollment and checks with consented test clips. Confirm provider results and reasons in the fraud desk.
4. Register a test customer passkey and verify the exact-action approval flow. Test a denied transfer and repeated request; balances must not change or debit twice.
5. Rehearse the signed bank-session and one-ticket delegate flows. Confirm the delegate transfer is refused.
6. On a free ephemeral instance, rehearse after a sleep/restart too: passkeys and demo state may be lost. Do not make persistence or availability claims based on this preview.

For the security model, supported endpoints, limits and evaluation requirements, see [docs/SECURITY.md](docs/SECURITY.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), and [docs/VALIDATION.md](docs/VALIDATION.md).
