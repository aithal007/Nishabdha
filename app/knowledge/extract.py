"""Topic-agnostic and banking-aware claim extraction and source authority scoring."""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlparse

# Source authority weights
SOURCE_TYPES = {
    "official": (1.0, "Official / Government / Regulator (RBI/Gov/CERT-In)"),
    "structured": (0.95, "Structured Open Data / Registry"),
    "reference": (0.85, "Encyclopedia / Reference (Wikipedia)"),
    "news": (0.75, "News / Financial Publication"),
    "research": (0.75, "Security Research / Analyst Report"),
    "company": (0.60, "Bank / Corporate Website"),
    "blog": (0.50, "Blog / Technical Article"),
    "forum": (0.45, "Discussion / Community Forum"),
    "review": (0.45, "Consumer Review Platform"),
    "commercial": (0.30, "Commercial Listing / Portal"),
}

FORUM = (
    "reddit.com",
    "quora.com",
    "stackexchange.com",
    "news.ycombinator.com",
    "teamblind.com",
)
REVIEW = (
    "trustpilot.",
    "g2.com",
    "capterra.",
    "glassdoor.",
    "ambitionbox.",
    "mouthshut.",
    "google.com/maps",
    "justdial.",
)
NEWS = (
    "reuters.",
    "bloomberg.",
    "economictimes.",
    "livemint.",
    "business-standard.",
    "moneycontrol.",
    "thehindu",
    "hindustantimes.",
    "techcrunch.",
    "inc42.",
    "yourstory.",
    "entrackr.",
    "forbes.",
    "ft.com",
    "wsj.com",
    "cnbc.",
    "bbc.",
    "nytimes.",
    "financialexpress.",
    "indianexpress.",
    "timesofindia.",
    "businessinsider.",
)
RESEARCH = (
    "statista.",
    "mordorintelligence.",
    "grandviewresearch.",
    "marketsandmarkets.",
    "mckinsey.",
    "bcg.com",
    "deloitte.",
    "pwc.",
    "kpmg.",
    "ey.com",
    "gartner.",
    "tracxn.",
    "crunchbase.",
    "cert-in.org.in",
    "cisa.gov",
)
COMMERCIAL = ("amazon.", "flipkart.", "indiamart.", "coupon", "deals")
SKIP_FETCH = (
    "youtube.com",
    "youtu.be",
    "instagram.com",
    "facebook.com",
    "twitter.com",
    "x.com",
    "tiktok.com",
    "linkedin.com",
)


def classify_source(url: str) -> str:
    """Classifies source domain into authority tier."""
    u = (url or "").lower()
    host = urlparse(u).netloc
    official = {
        "rbi.org.in",
        "sebi.gov.in",
        "cert-in.org.in",
        "cybercrime.gov.in",
        "cisa.gov",
        "fbi.gov",
        "npci.org.in",
    }
    host = urlparse(u).hostname or ""
    if any(host == domain or host.endswith("." + domain) for domain in official):
        return "official"
    if "wikipedia.org" in host or "britannica.com" in host or "wikidata.org" in host:
        return "reference"
    for kind, keys in (
        ("review", REVIEW),
        ("forum", FORUM),
        ("research", RESEARCH),
        ("news", NEWS),
        ("commercial", COMMERCIAL),
    ):
        if any(k in u for k in keys):
            return kind
    return "company" if "bank" in host or "corp" in host else "blog"


# Language and semantic cues
RISK_CUES = re.compile(
    r"\b(?:risk\w*|challeng\w*|concern\w*|problem\w*|issue\w*|shut ?down|loss(?:es)?|fail\w*|declin\w*|"
    r"struggl\w*|ban(?:ned)?|regulat\w*|penalt\w*|lawsuit|fraud|scam|phishing|deepfake|clone|unauthorized|"
    r"breach|stolen|impostor|extortion|threat\w*|cybercrime|digital arrest|vishing|sim swap)\b",
    re.I,
)
OPPORTUNITY_CUES = re.compile(
    r"\b(?:opportunit\w*|growth|grow(?:ing|s)?|demand|untapped|gap|expan\w*|surg\w*|rising|increas\w*|"
    r"potential|incentive\w*|subsid\w*|adoption|protect\w*|safeguard|refund|zero liability|reversal)\b",
    re.I,
)
FACT_CUES = re.compile(
    r"\b(?:founded|launched|established|raised|guideline|directive|circular|section|act|mandate|rule|"
    r"hours|timings|ifsc|interest rate|deposit|limit|rupees|rs\.?|inr|percent|%|(?:19|20)\d{2}|within \d+ days)\b",
    re.I,
)
OPINION_CUES = re.compile(
    r"\b(?:i think|i feel|in my (?:opinion|experience)|imo|we (?:tried|used)|i (?:tried|used)|personally|recommend)\b",
    re.I,
)
PRICE_RE = re.compile(
    r"(?:â‚¹|rs\.?|inr|\$|usd|â‚¬|Â£)\s?\d[\d,.]*(?:\s?(?:k|lakh|crore|cr|mn|million|bn|billion))?|\d[\d,.]*\s?(?:rupees|dollars)",
    re.I,
)
POSITIVE = re.compile(
    r"\b(?:good|great|safe|secure|protect\w*|reliable|verified|approved|authorized|authentic)\b",
    re.I,
)
NEGATIVE = re.compile(
    r"\b(?:bad|poor|fake|scam|fraud|unreliable|broken|danger\w*|unauthorized|stolen|loss)\b",
    re.I,
)
BOILER = re.compile(
    r"cookie|subscribe|newsletter|affiliate|sign up|log in|privacy policy|all rights reserved|click here|disclaimer|copyright",
    re.I,
)

CITATION = re.compile(
    r"doi\.org|\bdoi:|https?://|www\.|\bet al\b|\bpp?\.\s?\d|\bvol\.|\d+\(\d+\)|\(\d{4}[a-z]?\)\.?\s*$|^\W*\(\d{4}\)",
    re.I,
)
AUTHORS = re.compile(r"^[A-Z][\w'â€™-]+,\s(?:[A-Z]\.\s?)+")


def is_citation(s: str) -> bool:
    return bool(CITATION.search(s) or AUTHORS.search(s))


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def split_sentences(text: str) -> list[tuple[int, str]]:
    """Splits article text into (paragraph_index, sentence) tuples, excluding boilerplate and citations."""
    out = []
    paragraphs = re.split(r"\n\s*\n|\n", text or "")
    for para_i, para in enumerate(paragraphs):
        para = para.strip()
        if not para or BOILER.search(para):
            continue
        sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'â€œâ‚¹])", para)
        for s in sentences:
            s = s.strip(" -â€¢*#\t")
            if 25 <= len(s) <= 450 and not s.endswith("?") and not is_citation(s):
                out.append((para_i, s))
    return out


def _epistemic(kind: str, source_type: str) -> str:
    if kind == "fact":
        return (
            "reported"
            if source_type in ("official", "structured")
            else "reference"
            if source_type == "reference"
            else "reported"
        )
    return (
        "reported"
        if source_type in ("official", "reference", "news", "research")
        else "opinion"
    )


def analyse_claim(sentence: str, source_type: str) -> dict | None:
    """Extracts claim attributes: kind (fact/risk/opportunity/opinion), epistemic tag, sentiment, prices."""
    if BOILER.search(sentence):
        return None
    prices = PRICE_RE.findall(sentence)
    risk = bool(RISK_CUES.search(sentence))
    opp = bool(OPPORTUNITY_CUES.search(sentence))
    fact = bool(FACT_CUES.search(sentence) or prices)
    opin = bool(OPINION_CUES.search(sentence))
    pos = len(POSITIVE.findall(sentence))
    neg = len(NEGATIVE.findall(sentence))

    if not (risk or opp or fact or opin or pos or neg):
        return None

    if risk:
        kind = "risk"
    elif fact:
        kind = "fact"
    elif opp:
        kind = "opportunity"
    else:
        kind = "opinion"

    authority, label = SOURCE_TYPES.get(source_type, (0.5, "Standard"))
    epistemic = _epistemic(kind, source_type)
    sentiment = (pos > neg) - (neg > pos)
    if kind == "risk" and sentiment >= 0:
        sentiment = -1

    return {
        "kind": kind,
        "epistemic": epistemic,
        "authority": authority,
        "sentiment": sentiment,
        "prices": prices,
        "source_type": source_type,
    }
