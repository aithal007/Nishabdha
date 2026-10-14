"""Autonomous Research & Scraping Pipeline (Planning -> Search -> Scraping -> Claim Extraction -> Indexing)."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
import uuid
from collections import Counter
from urllib.parse import urlparse

from app.knowledge import extract as X, scraper, search, store
from app.knowledge.config import MAX_RESEARCH_SOURCES, RUNS_DIR
from app.providers.llm import get_llm

log = logging.getLogger("unclone.knowledge.pipeline")

FALLBACK_BANKING_TASKS = [
    ("regulations guidelines", "What official regulations or guidelines apply?"),
    ("scams threat vectors", "What are the common scams, modus operandi, and fraud risks?"),
    ("bank policy rules", "What are the bank's rules, limits, and timelines?"),
    ("prevention customer safety", "What steps should customers take to stay protected?"),
]

ACTIVE_RUNS: dict[str, ResearchRun] = {}


class ResearchRun:
    def __init__(self, query: str):
        self.id = uuid.uuid4().hex[:10]
        self.query = query.strip()
        self.created = time.time()
        self.status = "created"
        self.events: list[dict] = []
        self.sources: dict[str, dict] = {}
        self.claims: dict[str, dict] = {}
        self.docs: dict[str, str] = {}
        self.plan: list[dict] = []
        self.summary: str = ""
        ACTIVE_RUNS[self.id] = self

    def emit(self, stage: str, title: str, status: str, summary: str = "", data: dict | None = None):
        ev = {
            "i": len(self.events),
            "t": round(time.time() - self.created, 1),
            "stage": stage,
            "title": title,
            "status": status,
            "summary": summary,
            "data": data or {},
        }
        self.events.append(ev)
        log.info("[%s] [%s] %s: %s", self.id, stage, title, summary)

    async def execute(self) -> dict:
        self.status = "running"
        try:
            # 1. Plan
            await self._stage_plan()
            # 2. Search
            await self._stage_search()
            # 3. Select & Scrape
            await self._stage_scrape()
            # 4. Extract Claims
            await self._stage_extract()
            # 5. Index
            await self._stage_index()

            self.status = "completed"
            self.emit("complete", "Research & Scraping Complete", "done", f"Indexed {len(self.docs)} documents, {len(self.claims)} claims.")
            self._save()
            return self.snapshot()
        except Exception as e:
            self.status = "failed"
            self.emit("error", "Research Run Failed", "failed", f"{type(e).__name__}: {e}")
            self._save()
            raise

    async def _stage_plan(self):
        self.emit("plan", "Decomposing Research Topic", "running")
        llm = get_llm()
        tasks = []
        if llm.available:
            system_prompt = (
                "You are an expert research planner for banking security, financial fraud, and customer safety. "
                "Break down the research query into 3-5 distinct, keyword-focused search queries. "
                "Return JSON ONLY with format: {\"tasks\": [{\"q\": \"search query\", \"question\": \"sub-question\"}]}"
            )
            try:
                resp = await llm.json_chat(system_prompt, f"Topic: {self.query}")
                raw_tasks = resp.get("tasks", [])
                for t in raw_tasks:
                    if t.get("q"):
                        tasks.append({"q": str(t["q"]), "question": str(t.get("question", t["q"]))})
            except Exception as e:
                log.warning("LLM planning failed (%s), using fallback topics", e)

        if not tasks:
            for subtopic, q_text in FALLBACK_BANKING_TASKS:
                tasks.append({"q": f"{self.query} {subtopic}".strip(), "question": q_text})

        self.plan = [{"id": f"t{i+1}", **t} for i, t in enumerate(tasks)]
        self.emit("plan", "Plan Created", "done", f"Generated {len(self.plan)} research queries", {"plan": self.plan})

    async def _stage_search(self):
        self.emit("search", "Searching Web & Open Sources", "running")
        search_results = []
        for t in self.plan:
            q = t["q"]
            res = await search.search_web(q, max_results=6)
            for r in res:
                r["task_id"] = t["id"]
            search_results.extend(res)
            self.emit("search", f"Searched: {q}", "progress", f"Found {len(res)} results", {"query": q, "count": len(res)})

        # De-duplicate
        seen_urls = set()
        candidates = []
        for r in search_results:
            u = r.get("url")
            if not u or u in seen_urls:
                continue
            seen_urls.add(u)
            stype = X.classify_source(u)
            authority, label = X.SOURCE_TYPES.get(stype, (0.5, "Standard"))
            candidates.append({
                "url": u,
                "title": r.get("title", ""),
                "snippet": r.get("snippet", ""),
                "type": stype,
                "type_label": label,
                "authority": authority,
                "domain": urlparse(u).netloc.replace("www.", ""),
                "task_id": r.get("task_id", ""),
            })

        # Rank by authority
        candidates.sort(key=lambda c: -c["authority"])
        self.candidates = candidates
        self.emit("search", "Search Completed", "done", f"Collected {len(candidates)} unique sources", {"count": len(candidates)})

    async def _stage_scrape(self):
        self.emit("scrape", "Scraping Pages & Reading Full Content", "running")
        # Select up to MAX_RESEARCH_SOURCES
        selected = self.candidates[:MAX_RESEARCH_SOURCES]
        sem = asyncio.Semaphore(4)

        async def _fetch_one(cand: dict):
            u = cand["url"]
            async with sem:
                page = await scraper.fetch_page(u)
            if page.get("ok") and page.get("text"):
                sid = f"s{len(self.sources) + 1}"
                cand["id"] = sid
                cand["status"] = "fetched"
                cand["chars"] = len(page["text"])
                cand["via"] = page.get("via", "http")
                self.sources[sid] = cand
                self.docs[sid] = page["text"]
                self.emit("scrape", f"Read {cand['domain']}", "progress", f"{len(page['text']):,} chars", {"source": sid, "url": u})
            else:
                self.emit("scrape", f"Failed {cand['domain']}", "progress", page.get("error", "fetch error"), {"url": u})

        await asyncio.gather(*(_fetch_one(c) for c in selected))
        self.emit("scrape", "Scraping Finished", "done", f"Successfully scraped {len(self.docs)} full documents", {"sources_count": len(self.sources)})

    async def _stage_extract(self):
        self.emit("extract", "Extracting Claims & Verbatim Evidence", "running")
        new_claims = []
        for sid, text in self.docs.items():
            src = self.sources[sid]
            sentences = X.split_sentences(text)
            for _, sent in sentences:
                claim_attrs = X.analyse_claim(sent, src["type"])
                if not claim_attrs:
                    continue
                cid = f"c{len(self.claims) + 1}"
                c_item = {
                    "id": cid,
                    "text": sent,
                    "source": sid,
                    "url": src["url"],
                    "domain": src["domain"],
                    "kind": claim_attrs["kind"],
                    "epistemic": claim_attrs["epistemic"],
                    "authority": claim_attrs["authority"],
                    "sentiment": claim_attrs["sentiment"],
                    "prices": claim_attrs["prices"],
                    "tasks": [src.get("task_id", "")],
                }
                self.claims[cid] = c_item
                new_claims.append(c_item)

        kinds_summary = Counter(c["kind"] for c in self.claims.values())
        summary_str = ", ".join(f"{v} {k}" for k, v in kinds_summary.items()) or "no claims"
        self.emit("extract", "Claim Extraction Complete", "done", f"Extracted {len(self.claims)} structured claims ({summary_str})", {"claims_count": len(self.claims)})

    async def _stage_index(self):
        self.emit("index", "Indexing into Knowledge Base & Vector Store", "running")
        indexed_docs = 0
        indexed_chunks = 0
        for sid, text in self.docs.items():
            src = self.sources[sid]
            h = hashlib.sha256(text.encode("utf-8")).hexdigest()
            chunks = store.chunk_text(text)
            doc_meta = {
                "url": src["url"],
                "domain": src["domain"],
                "type": src["type"],
                "title": src.get("title", ""),
                "text": text,
                "text_hash": h,
                "via": src.get("via", "http"),
            }
            store.put_document(doc_meta, chunks)
            indexed_docs += 1
            indexed_chunks += len(chunks)

        # Store claims
        store.put_claims(list(self.claims.values()), run_id=self.id, query=self.query)
        stats = store.get_stats()
        self.emit("index", "Indexed Knowledge Base", "done", f"Added {indexed_docs} docs ({indexed_chunks} chunks); Store totals: {stats['documents']} docs, {stats['chunks']} chunks, {stats['claims']} claims", {"stats": stats})

    def snapshot(self) -> dict:
        return {
            "id": self.id,
            "query": self.query,
            "status": self.status,
            "created": self.created,
            "events": self.events,
            "plan": self.plan,
            "sources": self.sources,
            "claims": self.claims,
            "summary": self.summary,
        }

    def _save(self):
        try:
            p = RUNS_DIR / f"{self.id}.json"
            p.write_text(json.dumps(self.snapshot(), ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            log.warning("Failed to save run snapshot: %s", e)


async def scrape_single_url(url: str) -> dict:
    """Scrapes a single URL and indexes it into the knowledge base directly."""
    page = await scraper.fetch_page(url, force_refresh=True)
    if not page.get("ok"):
        return {"ok": False, "error": page.get("error", "Scrape failed")}

    text = page["text"]
    title = page.get("title", url)
    domain = urlparse(url).netloc.replace("www.", "")
    stype = X.classify_source(url)
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()

    chunks = store.chunk_text(text)
    doc_meta = {
        "url": url,
        "domain": domain,
        "type": stype,
        "title": title,
        "text": text,
        "text_hash": h,
        "via": "direct_url",
    }
    store.put_document(doc_meta, chunks)

    # Extract claims
    sentences = X.split_sentences(text)
    claims = []
    for i, (_, sent) in enumerate(sentences):
        attrs = X.analyse_claim(sent, stype)
        if not attrs:
            continue
        claims.append({
            "id": f"c_{h[:6]}_{i+1}",
            "text": sent,
            "url": url,
            "domain": domain,
            "kind": attrs["kind"],
            "epistemic": attrs["epistemic"],
            "authority": attrs["authority"],
            "sentiment": attrs["sentiment"],
            "prices": attrs["prices"],
            "tasks": ["direct_scrape"],
        })

    if claims:
        store.put_claims(claims, run_id=f"scrape_{h[:8]}", query=url)

    return {
        "ok": True,
        "url": url,
        "title": title,
        "domain": domain,
        "type": stype,
        "chars": len(text),
        "chunks": len(chunks),
        "claims": len(claims),
    }
