"""Web page fetcher and article text extractor with caching and fallback parsing."""
from __future__ import annotations

import asyncio
import hashlib
import html
import json
import logging
import re
import time
from pathlib import Path

import httpx

from app.knowledge.config import BROWSER_UA, CACHE_DIR, PAGE_TTL

log = logging.getLogger("unclone.knowledge.scraper")

PAGE_CACHE_DIR = CACHE_DIR / "pages"
PAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _cache_path(url: str) -> Path:
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
    return PAGE_CACHE_DIR / f"{h}.json"


def _clean_fallback_html(html_text: str) -> str:
    """Fallback text extractor if trafilatura is unavailable or fails."""
    # Strip script and style
    h = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html_text or "", flags=re.S | re.I)
    # Convert block elements to newlines
    h = re.sub(r"<(?:p|div|br|h[1-6]|li|blockquote)[^>]*>", "\n", h, flags=re.I)
    # Strip remaining tags
    h = re.sub(r"<[^>]+>", " ", h)
    # Unescape HTML entities
    text = html.unescape(h)
    # Normalize whitespaces
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if len(line) > 15)


def extract_article(html_text: str, url: str = "") -> tuple[str, str]:
    """Extracts (title, clean_text) from raw HTML."""
    m = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.S | re.I)
    title = html.unescape(m.group(1).strip()) if m else ""

    text = ""
    try:
        import trafilatura
        text = trafilatura.extract(
            html_text,
            include_comments=False,
            include_tables=True,
            favor_recall=True,
            url=url,
        ) or ""
    except Exception as e:
        log.debug("trafilatura extraction error on %s: %s", url, e)

    if not text or len(text) < 150:
        text = _clean_fallback_html(html_text)

    return title, text


async def fetch_page(url: str, force_refresh: bool = False) -> dict:
    """Fetches a web page with caching and returns structured content."""
    cpath = _cache_path(url)
    if not force_refresh and cpath.exists():
        try:
            data = json.loads(cpath.read_text(encoding="utf-8"))
            if time.time() - data.get("retrieved_at", 0) < PAGE_TTL:
                return {**data, "cached": True}
        except Exception:
            pass

    try:
        async with httpx.AsyncClient(
            timeout=12.0,
            follow_redirects=True,
            headers={
                "User-Agent": BROWSER_UA,
                "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        content_type = resp.headers.get("content-type", "").lower()
        if "text" not in content_type and "html" not in content_type and "json" not in content_type:
            return {"ok": False, "url": url, "error": f"Unsupported content-type: {content_type}", "cached": False}

        raw_html = resp.text
        title, text = extract_article(raw_html, url)
        if not text or len(text) < 100:
            return {"ok": False, "url": url, "error": "Insufficient text content extracted", "cached": False}

        result = {
            "ok": True,
            "url": url,
            "title": title or url,
            "text": text,
            "via": "direct_http",
            "retrieved_at": time.time(),
            "cached": False,
        }

        # Cache result
        try:
            cpath.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            log.warning("Failed to cache page %s: %s", url, e)

        return result
    except Exception as e:
        err_msg = f"{type(e).__name__}: {str(e)[:150]}"
        return {"ok": False, "url": url, "error": err_msg, "cached": False}
