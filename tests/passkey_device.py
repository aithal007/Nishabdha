"""A test-only authenticator: real P-256/COSE signatures, no verification bypasses."""

import hashlib
import json
import secrets

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from webauthn.helpers import bytes_to_base64url as enc


class Device:
    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.id = secrets.token_bytes(32)
        self.counter = 0

    def client_data(self, options, kind, origin):
        return json.dumps(
            {
                "type": kind,
                "challenge": options["challenge"],
                "origin": origin,
                "crossOrigin": False,
            },
            separators=(",", ":"),
        ).encode()

    def register(self, options, origin="http://localhost:8000"):
        point = self.key.public_key().public_numbers()
        cose = cbor2.dumps(
            {
                1: 2,
                3: -7,
                -1: 1,
                -2: point.x.to_bytes(32, "big"),
                -3: point.y.to_bytes(32, "big"),
            }
        )
        auth = (
            hashlib.sha256(options["rp"]["id"].encode()).digest()
            + b"\x45"
            + (0).to_bytes(4, "big")
        )
        auth += bytes(16) + len(self.id).to_bytes(2, "big") + self.id + cose
        att = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth})
        return {
            "id": enc(self.id),
            "rawId": enc(self.id),
            "type": "public-key",
            "response": {
                "clientDataJSON": enc(
                    self.client_data(options, "webauthn.create", origin)
                ),
                "attestationObject": enc(att),
            },
            "clientExtensionResults": {},
        }

    def authenticate(self, options, origin="http://localhost:8000", uv=True):
        self.counter += 1
        client = self.client_data(options, "webauthn.get", origin)
        auth = (
            hashlib.sha256(options["rpId"].encode()).digest()
            + bytes([5 if uv else 1])
            + self.counter.to_bytes(4, "big")
        )
        sig = self.key.sign(
            auth + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256())
        )
        return {
            "id": enc(self.id),
            "rawId": enc(self.id),
            "type": "public-key",
            "response": {
                "clientDataJSON": enc(client),
                "authenticatorData": enc(auth),
                "signature": enc(sig),
            },
            "clientExtensionResults": {},
        }


async def provision(client, customer="cus_ananya", token="app-ananya-demo"):
    from .conftest import STAFF

    device = Device()
    r = await client.post(
        f"/api/admin/customers/{customer}/passkeys/options", headers=STAFF
    )
    assert r.status_code == 200, r.text
    p = r.json()
    r = await client.post(
        "/api/app/passkeys/verify",
        headers={"X-App-Token": token},
        json={
            "approval_id": p["approval_id"],
            "credential": device.register(p["options"]),
        },
    )
    assert r.status_code == 200, r.text
    return device
