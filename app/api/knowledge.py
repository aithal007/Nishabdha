"""FastAPI Router for Knowledge Base, Autonomous Scraping & Grounded RAG."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field

from app.knowledge import pipeline, rag, scraper, store
from app.knowledge.config import RUNS_DIR

log = logging.getLogger("unclone.api.knowledge")

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


class AskRequest(BaseModel):
    question: str = Field(..., min_length=2, max_length=1000, description="Banking or security question")


class ResearchRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=500, description="Topic or threat intelligence query to research & scrape")


class ScrapeRequest(BaseModel):
    url: str = Field(..., min_length=5, max_length=1000, description="Direct URL of a bank policy or advisory web page to scrape")


@router.post("/ask")
async def ask_rag(req: AskRequest):
    """Answers a banking query via Grounded RAG with verbatim citations and verification."""
    try:
        res = await rag.answer_rag(req.question)
        return res
    except Exception as e:
        log.exception("Error answering RAG query")
        raise HTTPException(status_code=500, detail=f"RAG query failed: {type(e).__name__}: {e}")


@router.post("/research")
async def start_research(req: ResearchRequest, background_tasks: BackgroundTasks):
    """Starts an autonomous research run: decomposes topic, searches web, scrapes pages, extracts claims, and indexes into the knowledge base."""
    run = pipeline.ResearchRun(req.query)

    async def _run_job():
        try:
            await run.execute()
        except Exception as e:
            log.warning("Research run %s error: %s", run.id, e)

    background_tasks.add_task(_run_job)
    return {
        "ok": True,
        "run_id": run.id,
        "query": run.query,
        "status": "running",
        "message": f"Autonomous research launched for '{req.query}'. Fetch /api/knowledge/runs/{run.id} for live progress.",
    }


@router.post("/scrape")
async def scrape_url(req: ScrapeRequest):
    """Directly scrapes a single URL, cleans the text, extracts claims, and indexes it into the knowledge base."""
    if not req.url.startswith("http://") and not req.url.startswith("https://"):
        raise HTTPException(status_code=400, detail="URL must start with http:// or https://")
    res = await pipeline.scrape_single_url(req.url)
    if not res.get("ok"):
        raise HTTPException(status_code=422, detail=res.get("error", "Failed to scrape page"))
    return res


@router.get("/search")
async def search_knowledge(q: str = Query(..., min_length=1), k: int = Query(8, ge=1, le=50)):
    """Searches indexed passages in the knowledge base using FTS5 BM25 ranking."""
    results = store.search_chunks(q, k=k)
    return {"query": q, "count": len(results), "results": results}


@router.get("/claims")
async def list_claims(q: str = Query("", max_length=100), kind: str = Query("", max_length=30), limit: int = Query(50, ge=1, le=200)):
    """Retrieves extracted claims from the knowledge ledger with authority scores."""
    claims = store.search_claims(q=q, kind=kind, limit=limit)
    return {"count": len(claims), "claims": claims}


@router.get("/stats")
async def knowledge_stats():
    """Returns overview statistics of documents, chunks, and claims in the knowledge base."""
    return store.get_stats()


@router.get("/documents")
async def list_documents(limit: int = Query(20, ge=1, le=100)):
    """Lists indexed documents and web sources."""
    return {"documents": store.get_recent_documents(limit=limit)}


@router.get("/runs")
async def list_runs():
    """Lists recent research runs."""
    runs = []
    # In-memory active runs
    for r in pipeline.ACTIVE_RUNS.values():
        runs.append({"id": r.id, "query": r.query, "status": r.status, "created": r.created, "events_count": len(r.events)})
    # Disk runs
    try:
        for p in RUNS_DIR.glob("*.json"):
            rid = p.stem
            if rid not in pipeline.ACTIVE_RUNS:
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    runs.append({"id": data.get("id", rid), "query": data.get("query", ""), "status": data.get("status", "completed"), "created": data.get("created", 0), "events_count": len(data.get("events", []))})
                except Exception:
                    pass
    except Exception:
        pass
    runs.sort(key=lambda x: -x["created"])
    return {"runs": runs[:20]}


@router.get("/runs/{rid}")
async def get_run(rid: str):
    """Retrieves full snapshot and event stream of a specific research run."""
    if rid in pipeline.ACTIVE_RUNS:
        return pipeline.ACTIVE_RUNS[rid].snapshot()
    p = RUNS_DIR / f"{rid}.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    raise HTTPException(status_code=404, detail="Research run not found")
