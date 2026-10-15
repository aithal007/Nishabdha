/* Trust comes from the separately configured bank key, never from receipt headers. */
globalThis.NishabdhaReceipt = {
  canonical(value) {
    if (Array.isArray(value))
      return "[" + value.map((v) => this.canonical(v)).join(",") + "]";
    if (value && typeof value === "object")
      return (
        "{" +
        Object.keys(value)
          .sort()
          .map((k) => JSON.stringify(k) + ":" + this.canonical(value[k]))
          .join(",") +
        "}"
      );
    return JSON.stringify(value);
  },
  decode(value) {
    if (!/^[A-Za-z0-9_-]+$/.test(value))
      throw new Error("Malformed signature encoding");
    return Uint8Array.from(
      atob(
        value.replace(/-/g, "+").replace(/_/g, "/") +
          "=".repeat((4 - (value.length % 4)) % 4),
      ),
      (c) => c.charCodeAt(0),
    );
  },
  async verify(record, trust, issuer) {
    if (!issuer || new URL(issuer).origin !== issuer || trust.issuer !== issuer)
      throw new Error(
        "Expected bank origin must match your separately trusted key file",
      );
    if (
      !record ||
      typeof record.signature !== "string" ||
      record.signature.length > 65536
    )
      throw new Error("Invalid signed decision record");
    const parts = record.signature.split(".");
    if (parts.length !== 3) throw new Error("Invalid signed record");
    const parse = (value) =>
      JSON.parse(new TextDecoder().decode(this.decode(value)));
    const header = parse(parts[0]),
      payload = parse(parts[1]);
    const key = trust.keys?.find((k) => k.kid === header.kid);
    if (
      header.alg !== "ES256" ||
      header.jku ||
      header.jwk ||
      header.x5u ||
      header.crit ||
      !key ||
      key.d ||
      key.kty !== "EC" ||
      key.crv !== "P-256"
    )
      throw new Error("Unexpected signing algorithm or trusted key");
    const publicKey = await crypto.subtle.importKey(
      "jwk",
      key,
      { name: "ECDSA", namedCurve: "P-256" },
      false,
      ["verify"],
    );
    const valid = await crypto.subtle.verify(
      { name: "ECDSA", hash: "SHA-256" },
      publicKey,
      this.decode(parts[2]),
      new TextEncoder().encode(parts[0] + "." + parts[1]),
    );
    if (
      !valid ||
      payload.iss !== issuer ||
      payload.schema !== "nishabdha.decision.v1" ||
      this.canonical(payload) !== this.canonical(record.payload)
    )
      throw new Error("Signature, issuer or displayed record does not match");
    if (
      !payload.decision_id ||
      !Array.isArray(payload.reason_codes) ||
      !Number.isFinite(Date.parse(payload.recorded_at)) ||
      Date.parse(payload.recorded_at) > Date.now() + 5000
    )
      throw new Error("Invalid decision metadata");
    return payload;
  },
};
if (typeof document !== "undefined" && document.getElementById("receiptForm")) {
  document.getElementById("receiptForm").onsubmit = async (event) => {
    event.preventDefault();
    const status = document.getElementById("verifyStatus");
    const output = document.getElementById("verifiedPayload");
    output.hidden = true;
    output.textContent = "";
    try {
      const read = async (id) => {
        const file = document.getElementById(id).files[0];
        if (!file || file.size > 262144)
          throw new Error("Select a JSON file smaller than 256 KiB");
        return JSON.parse(await file.text());
      };
      const payload = await NishabdhaReceipt.verify(
        await read("receiptFile"),
        await read("trustedKeyFile"),
        document.getElementById("expectedIssuer").value.trim(),
      );
      status.textContent = `Signature verified · ${payload.outcome} · ${payload.operation} · evidence mode: ${payload.mode}. This is a historical application record.`;
      output.textContent = JSON.stringify(payload, null, 2);
      output.hidden = false;
    } catch (error) {
      status.textContent = "Verification failed: " + error.message;
    }
  };
}
