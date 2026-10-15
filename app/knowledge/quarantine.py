"""Untrusted fetched material stays separate until an authenticated staff review."""

import hashlib
import json
import re
import time
import uuid

from app.knowledge import store
from app.knowledge.config import DATA_DIR

DIRECTORY = DATA_DIR / "quarantine"


def _path(identifier):
    if not re.fullmatch(r"[a-f0-9]{32}", identifier):
        raise ValueError("Invalid quarantine identifier")
    return DIRECTORY / (identifier + ".json")


def stage(page):
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    identifier = uuid.uuid4().hex
    record = dict(
        page,
        id=identifier,
        status="pending_review",
        retrieved_at=page.get("retrieved_at", time.time()),
    )
    record["text_hash"] = hashlib.sha256(record["text"].encode()).hexdigest()
    _path(identifier).write_text(
        json.dumps(record, ensure_ascii=False), encoding="utf-8"
    )
    return {
        "ok": True,
        "id": identifier,
        "url": record["url"],
        "status": "pending_review",
        "text_hash": record["text_hash"],
    }


def inspect(identifier):
    return json.loads(_path(identifier).read_text(encoding="utf-8"))


def approve(identifier, expected_hash):
    record = inspect(identifier)
    actual = hashlib.sha256(record["text"].encode()).hexdigest()
    if actual != expected_hash or actual != record["text_hash"]:
        raise ValueError("Reviewed content hash does not match")
    from urllib.parse import urlsplit

    store.put_document(
        dict(
            record,
            domain=urlsplit(record["url"]).hostname,
            type="reviewed_source",
            via="reviewed_external",
        ),
        store.chunk_text(record["text"]),
    )
    record.update(status="approved", reviewed_at=time.time())
    _path(identifier).write_text(
        json.dumps(record, ensure_ascii=False), encoding="utf-8"
    )
    return {"ok": True, "id": identifier, "status": "approved", "text_hash": actual}
