"""Web discovery providers: DuckDuckGo (HTML), Wikipedia API, and SerpApi with rate pacing and caching."""

from __future__ import annotations

import asyncio
import hashlib
import html
import json
import logging
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from app.knowledge.config import BROWSER_UA, CACHE_DIR, SEARCH_TTL

log = logging.getLogger("unclone.knowledge.search")

SEARCH_CACHE_DIR = CACHE_DIR / "search"
SEARCH_CACHE_DIR.mkdir(parents=True, exist_ok=True)

_last_search_time: float = 0.0
_search_lock = asyncio.Lock()


def _cache_path(key: str) -> Path:
    h = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    return SEARCH_CACHE_DIR / f"{h}.json"


async def search_duckduckgo(query: str, max_results: int = 8) -> list[dict]:
    """DuckDuckGo HTML search without API keys."""
    async with _search_lock:
        global _last_search_time
        wait = 1.5 - (time.time() - _last_search_time)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_search_time = time.time()

    async with httpx.AsyncClient(
        timeout=15.0,
        headers={
            "User-Agent": BROWSER_UA,
            "Accept-Language": "en-US,en;q=0.9",
        },
        follow_redirects=True,
    ) as client:
        resp = await client.post(
            "https://html.duckduckgo.com/html/", data={"q": query, "kl": "in-en"}
        )
        if resp.status_code != 200:
            log.warning("DuckDuckGo returned HTTP %d for '%s'", resp.status_code, query)
            return []

    results = []
    # Try parsing via lxml
    try:
        from lxml import html as LH

        doc = LH.fromstring(resp.text)
        for div in doc.xpath('//div[contains(@class,"result__body")]'):
            a = div.xpath('.//a[contains(@class,"result__a")]')
            if not a:
                continue
            href = a[0].get("href", "")
            if "uddg=" in href:
                href = unquote(parse_qs(urlparse(href).query).get("uddg", [""])[0])
            if not href.startswith("http") or "duckduckgo.com" in href:
                continue
            snip = div.xpath('.//*[contains(@class,"result__snippet")]')
            results.append(
                {
                    "url": href,
                    "title": a[0].text_content().strip(),
                    "snippet": snip[0].text_content().strip() if snip else "",
                }
            )
            if len(results) >= max_results:
                break
    except Exception as e:
        log.warning("lxml parsing failed (%s), attempting regex fallback", e)
        # Regex fallback
        blocks = re.findall(
            r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
            resp.text,
            re.S,
        )
        for href, title_html, snip_html in blocks:
            if "uddg=" in href:
                href = unquote(parse_qs(urlparse(href).query).get("uddg", [""])[0])
            if href.startswith("http") and "duckduckgo.com" not in href:
                title = html.unescape(re.sub(r"<[^>]+>", "", title_html)).strip()
                snippet = html.unescape(re.sub(r"<[^>]+>", "", snip_html)).strip()
                results.append({"url": href, "title": title, "snippet": snippet})
            if len(results) >= max_results:
                break

    return results


async def search_wikipedia(query: str, max_results: int = 5) -> list[dict]:
    """Wikipedia OpenSearch API for definitions and background knowledge."""
    async with httpx.AsyncClient(
        timeout=10.0, headers={"User-Agent": BROWSER_UA}
    ) as client:
        resp = await client.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "opensearch",
                "search": query,
                "limit": max_results,
                "namespace": 0,
                "format": "json",
            },
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        if len(data) >= 4:
            titles = data[1]
            snippets = data[2]
            urls = data[3]
            return [
                {"url": u, "title": t, "snippet": s}
                for t, s, u in zip(titles, snippets, urls)
                if u.startswith("http")
            ]
    return []


async def search_web(
    query: str, max_results: int = 8, use_cache: bool = True
) -> list[dict]:
    """Unified search: cache -> DuckDuckGo -> Wikipedia fallback."""
    key = f"web:{query}"
    cpath = _cache_path(key)
    if use_cache and cpath.exists():
        try:
            cached = json.loads(cpath.read_text(encoding="utf-8"))
            if time.time() - cached.get("cached_at", 0) < SEARCH_TTL:
                return cached.get("results", [])
        except Exception:
            pass

    results = []
    try:
        results = await search_duckduckgo(query, max_results=max_results)
    except Exception as e:
        log.warning("DuckDuckGo search error on '%s': %s", query, e)

    if not results or len(results) < 3:
        try:
            wiki_res = await search_wikipedia(query, max_results=3)
            results.extend(wiki_res)
        except Exception as e:
            log.warning("Wikipedia fallback search error on '%s': %s", query, e)

    # De-duplicate by URL
    seen = set()
    deduped = []
    for r in results:
        u = r.get("url")
        if u and u not in seen:
            seen.add(u)
            deduped.append(r)

    if deduped:
        try:
            cpath.write_text(
                json.dumps(
                    {"cached_at": time.time(), "results": deduped}, ensure_ascii=False
                ),
                encoding="utf-8",
            )
        except Exception:
            pass

    return deduped[:max_results]
