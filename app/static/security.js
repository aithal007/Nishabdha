/* Browser WebAuthn; the relying-party origin and all approval bindings are checked server-side. */
const Security = {
  decode(s) {
    return Uint8Array.from(
      atob(
        s.replace(/-/g, "+").replace(/_/g, "/") +
          "=".repeat((4 - (s.length % 4)) % 4),
      ),
      (c) => c.charCodeAt(0),
    );
  },
  encode(b) {
    return btoa(String.fromCharCode(...new Uint8Array(b)))
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=/g, "");
  },
  status(s) {
    $("securityStatus").textContent = s;
  },
  options(o, registration = false) {
    o.challenge = this.decode(o.challenge);
    if (registration) o.user.id = this.decode(o.user.id);
    for (const c of o.allowCredentials || o.excludeCredentials || [])
      c.id = this.decode(c.id);
    return o;
  },
  serialize(c) {
    const response = { clientDataJSON: this.encode(c.response.clientDataJSON) };
    for (const k of [
      "attestationObject",
      "authenticatorData",
      "signature",
      "userHandle",
    ])
      if (c.response[k]) response[k] = this.encode(c.response[k]);
    if (c.response.getTransports)
      response.transports = c.response.getTransports();
    return {
      id: c.id,
      rawId: this.encode(c.rawId),
      type: c.type,
      response,
      clientExtensionResults: c.getClientExtensionResults(),
    };
  },
  async ceremony(body) {
    const p = await api("/api/app/passkeys/options", {
      method: "POST",
      headers: appH(),
      body,
    });
    const credential = await navigator.credentials.get({
      publicKey: this.options(p.options),
    });
    return api("/api/app/passkeys/verify", {
      method: "POST",
      headers: appH(),
      body: {
        approval_id: p.approval_id,
        credential: this.serialize(credential),
      },
    });
  },
  async approve(stepup_id) {
    const pending = await api("/api/app/pending", { headers: appH() });
    const action = pending.stepups.find((x) => x.stepup_id === stepup_id);
    if (!action) throw new Error("Approval expired or already resolved.");
    if (!action.requires_passkey)
      return api(`/api/app/stepups/${stepup_id}/approve`, {
        method: "POST",
        headers: appH(),
      });
    const t = action.transaction;
    const accepted = window.confirmTransaction
      ? await window.confirmTransaction(t)
      : confirm(
          `Approve INR ${(t.amount_paise / 100).toFixed(2)} to ${t.payee_name}, account ending ${t.destination_last4}, from account ending ${t.source_last4}?`,
        );
    if (!accepted) throw new Error("Approval cancelled.");
    return this.ceremony({ purpose: "transfer", stepup_id });
  },
  async provision() {
    const p = await api(
      `/api/admin/customers/${encodeURIComponent(cust().id)}/passkeys/options`,
      { method: "POST", headers: staffH() },
    );
    const credential = await navigator.credentials.create({
      publicKey: this.options(p.options, true),
    });
    await api("/api/app/passkeys/verify", {
      method: "POST",
      headers: appH(),
      body: {
        approval_id: p.approval_id,
        credential: this.serialize(credential),
      },
    });
    this.status("Passkey registered. Transfers now require your confirmation.");
  },
  async verifyJwt(token, jwk, expected = {}) {
    const parts = token.split(".");
    if (parts.length !== 3) throw new Error("Invalid signed record");
    const header = JSON.parse(new TextDecoder().decode(this.decode(parts[0])));
    if (header.alg !== "ES256" || header.kid !== jwk.kid)
      throw new Error("Unexpected signing key");
    const key = await crypto.subtle.importKey(
      "jwk",
      jwk,
      { name: "ECDSA", namedCurve: "P-256" },
      false,
      ["verify"],
    );
    const valid = await crypto.subtle.verify(
      { name: "ECDSA", hash: "SHA-256" },
      key,
      this.decode(parts[2]),
      new TextEncoder().encode(parts[0] + "." + parts[1]),
    );
    const payload = JSON.parse(new TextDecoder().decode(this.decode(parts[1])));
    if (
      !valid ||
      !Number.isFinite(payload.exp) ||
      !Number.isFinite(payload.iat) ||
      payload.iat > Date.now() / 1000 + 5 ||
      payload.exp <= Date.now() / 1000 ||
      Object.entries(expected).some(([k, v]) => payload[k] !== v)
    )
      throw new Error("Session proof invalid or expired");
    return payload;
  },
  async checkBank() {
    const notice = await api("/api/app/bank-call", { headers: appH() });
    if (!notice.genuine_bank_call) {
      $("authorityBank").textContent =
        "No authorized outbound bank session to verify.";
      this.status(
        "No active authorized outbound bank session. Do not rely on a caller's code.",
      );
      return;
    }
    const keys = await api("/.well-known/jwks.json");
    if (keys.issuer !== location.origin)
      throw new Error(
        "Bank origin configuration does not match this application.",
      );
    const signed = await api(
      `/api/app/bank-call/${encodeURIComponent(notice.notice_id)}/proof`,
      { headers: appH() },
    );
    const p = await this.verifyJwt(signed.proof, keys.keys[0], {
      iss: location.origin,
      aud: cust().id,
      call_id: notice.call_id,
      notice_id: notice.notice_id,
      type: "bank-session",
      agent_type: "ai",
    });
    $("authorityBank").textContent =
      `Verified ${p.iss} · disclosed AI · session ${p.call_id}`;
    clearTimeout(this.bankProofExpiry);
    this.bankProofExpiry = setTimeout(
      () => {
        $("authorityBank").textContent =
          "Bank session proof expired. Verify the session again.";
      },
      Math.max(0, p.exp * 1000 - Date.now()),
    );
    this.status(
      `Verified AI bank session ${p.call_id}: ${p.reason}. This verifies the app session, not arbitrary phone audio.`,
    );
  },
  canonical(x) {
    if (Array.isArray(x))
      return "[" + x.map((v) => this.canonical(v)).join(",") + "]";
    if (x && typeof x === "object")
      return (
        "{" +
        Object.keys(x)
          .sort()
          .map((k) => JSON.stringify(k) + ":" + this.canonical(x[k]))
          .join(",") +
        "}"
      );
    return JSON.stringify(x);
  },
  async hash(x) {
    return Array.from(
      new Uint8Array(
        await crypto.subtle.digest(
          "SHA-256",
          new TextEncoder().encode(this.canonical(x)),
        ),
      ),
    )
      .map((v) => v.toString(16).padStart(2, "0"))
      .join("");
  },
  async authorizeDelegate() {
    const key = await crypto.subtle.generateKey(
      { name: "ECDSA", namedCurve: "P-256" },
      true,
      ["sign", "verify"],
    );
    const holder_jwk = await crypto.subtle.exportKey("jwk", key.publicKey);
    const binding = await api("/api/app/agents/delegation-binding", {
      method: "POST",
      headers: appH(),
      body: { holder_jwk },
    });
    if (
      !confirm(
        "Authorize this disclosed AI assistant to create ONE support ticket within ten minutes? It cannot move money or read your balance.",
      )
    )
      return;
    const approval = await this.ceremony({
      purpose: "delegation",
      binding_hash: binding.binding_hash,
    });
    const grant = await api("/api/app/agents/grants", {
      method: "POST",
      headers: appH(),
      body: { holder_jwk, approval_id: approval.approval_id },
    });
    this.delegate = { key, grant, customer_id: cust().id };
    $("delegateTranscript").replaceChildren();
    this.delegateTurn(
      "BANK",
      "Permission granted for one support ticket. Voice disclosure alone grants no access.",
    );
    $("delegatePermission").hidden = false;
    $("delegateExpiry").textContent =
      `Expires ${new Date(grant.expires_at).toLocaleTimeString()} · 1 use remaining`;
    $("runDelegate").textContent = "Create the authorized support ticket";
    $("delegateTransfer").hidden = false;
    $("delegateRead").hidden = false;
    $("delegateReplay").hidden = true;
    this.status(
      "Assistant authorized for one ticket. Run the demo or revoke the permission.",
    );
    $("runDelegate").hidden = false;
    $("revokeDelegate").hidden = false;
  },
  async delegateRequest(action, subject) {
    const d = this.delegate;
    if (!d || d.customer_id !== cust().id)
      throw new Error("Authorize an assistant for this customer first.");
    const nonce = await api(`/api/agents/grants/${d.grant.grant_id}/nonce`, {
      method: "POST",
    });
    const now = Math.floor(Date.now() / 1000);
    const header = { alg: "ES256", typ: "JWT" };
    const claims = {
      aud: nonce.audience,
      iat: now,
      exp: now + 60,
      jti: crypto.randomUUID(),
      grant_id: d.grant.grant_id,
      nonce: nonce.nonce,
      body_hash: await this.hash({ action, subject }),
    };
    const part = (x) =>
      this.encode(new TextEncoder().encode(JSON.stringify(x)));
    const data = part(header) + "." + part(claims);
    const sig = await crypto.subtle.sign(
      { name: "ECDSA", hash: "SHA-256" },
      d.key.privateKey,
      new TextEncoder().encode(data),
    );
    const body = { proof: data + "." + this.encode(sig), action, subject };
    const path = `/api/agents/grants/${d.grant.grant_id}/execute`;
    const result = await api(path, { method: "POST", body });
    return { result, path, body };
  },
  async runDelegate() {
    this.delegateTurn(
      "AI ASSISTANT",
      "I am a disclosed AI assistant. Please create my customer's support ticket.",
    );
    if (window.speechSynthesis)
      speechSynthesis.speak(
        new SpeechSynthesisUtterance(
          "I am a disclosed AI support assistant. I can open one ticket, but I cannot transfer money.",
        ),
      );
    const sent = await this.delegateRequest(
      "support_ticket.create",
      "Please help with my card",
    );
    this.delegate.lastSent = sent;
    const jwks = await api("/.well-known/jwks.json");
    const parts = sent.result.receipt.split(".");
    if (parts.length !== 3) throw new Error("Invalid ticket receipt");
    const header = JSON.parse(new TextDecoder().decode(this.decode(parts[0])));
    const payload = JSON.parse(new TextDecoder().decode(this.decode(parts[1])));
    const expected = {
      iss: location.origin,
      ticket_id: sent.result.ticket_id,
      grant_id: this.delegate.grant.grant_id,
      customer_id: cust().id,
      action: sent.body.action,
      subject: sent.body.subject,
      status: "executed",
      agent_type: "delegated_synthetic",
    };
    if (
      header.alg !== "ES256" ||
      header.kid !== jwks.keys[0].kid ||
      Object.entries(expected).some(([k, v]) => payload[k] !== v)
    )
      throw new Error("Ticket receipt does not match this request");
    const publicKey = await crypto.subtle.importKey(
      "jwk",
      jwks.keys[0],
      { name: "ECDSA", namedCurve: "P-256" },
      false,
      ["verify"],
    );
    const intact = await crypto.subtle.verify(
      { name: "ECDSA", hash: "SHA-256" },
      publicKey,
      this.decode(parts[2]),
      new TextEncoder().encode(parts[0] + "." + parts[1]),
    );
    if (!intact) throw new Error("Ticket receipt signature failed");
    this.delegateTurn(
      "BANK",
      `Ticket ${sent.result.ticket_id} created. Signed receipt verified. The one-use permission is consumed.`,
    );
    $("delegateReplay").hidden = false;
    $("delegateExpiry").textContent =
      "0 uses remaining. The signed permission cannot be reused.";
    this.status(
      `AI ticket ${sent.result.ticket_id} created; receipt verified. Try replay separately to inspect the refusal.`,
    );
    $("runDelegate").hidden = true;
    await this.loadDecisions();
  },
  delegateTurn(who, text) {
    const row = document.createElement("div");
    row.className = "delegate-turn";
    row.textContent = `${who}: ${text}`;
    $("delegateTranscript").append(row);
    row.scrollIntoView({ block: "nearest" });
  },
  async attemptDelegate(action) {
    this.delegateTurn(
      "AI ASSISTANT",
      action === "transfer_funds"
        ? "Please transfer INR 500."
        : "Please read my customer's balance.",
    );
    try {
      await this.delegateRequest(
        action,
        "Demonstration of a request outside the grant",
      );
      throw new Error(
        "Unexpected authorization: inspect the gateway before continuing.",
      );
    } catch (e) {
      if (e.status !== 403) throw e;
      this.delegateTurn(
        "BANK",
        `Refused: ${e.message}${e.decisionId ? " · decision " + e.decisionId : ""}. No money or account data released.`,
      );
    }
    await this.loadDecisions();
  },
  async replayDelegate() {
    const d = this.delegate;
    if (!d || d.customer_id !== cust().id || !d.lastSent)
      throw new Error("Create a ticket for this customer first.");
    this.delegateTurn(
      "AI ASSISTANT",
      "Resending the exact same signed ticket request.",
    );
    try {
      await api(d.lastSent.path, { method: "POST", body: d.lastSent.body });
      throw new Error("Unexpected replay acceptance.");
    } catch (e) {
      if (e.status !== 403) throw e;
      this.delegateTurn(
        "BANK",
        `Replay refused: ${e.message}. No second ticket created.`,
      );
    }
    await this.loadDecisions();
  },
  download(name, value) {
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = name;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  },
  async loadDecisions() {
    const customerId = cust().id;
    const result = await api("/api/app/decisions", { headers: appH() });
    if (cust().id !== customerId) return;
    const box = $("decisionList");
    box.replaceChildren();
    if (!result.decisions.length)
      box.textContent = "No decisions recorded for this customer yet.";
    for (const record of result.decisions) {
      const item = document.createElement("div");
      item.className = "decision-item";
      const text = document.createElement("span");
      text.textContent = `${record.payload.outcome} · ${record.payload.operation} · ${record.payload.message} [${record.payload.mode}]`;
      const button = document.createElement("button");
      button.className = "ghost";
      button.textContent = "Download signed decision";
      button.onclick = () =>
        this.download(`${record.payload.decision_id}.json`, record);
      item.append(text, button);
      box.append(item);
    }
  },
  async revokeDelegate() {
    if (!this.delegate || this.delegate.customer_id !== cust().id)
      throw new Error("No assistant for this customer.");
    await api(`/api/app/agents/grants/${this.delegate.grant.grant_id}/revoke`, {
      method: "POST",
      headers: appH(),
    });
    this.delegate = null;
    for (const id of [
      "delegateTransfer",
      "delegateRead",
      "delegateReplay",
      "delegatePermission",
    ])
      $(id).hidden = true;
    this.delegateTurn(
      "BANK",
      "Permission revoked. Subsequent signed requests will be refused.",
    );
    $("runDelegate").hidden = true;
    $("revokeDelegate").hidden = true;
    this.status("Assistant permission revoked.");
  },
};
$("provisionPasskey").onclick = () =>
  Security.provision().catch((e) => Security.status(e.message));
$("pCheckBank").onclick = () =>
  Security.checkBank().catch((e) => Security.status(e.message));
$("delegateDemo").onclick = () =>
  Security.authorizeDelegate().catch((e) => Security.status(e.message));
$("runDelegate").onclick = () =>
  Security.runDelegate().catch((e) => Security.status(e.message));
$("revokeDelegate").onclick = () =>
  Security.revokeDelegate().catch((e) => Security.status(e.message));
$("delegateTransfer").onclick = () =>
  Security.attemptDelegate("transfer_funds").catch((e) =>
    Security.status(e.message),
  );
$("delegateRead").onclick = () =>
  Security.attemptDelegate("balance").catch((e) => Security.status(e.message));
$("delegateReplay").onclick = () =>
  Security.replayDelegate().catch((e) => Security.status(e.message));
$("loadDecisions").onclick = () =>
  Security.loadDecisions().catch((e) => Security.status(e.message));
$("downloadBankKey").onclick = async () => {
  try {
    const jwks = await api("/.well-known/jwks.json");
    if (jwks.issuer !== location.origin)
      throw new Error("Bank origin mismatch");
    Security.download("trusted-bank-key.json", {
      issuer: location.origin,
      keys: jwks.keys,
    });
  } catch (e) {
    Security.status(e.message);
  }
};
$("customer").addEventListener?.("change", () => {
  clearTimeout(Security.bankProofExpiry);
  Security.delegate = null;
  for (const id of [
    "runDelegate",
    "revokeDelegate",
    "delegateTransfer",
    "delegateRead",
    "delegateReplay",
    "delegatePermission",
  ])
    $(id).hidden = true;
  $("delegateTranscript").replaceChildren();
  $("decisionList").replaceChildren();
  $("authorityBank").textContent = "Not verified for this customer.";
  Security.status(
    "Customer changed. Verify this customer's session and permissions separately.",
  );
});
(async () => {
  try {
    const h = await api("/api/health");
    const chain = h.voice?.chain || h.chain || h.voice_engine || [];
    if (chain.includes("mock")) {
      const target = document.getElementById?.("voiceModeBanner");
      const banner = target || document.createElement("div");
      banner.hidden = false;
      if (!target) banner.className = "notif alert";
      banner.textContent =
        "SIMULATED VOICE RESULTS — test/demo engine active. This is not live deepfake detection.";
      if (!target) document.body.prepend(banner);
    }
  } catch {}
})();
