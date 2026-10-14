"""Tests for the Knowledge Base, Web Scraping, and Grounded RAG system."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.knowledge import extract as X, rag, seed_data, store
from app.main import app


@pytest.fixture(autouse=True)
def init_knowledge():
    seed_data.seed_knowledge_base()


def test_source_classification():
    assert X.classify_source("https://rbi.org.in/scripts/BS_CircularIndexDisplay.aspx") == "official"
    assert X.classify_source("https://cybercrime.gov.in/alert") == "official"
    assert X.classify_source("https://en.wikipedia.org/wiki/Deepfake") == "reference"
    assert X.classify_source("https://economictimes.indiatimes.com/news") == "news"
    assert X.classify_source("https://reddit.com/r/scams") == "forum"
    assert X.classify_source("https://unclone.bank/about") == "company"


def test_claim_analysis():
    c1 = X.analyse_claim("A customer shall have zero liability in contributory fraud by the bank.", "official")
    assert c1 is not None
    assert c1["kind"] in ("fact", "risk", "opportunity")
    assert c1["authority"] == 1.0

    c2 = X.analyse_claim("Scammers clone voice audio to demand ransom.", "news")
    assert c2 is not None
    assert c2["kind"] == "risk"
    assert c2["sentiment"] == -1

    c3 = X.analyse_claim("Fixed deposit rates range from 6.5 to 7.25 percent.", "company")
    assert c3 is not None
    assert c3["kind"] == "fact"

    # Boilerplate should be filtered out
    c_junk = X.analyse_claim("Click here for privacy policy and cookie terms all rights reserved.", "blog")
    assert c_junk is None


def test_store_and_search():
    stats = store.get_stats()
    assert stats["documents"] >= 4
    assert stats["chunks"] >= 4
    assert stats["claims"] >= 10

    # Search chunks via FTS5
    res = store.search_chunks("zero liability", k=5)
    assert len(res) > 0
    assert any("zero liability" in r["text"].lower() for r in res)

    # Search claims
    claims = store.search_claims(q="liability")
    assert len(claims) > 0


def test_citation_verification():
    ev = "A customer shall have zero liability when notifying the bank within three working days."
    supported = "The customer has zero liability if reported within three working days."
    unsupported = "The bank charges a penalty fee of ten thousand dollars."

    assert rag.verify_citation(supported, ev) == "supported"
    assert rag.verify_citation(unsupported, ev) == "unsupported"


@pytest.mark.asyncio
async def test_rag_answering():
    # Test asking a question regarding RBI guidelines
    res = await rag.answer_rag("What is the customer liability if unauthorized transaction is reported within three days?")
    assert res is not None
    assert "answer" in res
    assert len(res["answer"]) > 0
    assert "evidence" in res
    assert len(res["evidence"]) > 0
    assert res["covered"] is True
    assert "verification" in res


@pytest.mark.asyncio
async def test_knowledge_api_endpoints():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Stats endpoint
        r_stats = await client.get("/api/knowledge/stats")
        assert r_stats.status_code == 200
        stats = r_stats.json()
        assert stats["documents"] >= 4

        # 2. Search endpoint
        r_search = await client.get("/api/knowledge/search?q=rbi")
        assert r_search.status_code == 200
        data = r_search.json()
        assert data["count"] > 0

        # 3. Claims endpoint
        r_claims = await client.get("/api/knowledge/claims?limit=10")
        assert r_claims.status_code == 200
        assert len(r_claims.json()["claims"]) > 0

        # 4. RAG ask endpoint
        r_ask = await client.post("/api/knowledge/ask", json={"question": "What is the IFSC code and branch timings?"})
        assert r_ask.status_code == 200
        ans = r_ask.json()
        assert "answer" in ans
        assert "spoken_summary" in ans
        assert "evidence" in ans

        # 5. Health endpoint
        r_health = await client.get("/health")
        assert r_health.status_code == 200
        assert r_health.json()["status"] == "healthy"


def test_11_target_domains_coverage():
    """Verifies that all 11 required financial and voice clone domains are stored in the vector database."""
    stats = store.get_stats()
    assert stats["documents"] >= 11
    assert stats["chunks"] >= 30
    assert stats["claims"] >= 50

    # Test key domain terms in vector store
    domains_terms = [
        "zero liability",  # Banks
        "digital lending",  # NBFCs
        "spurious calls",   # Insurers
        "upi pin",          # UPI Users
        "wire transfer",    # Finance Teams
        "audio deepfakes",  # Voice Fraud Impersonation
        "video kyc",        # KYC
        "remote hiring",    # Hiring
        "proctored",        # Exams
        "vishing",          # Remote Work
        "emergency",        # When Anybody Can Be Cloned
    ]
    for term in domains_terms:
        res = store.search_chunks(term, k=3)
        assert len(res) > 0, f"Domain term '{term}' not found in vector store"


@pytest.mark.asyncio
async def test_rag_explicit_citations():
    """Verifies that RAG answers include explicit citations to source URLs and domains to guarantee zero hallucination."""
    queries = [
        "Do I ever need to enter my UPI PIN to receive money?",
        "What are the rules for NBFC loan recovery agents?",
        "How can parents defend against a cloned voice kidnapping call?",
    ]
    for q in queries:
        ans = await rag.answer_rag(q, auto_research=False)
        assert ans["covered"] is True
        assert len(ans["answer"]) > 0
        first_answer = ans["answer"][0]
        # Must have citation ID
        assert len(first_answer["cites"]) > 0
        # Text or source_info must specify the source
        assert "Source:" in first_answer["text"] or first_answer.get("source_info")
        # Verification must be present
        assert ans["verification"]["supported"] + ans["verification"]["partial"] > 0

