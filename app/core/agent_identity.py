"""ES256 signatures: application identity, not proof of acoustic authenticity."""

import hashlib
import json
import os
import tempfile
from functools import lru_cache

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.config import get_settings


def canonical(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: dict) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def origin() -> str:
    return get_settings().bank_origin.rstrip("/")


@lru_cache(maxsize=8)
def _load_key(directory: str):
    from pathlib import Path

    path = Path(directory) / "bank-signing-key.pem"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        key = ec.generate_private_key(ec.SECP256R1())
        encoded = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        # Publish a complete file atomically; simultaneous workers never read a partial PEM.
        fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".bank-key-")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(encoded)
                f.flush()
                os.fsync(f.fileno())
            try:
                os.link(temp, path)
            except FileExistsError:
                pass
        finally:
            os.unlink(temp)
    return serialization.load_pem_private_key(path.read_bytes(), password=None)


def signing_key():
    return _load_key(str(get_settings().data_dir))


def public_jwk() -> dict:
    result = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(signing_key().public_key()))
    result.update(alg="ES256", use="sig", kid=digest(result)[:24])
    return result


def sign_record(payload: dict) -> str:
    return jwt.encode(
        payload, signing_key(), algorithm="ES256", headers={"kid": public_jwk()["kid"]}
    )


def normalize_holder(jwk: dict) -> dict:
    if jwk.get("kty") != "EC" or jwk.get("crv") != "P-256" or "d" in jwk:
        raise ValueError("public P-256 JWK required")
    result = {k: jwk[k] for k in ("kty", "crv", "x", "y")}
    jwt.algorithms.ECAlgorithm.from_jwk(result)
    return result


def delegation_config(holder_jwk: dict) -> dict:
    return {
        "holder_jwk": normalize_holder(holder_jwk),
        "scope": "support_ticket.create",
        "max_uses": 1,
        "ttl_seconds": 600,
    }


def delegation_binding(holder_jwk: dict) -> str:
    return digest(delegation_config(holder_jwk))
