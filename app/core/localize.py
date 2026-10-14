"""Translate dynamic English sentences (action results) to Hindi/Kannada with the LLM, guarded:
every number in the English must survive in the translation, otherwise we speak English.
(Amounts and card digits must never be mistranslated.)"""
from __future__ import annotations

import logging
import re
from collections import OrderedDict

from app.providers.llm import get_llm

log = logging.getLogger("unclone.localize")
_cache: OrderedDict[tuple[str, str], str] = OrderedDict()
_NAMES = {"hi": "Hindi", "kn": "Kannada"}


def _numbers(s: str) -> list[str]:
    return sorted(re.sub(r"[,\s]", "", n) for n in re.findall(r"\d[\d,]*", s))


async def localize(text: str, lang: str) -> str:
    if lang not in _NAMES or not text.strip():
        return text
    key = (lang, text)
    if key in _cache:
        return _cache[key]
    llm = get_llm()
    if not llm.available:
        return text
    try:
        out = await llm.json_chat(
            f"Translate the bank assistant sentence into natural spoken {_NAMES[lang]}. Keep every number exactly as digits (do not convert to words). Return JSON {{\"text\": str}}.",
            f"<<<{text}>>>",
        )
        tr = str(out.get("text") or "").strip()
        tr_native = tr.translate(str.maketrans("०१२३४५६७८९೦೧೨೩೪೫೬೭೮೯", "01234567890123456789"))
        if not tr or _numbers(tr_native) != _numbers(text):
            log.warning("translation dropped/changed numbers, speaking English")
            return text
        _cache[key] = tr
        if len(_cache) > 500:
            _cache.popitem(last=False)
        return tr
    except Exception as e:
        log.warning("localize failed: %s", e)
        return text
