import { defineConfig } from "@playwright/test";
import { resolve } from "node:path";
export default defineConfig({
  testDir: "./tests",
  timeout: 45000,
  fullyParallel: false,
  use: {
    baseURL: "http://localhost:8010",
    viewport: { width: 1440, height: 1000 },
    headless: true,
  },
  reporter: "list",
  webServer: {
    command: `"${resolve(process.platform === "win32" ? "../.venv/Scripts/python.exe" : "../.venv/bin/python")}" -m uvicorn app.main:app --app-dir .. --host 127.0.0.1 --port 8010`,
    url: "http://localhost:8010/health",
    reuseExistingServer: false,
    env: {
      APP_ENV: "demo",
      VOICE_PRIMARY: "mock",
      VOICE_FALLBACK: "none",
      STT_PROVIDER: "none",
      STT_FALLBACK: "none",
      TTS_PROVIDER: "none",
      LLM_PROVIDER: "none",
      STAFF_API_KEY: "staff-preview",
      AUDIT_HMAC_SECRET: "e2e-audit-fixture",
      BANK_ORIGIN: "http://localhost:8010",
      WEBAUTHN_RP_ID: "localhost",
      DATA_DIR: resolve(".e2e-data"),
    },
  },
});
