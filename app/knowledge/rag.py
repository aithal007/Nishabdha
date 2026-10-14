"""Grounded Retrieval-Augmented Generation (RAG) with citation tracking, vector search, and autonomous research fallback."""
from __future__ import annotations

import logging
import re
from typing import Any

from app.knowledge import store
from app.providers.llm import get_llm

log = logging.getLogger("unclone.knowledge.rag")

SYSTEM_RAG = (
    "You are the Grounded Banking Knowledge & Security Verification Assistant. "
    "Answer the user's question accurately using ONLY the provided evidence. "
    "Rules:\n"
    "1. Write 2-4 factual, clear sentences.\n"
    "2. Every single sentence MUST cite the evidence ID it rests upon (e.g. [c1] or [d1]).\n"
    "3. State the exact source (e.g. 'According to [c1] (Source: Reserve Bank of India - https://www.rbi.org.in/...): ...').\n"
    "4. Also provide a 'spoken_summary' (1-2 short, conversational sentences suitable for reading out loud over a phone call).\n"
    "5. If the provided evidence does not cover the question, state what is known, state what is missing, and set covered=false.\n"
    "6. Do NOT invent facts or cite IDs not in the evidence list. Zero hallucination allowed.\n"
    "Return JSON ONLY with format:\n"
    "{\n"
    "  \"answer\": [{\"text\": \"sentence string with [c1] citation\", \"cites\": [\"c1\"]}],\n"
    "  \"spoken_summary\": \"short voice banking reply\",\n"
    "  \"covered\": true\n"
    "}"
)

STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "are", "was", "were", "has", "have", "had",
    "from", "shall", "will", "may", "can", "not", "but", "you", "your", "our", "all", "any",
    "when", "where", "what", "which", "who", "whom", "how", "why", "been", "being", "into",
    "over", "under", "about", "such", "than", "then", "their", "there", "they", "them", "bank"
}


def _clean_cite_id(cite: str) -> str:
    m = re.search(r"[cd]\d+", str(cite).lower())
    return m.group(0) if m else str(cite).strip(" []")


def verify_citation(sentence: str, evidence_text: str) -> str:
    """Checks whether a sentence is supported by its cited evidence using lexical overlap."""
    if not evidence_text:
        return "unsupported"
    s_words = {w.lower() for w in re.findall(r"\b[a-zA-Z0-9]{3,}\b", sentence) if w.lower() not in STOPWORDS}
    e_words = {w.lower() for w in re.findall(r"\b[a-zA-Z0-9]{3,}\b", evidence_text) if w.lower() not in STOPWORDS}
    if not s_words:
        return "unsupported"
    overlap = len(s_words & e_words) / len(s_words)
    if overlap >= 0.30:
        return "supported"
    elif overlap >= 0.15:
        return "partial"
    return "unsupported"


async def retrieve_evidence(question: str, top_claims: int = 10, top_passages: int = 4) -> list[dict]:
    """Retrieves top claims and passage chunks for a question using vector cosine similarity and FTS5."""
    # 1. Retrieve chunks from vector database
    chunks = store.search_chunks(question, k=top_passages)

    # 2. Retrieve claims from claim ledger matching question terms
    q_words = [w.lower() for w in re.findall(r"\b[a-zA-Z0-9]{3,}\b", question) if w.lower() not in STOPWORDS]
    claims = []
    for w in q_words:
        claims.extend(store.search_claims(q=w, limit=6))

    # De-duplicate claims and sort by term relevance
    seen_cids = set()
    deduped_claims = []
    for c in claims:
        if c["id"] not in seen_cids:
            seen_cids.add(c["id"])
            deduped_claims.append(c)

    deduped_claims.sort(
        key=lambda c: (
            sum(w in c["text"].lower() for w in q_words),
            c.get("authority", 0.5),
        ),
        reverse=True,
    )

    ev_list = []
    # Add passages from vector store (highest cosine similarity first)
    for i, p in enumerate(chunks[:top_passages]):
        did = f"d{i+1}"
        ev_list.append({
            "id": did,
            "text": p["text"][:600],
            "kind": "passage",
            "authority": 0.8,
            "domain": p.get("domain") or "bank-documents",
            "url": p.get("url", ""),
            "score": p.get("score", 0.0),
        })

    # Add claims
    for i, c in enumerate(deduped_claims[:top_claims]):
        cid = f"c{i+1}"
        ev_list.append({
            "id": cid,
            "text": c["text"],
            "kind": "claim",
            "authority": c.get("authority", 0.5),
            "epistemic": c.get("epistemic", "reported"),
            "domain": c.get("domain") or "bank-records",
            "url": c.get("url", ""),
            "score": sum(w in c["text"].lower() for w in q_words) * 0.1,
        })

    return ev_list



def is_evidence_adequate(question: str, ev: list[dict]) -> bool:
    """Determines whether the retrieved vector database evidence adequately covers the query."""
    if not ev:
        return False
    q_words = {w.lower() for w in re.findall(r"\b[a-zA-Z0-9]{3,}\b", question) if w.lower() not in STOPWORDS}
    if not q_words:
        return True

    # Count how many question terms appear in the top evidence
    combined_ev_text = " ".join(e["text"].lower() for e in ev[:6])
    matched_words = {w for w in q_words if w in combined_ev_text}
    match_ratio = len(matched_words) / len(q_words)

    # Check top vector score
    top_score = max((e.get("score", 0.0) for e in ev), default=0.0)
    return match_ratio >= 0.35 or top_score >= 0.08


async def answer_rag(question: str, auto_research: bool = True) -> dict[str, Any]:
    """Answers a banking query via Grounded RAG with citations, vector search, and autonomous research fallback."""
    # Ensure database is seeded with the 11 target domains if empty
    from app.knowledge import seed_data
    seed_data.seed_knowledge_base()

    ev = await retrieve_evidence(question)
    researched = False
    run_id = None

    # Check if the query is covered by pre-stored vector DB
    if auto_research and not is_evidence_adequate(question, ev):
        log.info("Query '%s' outside pre-stored knowledge base; launching autonomous research agent...", question)
        try:
            from app.knowledge.pipeline import ResearchRun
            run = ResearchRun(question)
            await run.execute()
            run_id = run.id
            researched = True
            # Re-retrieve from newly populated vector database
            ev = await retrieve_evidence(question)
        except Exception as e:
            log.warning("Autonomous research agent failed (%s); proceeding with available records", e)

    ev_map = {e["id"]: e for e in ev}
    if not ev:
        return {
            "question": question,
            "answer": [{
                "id": "a1",
                "text": "No verified records found in the knowledge base.",
                "cites": [],
                "source_info": "UnClone Verification System",
                "ruling": "no citation"
            }],
            "spoken_summary": "I could not find official verified bank records regarding this query.",
            "evidence": [],
            "covered": False,
            "verification": {"supported": 0, "partial": 0, "unsupported": 0, "no citation": 1},
            "retrieved_from": "empty_store",
            "researched": researched,
        }

    evidence_str = "\n".join(f"[{e['id']}] (Source: {e['domain']} - {e['url']}) {e['text']}" for e in ev)
    user_prompt = f"USER QUERY: {question}\n\nEVIDENCE RETRIEVED FROM VECTOR DATABASE:\n{evidence_str}"

    llm = get_llm()
    answer_items = []
    spoken_summary = ""
    covered = True

    if llm.available:
        try:
            resp = await llm.json_chat(SYSTEM_RAG, user_prompt)
            raw_answers = resp.get("answer", [])
            spoken_summary = str(resp.get("spoken_summary", "")).strip()
            covered = bool(resp.get("covered", True))

            for i, item in enumerate(raw_answers):
                cites = [_clean_cite_id(c) for c in item.get("cites", []) if _clean_cite_id(c) in ev_map]
                src_names = [f"{ev_map[c]['domain']} ({ev_map[c]['url']})" for c in cites if c in ev_map and ev_map[c].get("url")]
                src_text = f" (Source: {', '.join(src_names)})" if src_names else ""
                base_text = str(item.get("text", "")).strip()
                answer_items.append({
                    "id": f"a{i+1}",
                    "text": base_text if src_text in base_text else f"{base_text}{src_text}",
                    "cites": cites,
                    "source_info": src_names[0] if src_names else (ev[0].get("domain") or "Verified Bank Record"),
                })
        except Exception as e:
            log.warning("LLM RAG synthesis failed (%s); using extractive grounded fallback", e)

    # Extractive fallback if LLM not available or failed
    if not answer_items:
        # Rank by question term overlap and score
        q_words = [w.lower() for w in re.findall(r"\b[a-zA-Z0-9]{3,}\b", question) if w.lower() not in STOPWORDS]
        sorted_ev = sorted(
            ev,
            key=lambda x: (
                sum(w in x["text"].lower() for w in q_words),
                x.get("score", 0.0),
                x.get("authority", 0.0),
            ),
            reverse=True,
        )[:2]
        for i, item in enumerate(sorted_ev):
            src_str = f" (Source: {item['domain']} - {item['url']})" if item.get("url") else f" (Source: {item['domain']})"
            answer_items.append({
                "id": f"a{i+1}",
                "text": f"[{item['id']}]: {item['text']}{src_str}",
                "cites": [item["id"]],
                "source_info": item.get("domain") or "Official Record",
            })
        spoken_summary = sorted_ev[0]["text"] if sorted_ev else "Here is what our verified records show."
        covered = True


    # Run verification for each answer sentence against its cited evidence
    verif_counts = {"supported": 0, "partial": 0, "unsupported": 0, "no citation": 0}
    for item in answer_items:
        if not item.get("cites"):
            item["ruling"] = "no citation"
            verif_counts["no citation"] += 1
        else:
            combined_evidence = " ".join(ev_map[cid]["text"] for cid in item["cites"] if cid in ev_map)
            ruling = verify_citation(item["text"], combined_evidence)
            item["ruling"] = ruling
            verif_counts[ruling] += 1

    if not spoken_summary and answer_items:
        spoken_summary = answer_items[0]["text"]

    return {
        "question": question,
        "answer": answer_items,
        "spoken_summary": spoken_summary,
        "evidence": ev,
        "covered": covered,
        "verification": verif_counts,
        "retrieved_from": "autonomous_research_agent" if researched else "pre_stored_vector_db",
        "researched": researched,
        "run_id": run_id,
    }
