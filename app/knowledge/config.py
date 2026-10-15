"""Configuration and path settings for the Knowledge Base & Research RAG system."""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = Path(os.environ.get("DATA_DIR", str(BASE_DIR / "data"))) / "knowledge"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "knowledge.db"
CACHE_DIR = DATA_DIR / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

RUNS_DIR = DATA_DIR / "runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36 (UnClone-KnowledgeOps/1.0)"
)
API_UA = (
    "UnClone-VoiceBanking-Research/1.0 (Banking Knowledge & Fraud Intelligence RAG)"
)

SEARCH_TTL = 86400 * 3  # 3 days
PAGE_TTL = 86400 * 7  # 7 days
DEFAULT_CHUNK_SIZE = 800
DEFAULT_CHUNK_OVERLAP = 100
MAX_RESEARCH_SOURCES = 12
