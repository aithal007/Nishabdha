"""Structured Knowledge Store (SQLite FTS5 + Claim Ledger + Vector Cosine)."""

from __future__ import annotations

import array
import json
import logging
import math
import sqlite3
import threading
import time

from app.knowledge.config import DB_PATH, DEFAULT_CHUNK_OVERLAP, DEFAULT_CHUNK_SIZE
from app.knowledge.embedder import get_embedding, get_embeddings_batch

log = logging.getLogger("unclone.knowledge.store")


_lock = threading.Lock()
_con: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    url TEXT PRIMARY KEY,
    domain TEXT,
    type TEXT,
    title TEXT,
    text TEXT,
    text_hash TEXT,
    via TEXT,
    indexed_at REAL
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_url TEXT,
    i INT,
    text TEXT,
    emb BLOB
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_url);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text,
    content='chunks',
    content_rowid='id'
);

CREATE TABLE IF NOT EXISTS claims (
    id TEXT,
    run TEXT,
    url TEXT,
    text TEXT,
    kind TEXT,
    epistemic TEXT,
    authority REAL,
    sentiment INT,
    prices TEXT,
    tasks TEXT,
    query TEXT,
    created REAL,
    PRIMARY KEY(run, id)
);

CREATE INDEX IF NOT EXISTS idx_claims_kind ON claims(kind);
CREATE INDEX IF NOT EXISTS idx_claims_url ON claims(url);
"""


def con() -> sqlite3.Connection:
    global _con
    if _con is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _con = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _con.row_factory = sqlite3.Row
        _con.executescript(SCHEMA)
    return _con


def chunk_text(
    text: str, size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_CHUNK_OVERLAP
) -> list[str]:
    """Chunks text preserving paragraphs when possible."""
    paragraphs = [p.strip() for p in (text or "").split("\n") if p.strip()]
    if not paragraphs:
        return []
    chunks = []
    current = ""
    for p in paragraphs:
        if current and len(current) + len(p) + 1 > size:
            chunks.append(current.strip())
            # overlap handling
            words = current.split()
            overlap_words = words[-max(1, overlap // 6) :] if len(words) > 10 else []
            current = " ".join(overlap_words) + (" " if overlap_words else "") + p
        else:
            current = (current + "\n" + p).strip() if current else p
    if current.strip():
        chunks.append(current.strip())
    return chunks


def needs_index(url: str, text_hash: str) -> bool:
    with _lock:
        r = (
            con()
            .execute("SELECT text_hash FROM documents WHERE url=?", (url,))
            .fetchone()
        )
        return not r or r[0] != text_hash


def put_document(doc: dict, chunks: list[str], embs: list[list[float]] | None = None):
    """Inserts or updates a document, rebuilding its chunks, vector embeddings, and FTS5 entries."""
    if embs is None and chunks:
        embs = get_embeddings_batch(chunks)

    with _lock, con() as c:
        c.execute(
            """INSERT OR REPLACE INTO documents
               (url, domain, type, title, text, text_hash, via, indexed_at)
               VALUES (:url, :domain, :type, :title, :text, :text_hash, :via, :indexed_at)""",
            {
                "url": doc["url"],
                "domain": doc.get("domain", ""),
                "type": doc.get("type", "company"),
                "title": doc.get("title", ""),
                "text": doc.get("text", ""),
                "text_hash": doc.get("text_hash", ""),
                "via": doc.get("via", "direct"),
                "indexed_at": time.time(),
            },
        )
        # Delete old chunks & FTS5
        old_ids = c.execute(
            "SELECT id, text FROM chunks WHERE doc_url=?", (doc["url"],)
        ).fetchall()
        for row in old_ids:
            c.execute(
                "INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES('delete', ?, ?)",
                (row["id"], row["text"]),
            )
        c.execute("DELETE FROM chunks WHERE doc_url=?", (doc["url"],))

        # Insert new chunks with vector embeddings
        for i, chunk in enumerate(chunks):
            emb_blob = (
                array.array("f", embs[i]).tobytes() if embs and i < len(embs) else None
            )
            rid = c.execute(
                "INSERT INTO chunks (doc_url, i, text, emb) VALUES (?, ?, ?, ?)",
                (doc["url"], i, chunk, emb_blob),
            ).lastrowid
            c.execute(
                "INSERT INTO chunks_fts (rowid, text) VALUES (?, ?)", (rid, chunk)
            )


def put_claims(claims: list[dict], run_id: str = "seed", query: str = ""):
    """Stores a batch of claims into the knowledge ledger."""
    with _lock, con() as c:
        rows = []
        for i, cl in enumerate(claims):
            cid = cl.get("id") or f"c{i + 1}"
            prices_str = json.dumps(cl.get("prices", []))
            tasks_str = json.dumps(cl.get("tasks", []))
            rows.append(
                (
                    cid,
                    run_id,
                    cl.get("url", ""),
                    cl.get("text", ""),
                    cl.get("kind", "fact"),
                    cl.get("epistemic", "reported"),
                    float(cl.get("authority", 0.5)),
                    int(cl.get("sentiment", 0)),
                    prices_str,
                    tasks_str,
                    query,
                    time.time(),
                )
            )
        c.executemany(
            """INSERT OR REPLACE INTO claims
               (id, run, url, text, kind, epistemic, authority, sentiment, prices, tasks, query, created)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )


def search_chunks(q: str, k: int = 8, qvec: list[float] | None = None) -> list[dict]:
    """Retrieves top-k chunks from the vector database using vector cosine similarity with BM25 fallback."""
    c = con()
    if qvec is None:
        qvec = get_embedding(q)

    # 1. Vector cosine similarity search
    qn = math.sqrt(sum(x * x for x in qvec)) or 1.0
    scored = []
    rows = c.execute(
        """SELECT c.id, c.doc_url, c.text, c.emb, d.title, d.domain, d.type
           FROM chunks c JOIN documents d ON d.url = c.doc_url AND d.via IN ('curated_demo_policy', 'reviewed_external')
           WHERE c.emb IS NOT NULL"""
    ).fetchall()
    for r in rows:
        v = array.array("f", r["emb"])
        dot = sum(a * b for a, b in zip(qvec, v))
        vn = math.sqrt(sum(x * x for x in v)) or 1.0
        score = dot / (qn * vn)
        scored.append((score, r))
    scored.sort(key=lambda x: -x[0])

    # If vector match is found, return top results
    if scored and scored[0][0] > 0.04:
        return [
            {
                "id": f"d{r['id']}",
                "doc_url": r["doc_url"],
                "url": r["doc_url"],
                "title": r["title"],
                "domain": r["domain"],
                "type": r["type"],
                "text": r["text"],
                "score": round(score, 4),
            }
            for score, r in scored[:k]
        ]

    # FTS5 search
    clean_words = [
        w for w in q.replace('"', " ").replace("'", " ").split() if len(w) > 2
    ]
    terms = " OR ".join(f'"{w}"' for w in clean_words)
    if not terms:
        # Fallback to recent chunks
        rows = c.execute(
            """SELECT c.id, c.doc_url, c.text, d.title, d.domain, d.type
               FROM chunks c JOIN documents d ON d.url = c.doc_url AND d.via IN ('curated_demo_policy', 'reviewed_external')
               LIMIT ?""",
            (k,),
        ).fetchall()
        return [
            {
                "id": f"d{r['id']}",
                "doc_url": r["doc_url"],
                "url": r["doc_url"],
                "title": r["title"],
                "domain": r["domain"],
                "type": r["type"],
                "text": r["text"],
                "score": 0.1,
            }
            for r in rows
        ]

    try:
        rows = c.execute(
            """SELECT c.id, c.doc_url, c.text, d.title, d.domain, d.type, bm25(chunks_fts) as score
               FROM chunks_fts
               JOIN chunks c ON c.id = chunks_fts.rowid
               JOIN documents d ON d.url = c.doc_url AND d.via IN ('curated_demo_policy', 'reviewed_external')
               WHERE chunks_fts MATCH ?
               ORDER BY score ASC LIMIT ?""",
            (terms, k),
        ).fetchall()
        return [
            {
                "id": f"d{r['id']}",
                "doc_url": r["doc_url"],
                "url": r["doc_url"],
                "title": r["title"],
                "domain": r["domain"],
                "type": r["type"],
                "text": r["text"],
                "score": round(-float(r["score"]), 4),
            }
            for r in rows
        ]
    except Exception as e:
        log.warning("FTS match failed (%s); trying LIKE fallback", e)
        # LIKE fallback
        pat = f"%{clean_words[0]}%" if clean_words else "%"
        rows = c.execute(
            """SELECT c.id, c.doc_url, c.text, d.title, d.domain, d.type
               FROM chunks c JOIN documents d ON d.url = c.doc_url AND d.via IN ('curated_demo_policy', 'reviewed_external')
               WHERE c.text LIKE ? LIMIT ?""",
            (pat, k),
        ).fetchall()
        return [
            {
                "id": f"d{r['id']}",
                "doc_url": r["doc_url"],
                "url": r["doc_url"],
                "title": r["title"],
                "domain": r["domain"],
                "type": r["type"],
                "text": r["text"],
                "score": 0.5,
            }
            for r in rows
        ]


def search_claims(q: str = "", kind: str = "", limit: int = 50) -> list[dict]:
    """Retrieves claims filtered by text keywords and/or kind."""
    c = con()
    query_parts = [
        "url IN (SELECT url FROM documents WHERE via IN ('curated_demo_policy', 'reviewed_external'))"
    ]
    params = []
    if kind:
        query_parts.append("kind = ?")
        params.append(kind)
    if q:
        query_parts.append("text LIKE ?")
        params.append(f"%{q}%")
    where_sql = " AND ".join(query_parts)
    params.append(limit)
    rows = c.execute(
        f"""SELECT id, run, url, text, kind, epistemic, authority, sentiment, prices, tasks, query, created
            FROM claims WHERE {where_sql} ORDER BY authority DESC, created DESC LIMIT ?""",
        params,
    ).fetchall()
    return [
        {
            "id": r["id"],
            "run": r["run"],
            "url": r["url"],
            "text": r["text"],
            "kind": r["kind"],
            "epistemic": r["epistemic"],
            "authority": r["authority"],
            "sentiment": r["sentiment"],
            "prices": json.loads(r["prices"] or "[]"),
            "tasks": json.loads(r["tasks"] or "[]"),
            "query": r["query"],
            "created": r["created"],
        }
        for r in rows
    ]


def get_stats() -> dict:
    """Returns overview statistics of the knowledge base."""
    c = con()
    n_docs = c.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    n_chunks = c.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    n_claims = c.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
    domains = [
        r[0]
        for r in c.execute(
            "SELECT DISTINCT domain FROM documents WHERE domain != ''"
        ).fetchall()
    ]
    return {
        "documents": n_docs,
        "chunks": n_chunks,
        "claims": n_claims,
        "domains_count": len(domains),
        "domains": domains[:15],
    }


def get_recent_documents(limit: int = 20) -> list[dict]:
    c = con()
    rows = c.execute(
        """SELECT url, domain, type, title, text_hash, via, indexed_at
           FROM documents ORDER BY indexed_at DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]
