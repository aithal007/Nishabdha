import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { readFile } from "node:fs/promises";

test("navigation, customer data and live typed call retain their contracts", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Voice workspace" }),
  ).toBeEnabled();
  await expect(
    page.getByRole("heading", { name: "Verify the caller. Prove the agent." }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/voice-desktop.png",
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Approval center", exact: true })
    .click();
  await expect(page.locator("#pName")).toHaveText("Ananya Rao");
  await page
    .getByText("Optional sensitive-action example: simulated banking", {
      exact: true,
    })
    .click();
  await expect(page.locator("#pBalance")).toContainText("Savings");
  await page.screenshot({
    path: "test-results/customer-desktop.png",
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Voice workspace", exact: true })
    .click();
  await page.locator("#typeText").fill("What's my balance?");
  await page.locator("#typeBtn").click();
  await expect(page.locator("#callState")).toContainText("Connected", {
    timeout: 15000,
  });
  await expect(page.locator("#chat")).toContainText("What's my balance?");
  await page.locator("#endBtn").click();
  await expect(page.locator("#callState")).toHaveText("Not connected");
  expect(errors).toEqual([]);
});

test("CopilotKit receives reviewed answers through the AG-UI backend", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page.getByRole("button", { name: "Open policy assistant" }).click();
  const prompt = page.getByRole("button", {
    name: "How do I approve a transfer with a passkey?",
  });
  await expect(prompt).toBeEnabled({ timeout: 20000 });
  await prompt.click();
  await expect(page.locator(".policy-message.assistant")).toContainText(
    "every transfer requires a passkey",
    { timeout: 15000 },
  );
  await expect(page.locator(".policy-message.assistant")).toContainText(
    "Reviewed source:",
  );
  await page.screenshot({ path: "test-results/copilot-desktop.png" });
  await page.getByRole("button", { name: "Close dialog" }).click();
  expect(errors).toEqual([]);
});

test("transaction review shows exact frozen details and cancellation resolves", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Voice workspace", exact: true }),
  ).toBeEnabled();
  await page.evaluate(() => {
    (window as unknown as { review: Promise<boolean> }).review =
      window.confirmTransaction!({
        amount_paise: 125050,
        payee_name: "Amma",
        destination_last4: "7788",
        source_last4: "4411",
        currency: "INR",
      });
  });
  await expect(page.getByRole("alertdialog")).toBeVisible();
  await expect(page.getByRole("alertdialog")).toContainText("1,250.50");
  await expect(page.getByRole("alertdialog")).toContainText("7788");
  await page.getByRole("button", { name: "Cancel transfer" }).click();
  expect(
    await page.evaluate(
      () => (window as unknown as { review: Promise<boolean> }).review,
    ),
  ).toBe(false);
});

test("real browser WebAuthn registration and one-use delegate demo", async ({
  page,
  context,
}) => {
  const device = await context.newCDPSession(page);
  await device.send("WebAuthn.enable");
  await device.send("WebAuthn.addVirtualAuthenticator", {
    options: {
      protocol: "ctap2",
      transport: "internal",
      hasResidentKey: true,
      hasUserVerification: true,
      isUserVerified: true,
      automaticPresenceSimulation: true,
    },
  });
  page.on("dialog", (dialog) => dialog.accept());
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Approval center", exact: true }),
  ).toBeEnabled();
  await page.locator(".staff-access summary").click();
  await page.locator("#staffKey").fill("staff-preview");
  await page.locator("#staffKey").press("Tab");
  await page
    .getByRole("button", { name: "Approval center", exact: true })
    .click();
  await page.locator("#provisionPasskey").click();
  await expect(page.locator("#securityStatus")).toContainText(
    "Passkey registered",
    { timeout: 20000 },
  );
  await page.locator("#delegateDemo").click();
  await expect(page.locator("#securityStatus")).toContainText(
    "Assistant authorized",
    { timeout: 15000 },
  );
  await expect(page.locator("#delegatePermission")).toContainText(
    "Cannot read balances or move money",
  );
  await page.locator("#delegateTransfer").click();
  await expect(page.locator("#delegateTranscript")).toContainText(
    "Refused: action outside delegated scope",
  );
  await page.locator("#delegateRead").click();
  await expect(page.locator("#delegateTranscript")).toContainText(
    "Please read my customer's balance",
  );
  await page.locator("#runDelegate").click();
  await expect(page.locator("#securityStatus")).toContainText(
    "receipt verified",
    { timeout: 15000 },
  );
  await page.locator("#delegateReplay").click();
  await expect(page.locator("#delegateTranscript")).toContainText(
    "Replay refused",
  );
  const [receiptDownload] = await Promise.all([
    page.waitForEvent("download"),
    page.locator("#decisionList button").first().click(),
  ]);
  const receiptPath = await receiptDownload.path();
  const [keyDownload] = await Promise.all([
    page.waitForEvent("download"),
    page.locator("#downloadBankKey").click(),
  ]);
  const keyPath = await keyDownload.path();
  const verifier = await context.newPage();
  await verifier.goto("/static/receipt-verifier.html");
  await verifier.locator("#expectedIssuer").fill("http://localhost:8010");
  await verifier.locator("#trustedKeyFile").setInputFiles(keyPath!);
  await verifier.locator("#receiptFile").setInputFiles(receiptPath!);
  const network: string[] = [];
  verifier.on("request", (request) => network.push(request.url()));
  await verifier
    .getByRole("button", { name: "Verify signature and record" })
    .click();
  await expect(verifier.locator("#verifyStatus")).toContainText(
    "Signature verified",
  );
  expect(network).toEqual([]);
  const tampered = JSON.parse(await readFile(receiptPath!, "utf8"));
  tampered.payload.outcome = "executed_by_attacker";
  await verifier.locator("#receiptFile").setInputFiles({
    name: "tampered.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(tampered)),
  });
  await verifier
    .getByRole("button", { name: "Verify signature and record" })
    .click();
  await expect(verifier.locator("#verifyStatus")).toContainText(
    "Verification failed",
  );
  await verifier.close();
  await page.locator("#delegateDemo").click();
  await expect(page.locator("#runDelegate")).toBeVisible();
  await page.locator("#revokeDelegate").click();
  await expect(page.locator("#securityStatus")).toContainText(
    "permission revoked",
  );
  await expect(page.locator("#runDelegate")).toBeHidden();
  expect(
    await page.evaluate(() => localStorage.getItem("staffKey")),
  ).toBeNull();
  await page.getByRole("button", { name: "Trust desk", exact: true }).click();
  await expect(page.locator("#dTickets")).toContainText(
    "Authorized AI support ticket",
  );
  await page.screenshot({
    path: "test-results/fraud-desk.png",
    fullPage: true,
  });
});

test("mobile navigation and policy screen fit the viewport", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "Open navigation" }).click();
  await page
    .getByRole("button", { name: "Approval center", exact: true })
    .click();
  await expect(page.locator("#pName")).toHaveText("Ananya Rao");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/customer-mobile.png",
    fullPage: true,
    animations: "disabled",
  });
  await page.getByRole("button", { name: "Open navigation" }).click();
  await page
    .getByRole("button", { name: "Knowledge library", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Good answers start with evidence." }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("staff outbound session proof verifies in the customer app", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Trust desk", exact: true }),
  ).toBeEnabled();
  await page.locator(".staff-access summary").click();
  await page.locator("#staffKey").fill("staff-preview");
  await page.locator("#staffKey").press("Tab");
  await page.getByRole("button", { name: "Trust desk", exact: true }).click();
  await page.locator(".outbound-control summary").click();
  await page.locator("#dOutbound").click();
  await expect(page.locator("#callState")).toContainText("Connected");
  await page
    .getByRole("button", { name: "Approval center", exact: true })
    .click();
  await page.locator("#pCheckBank").click();
  await expect(page.locator("#securityStatus")).toContainText(
    "Verified AI agent session",
  );
  await page
    .getByRole("button", { name: "Voice workspace", exact: true })
    .click();
  await page.locator("#endBtn").click();
  await expect(page.locator("#callState")).toHaveText("Not connected");
});

test("workspace accessibility and mobile keyboard navigation", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Voice workspace", exact: true }),
  ).toBeEnabled();
  const audit = async (view: string) => {
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
      .analyze();
    expect(
      results.violations.map((v) => ({
        id: v.id,
        nodes: v.nodes.map((n) => ({
          target: n.target,
          summary: n.failureSummary,
        })),
      })),
      view,
    ).toEqual([]);
  };
  for (const name of [
    "Voice workspace",
    "Approval center",
    "Trust desk",
    "Knowledge library",
  ]) {
    await page.getByRole("button", { name, exact: true }).click();
    await audit(name);
  }
  await page.getByRole("button", { name: "Open policy assistant" }).click();
  await expect(
    page.getByRole("button", {
      name: "How do I approve a transfer with a passkey?",
    }),
  ).toBeEnabled();
  await audit("Policy assistant");
  await page.getByRole("button", { name: "Close dialog" }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Open navigation" }).click();
  await expect(
    page.getByRole("dialog", { name: "Workspace navigation" }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("button", { name: "Open navigation" }),
  ).toBeFocused();
});
