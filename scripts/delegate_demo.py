"""Holder CLI. First generate a key; approve its public JWK in the customer UI.

python scripts/delegate_demo.py key --key data/delegate-key.pem
python scripts/delegate_demo.py execute --key data/delegate-key.pem --grant grant_... --origin http://localhost:8000
Never copy the private key into the customer UI. This CLI does not bypass passkeys.
"""

import argparse
import hashlib
import json
import secrets
import time
from pathlib import Path

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["key", "execute"])
    p.add_argument("--key", default="data/delegate-key.pem")
    p.add_argument("--grant")
    p.add_argument("--origin", default="http://localhost:8000")
    p.add_argument("--subject", default="Please explain my card statement")
    args = p.parse_args()
    path = Path(args.key)
    if args.command == "key":
        if path.exists():
            p.error("Key file exists; choose a new path to avoid overwriting authority")
        path.parent.mkdir(parents=True, exist_ok=True)
        key = ec.generate_private_key(ec.SECP256R1())
        import os

        with os.fdopen(
            os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb"
        ) as f:
            f.write(
                key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
            )
        print(jwt.algorithms.ECAlgorithm.to_jwk(key.public_key()))
        return
    if not args.grant:
        p.error(
            "--grant required; obtain it through passkey-approved customer delegation"
        )
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    origin = args.origin.rstrip("/")
    with httpx.Client(base_url=origin, timeout=15) as client:
        response = client.post(f"/api/agents/grants/{args.grant}/nonce")
        response.raise_for_status()
        nonce = response.json()
        if nonce["audience"] != origin:
            p.error("Server audience does not match the explicitly trusted origin")
        body = {"action": "support_ticket.create", "subject": args.subject}
        digest = hashlib.sha256(
            json.dumps(
                body, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode()
        ).hexdigest()
        now = int(time.time())
        claims = {
            "aud": origin,
            "iat": now,
            "exp": now + 60,
            "jti": secrets.token_urlsafe(16),
            "grant_id": args.grant,
            "nonce": nonce["nonce"],
            "body_hash": digest,
        }
        response = client.post(
            f"/api/agents/grants/{args.grant}/execute",
            json={**body, "proof": jwt.encode(claims, key, algorithm="ES256")},
        )
        print(response.status_code, response.text)
        response.raise_for_status()


if __name__ == "__main__":
    main()
