"""Reviewed knowledge boundary tests; no live network or models."""

import socket

import pytest
from httpx import ASGITransport, AsyncClient

from app.knowledge import quarantine, rag, scraper, seed_data, store
from app.knowledge.extract import classify_source
from app.main import app


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_con", None)
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "kb.db")
    monkeypatch.setattr(quarantine, "DIRECTORY", tmp_path / "pending")
    seed_data.seed_knowledge_base()
    yield
    if store._con:
        store._con.close()
    store._con = None


@pytest.mark.asyncio
async def test_extract_only_and_no_research(monkeypatch):
    from app.knowledge import pipeline

    async def forbidden(*args):
        raise AssertionError("Research must not run on calls")

    monkeypatch.setattr(pipeline.ResearchRun, "execute", forbidden)
    answer = await rag.answer_rag(
        "Why do sensitive actions require caller verification?", auto_research=True
    )
    assert answer["covered"]
    assert answer["spoken_summary"] == answer["answer"][0]["text"]
    assert answer["answer"][0]["text"] in answer["evidence"][0]["text"]
    assert not answer["researched"]
    unknown = await rag.answer_rag("What is the orbital period of Neptune?")
    assert not unknown["covered"]


def test_citations_not_overlap():
    assert (
        rag.verify_citation("Transfers are permitted.", "Transfers are not permitted.")
        == "unsupported"
    )
    assert rag.verify_citation("Limit is 900.", "Limit is 100.") == "unsupported"


def test_quarantine_hash_bound_approval():
    item = quarantine.stage(
        {
            "url": "https://www.rbi.org.in/example",
            "title": "Reviewed example",
            "text": "Zebra policy requires amber approval.",
        }
    )
    assert not any("Zebra" in r["text"] for r in store.search_chunks("Zebra amber"))
    with pytest.raises(ValueError):
        quarantine.approve(item["id"], "0" * 64)
    quarantine.approve(item["id"], item["text_hash"])
    assert any("Zebra" in r["text"] for r in store.search_chunks("Zebra amber"))


def test_legacy_unreviewed_is_excluded():
    store.put_document(
        {
            "url": "https://www.rbi.org.in/legacy",
            "text": "Zebra unsupported legacy",
            "via": "authoritative_seed",
        },
        ["Zebra unsupported legacy"],
    )
    assert not any(
        "legacy" in r["text"] for r in store.search_chunks("Zebra unsupported legacy")
    )
    assert classify_source("https://rbi.org.in.evil.example/a") != "official"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://www.rbi.org.in/x",
        "https://rbi.org.in.evil.example/x",
        "https://127.0.0.1/x",
        "https://user:pass@www.rbi.org.in/x",
        "https://www.rbi.org.in:8443/x",
    ],
)
async def test_source_url_rejected(url):
    with pytest.raises(ValueError):
        await scraper.validate_source_url(url)


@pytest.mark.asyncio
async def test_private_dns_rejected(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))
        ],
    )
    with pytest.raises(ValueError):
        await scraper.validate_source_url("https://www.rbi.org.in/a")


@pytest.mark.asyncio
async def test_ingestion_requires_staff():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        for route, body in [
            ("scrape", {"url": "https://www.rbi.org.in/a"}),
            ("research", {"query": "caller verification"}),
            ("quarantine/" + "a" * 32 + "/approve", {"text_hash": "0" * 64}),
        ]:
            response = await client.post("/api/knowledge/" + route, json=body)
            assert response.status_code == 401
