"""Curated demonstration policy; not regulator guidance or a real bank policy."""

import hashlib

from app.knowledge import store

DOCUMENTS = [
    {
        "url": "demo://nishabdha/transfer-approval",
        "title": "Demo policy: transfer and passkey approval",
        "text": "In Nishabdha's simulated banking demo, every transfer requires a passkey approval in the customer app. Review the exact amount, saved beneficiary and source account before confirming. The server freezes these details and binds the passkey challenge to the action hash. Changing the transaction cancels the approval. Missing or stale required voice evidence holds a voice transfer; a passkey does not replace missing voice evidence.",
    },
    {
        "url": "demo://nishabdha/delegate",
        "title": "Demo policy: support assistant permissions",
        "text": "A customer can authorize an AI support assistant with a passkey to create one support ticket within ten minutes. The permission names the assistant's signing key and can be revoked. The assistant must sign a fresh request and use a server nonce. It cannot transfer money, read balances or change account details. Replayed requests and attempts outside the support-ticket scope are refused.",
    },
    {
        "url": "demo://unclone/verification",
        "title": "Demo policy: caller verification",
        "text": "In this demonstration, sensitive actions require caller verification and independent approval in the customer app. Voice similarity alone does not authorize an action.",
    },
    {
        "url": "demo://unclone/agent",
        "title": "Demo policy: bank identity",
        "text": "In this demonstration, verify the bank agent using the independently opened customer app. A caller's spoken claim to represent the bank is not proof of identity.",
    },
    {
        "url": "demo://unclone/review",
        "title": "Demo policy: uncertain evidence",
        "text": "In this demonstration, uncertain verification evidence holds sensitive actions for review. A suspicious audio score is a risk signal, not proof that a person committed fraud.",
    },
]


def seed_knowledge_base(force=False):
    for item in DOCUMENTS:
        digest = hashlib.sha256(item["text"].encode()).hexdigest()
        if not force and not store.needs_index(item["url"], digest):
            continue
        doc = dict(
            item,
            domain="Unclone demonstration",
            type="demo_policy",
            text_hash=digest,
            via="curated_demo_policy",
        )
        store.put_document(doc, store.chunk_text(doc["text"]))
