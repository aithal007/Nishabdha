# Frontend design and integration

The interface uses a React/Vite shell, source-owned shadcn/ui-style Radix controls, Tailwind v4, locally bundled Inter, Lucide icons, and a headless CopilotKit policy assistant. FastAPI serves the compiled assets; there is no extra Node runtime in deployment.

## Product and design brief

The audience consists of a caller asking for banking help, a customer reviewing account permissions, and staff investigating suspicious activity. The interface should make the current task clear, put exact-action consent before execution, and distinguish unavailable evidence from a confirmed attack.

The desktop layout has a navy navigation rail, a pale workspace, white content panels, and a restrained teal/green action palette. Amber indicates uncertainty; red is reserved for adverse signals and destructive actions. Typography uses Inter with a compact but explicit hierarchy. The three-step assurance strip explains caller evidence, customer consent, and controlled execution; it does not pretend to be a live verification status. Health and mock-mode displays come from the backend.

The four workspaces are:

- **Voice workspace:** conversation transcript, microphone, language, turn completion, typed fallback, and consented audio-file testing.
- **Customer app:** real simulated-account data, incoming approvals/activity, an exact-transfer review dialog, staff-assisted passkey setup, bank-session proof, limited delegate controls, voice enrollment, and card freezing.
- **Fraud desk:** session inbox, review queue, signal history, decision timeline, evidence report, audit verification, and termination controls. Staff authentication remains mandatory server-side.
- **Knowledge library:** reviewed extractive answers, source provenance, staff research/scraping, and explicit quarantine inspection/approval. It does not automatically publish retrieved pages.

## Component ownership and build

`frontend/src/App.tsx` owns navigation, the responsive shell, the policy sheet, and the transaction-review dialog. `frontend/src/components/ui/` owns local Radix wrappers following the shadcn source model. `frontend/src/styles.css` provides the new theme. `workspace-base.css` contains inherited workspace primitives underneath that theme.

The existing audio, enrollment, customer-notification, and fraud-desk controller has been extracted into `app/static/workspace.js`. It owns the stable DOM inside `frontend/src/workspace.html`. React treats this workspace as an opaque, memoized view, so state updates to navigation or dialogs cannot recreate an active microphone/session panel. The controller and `security.js` load once after those nodes exist. This transition keeps working audio and security flows while letting the shell and new features use React. Future panel migrations should replace both a panel and its controller handlers together; do not let React and imperative code write the same subtree.

The browser dispatches `nishabdha:navigate`; the workspace controller emits `nishabdha:tab` after changing its active panel. Passkey approval calls `window.confirmTransaction` to show the exact persisted recipient, account, and amount before starting the verified WebAuthn ceremony. Cancelling that review grants no authority. Backend enforcement is unchanged.

From the repository root:

```powershell
npm ci --prefix frontend
npm run build --prefix frontend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Open `http://localhost:8000`, matching `BANK_ORIGIN` and the relying-party ID. Built assets are committed under `app/static/ui/` so a Python-only deployment can serve the UI. Rebuild after any frontend source change. A development Vite proxy is available through `npm run dev --prefix frontend`; passkeys require the backend origin configuration to match the actual browser origin, so rehearse security flows through FastAPI's built UI.

## CopilotKit backend boundary

The headless CopilotKit React hook connects an AG-UI `HttpAgent` to `POST /api/copilot/policy`. The prototype registers that public policy agent locally rather than running an additional CopilotRuntime service. This is a demo integration, not a production CopilotRuntime deployment.

The endpoint accepts bounded conversation messages and streams run/message events as SSE. It selects the latest user question and calls the same reviewed extractive lookup used by the knowledge library. It ignores client system instructions, tool descriptions, shared state, and alleged approvals. The browser renders returned text as plain text. No customer token, staff key, account state, transcript from a bank call, or mutation tool is sent to the assistant. It can explain a policy or abstain; it cannot perform an account operation.

## Validation

`npm run build --prefix frontend` checks TypeScript and builds the production assets. Browser scenarios live in `frontend/tests/`; Playwright starts an isolated FastAPI demo server on port 8010 with test-only data and explicit mock disclosure. It checks navigation, a real WebSocket typed turn, policy streaming, transfer-review cancellation, browser WebAuthn through a virtual authenticator, the delegate's valid ticket and denied transfer/replay, and mobile fit. These are application-flow checks, not a physical authenticator rehearsal or real DetectifAI detection benchmark.

See [`VALIDATION.md`](VALIDATION.md) for recorded results and [`../frontend/THIRD_PARTY_NOTICES.md`](../frontend/THIRD_PARTY_NOTICES.md) for the requested repository references and license notice.
