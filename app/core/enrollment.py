"""Voice enrollment (feature 1): quality-gated, deepfake-screened, stored for both engines."""
from __future__ import annotations

import asyncio

from sqlalchemy import select, update

from app.audio import assess, decode_any, to_wav_bytes
from app.config import get_settings
from app.core import audit
from app.db import session_scope
from app.models import Customer, VoiceEnrollment, new_id
from app.providers.base import ProviderError
from app.providers.voice_engine import get_voice_engine

PHRASES = {
    "en": [
        "My voice is my password, please verify me.",
        "I bank with Unclone Bank and I live in Bengaluru.",
        "Today I am setting up voice security for my account.",
        "Seven three nine one four six eight two zero five.",
    ],
    "hi": [
        "मेरी आवाज़ ही मेरा पासवर्ड है, कृपया मुझे सत्यापित करें।",
        "मैं अनक्लोन बैंक का ग्राहक हूँ और बेंगलुरु में रहता हूँ।",
        "आज मैं अपने खाते के लिए वॉइस सुरक्षा सेट कर रहा हूँ।",
        "सात तीन नौ एक चार छह आठ दो शून्य पाँच।",
    ],
    "kn": [
        "ನನ್ನ ಧ್ವನಿಯೇ ನನ್ನ ಪಾಸ್‌ವರ್ಡ್, ದಯವಿಟ್ಟು ನನ್ನನ್ನು ಪರಿಶೀಲಿಸಿ.",
        "ನಾನು ಅನ್‌ಕ್ಲೋನ್ ಬ್ಯಾಂಕ್ ಗ್ರಾಹಕ, ಬೆಂಗಳೂರಿನಲ್ಲಿ ವಾಸಿಸುತ್ತೇನೆ.",
        "ಇಂದು ನನ್ನ ಖಾತೆಗೆ ಧ್ವನಿ ಸುರಕ್ಷತೆ ಹೊಂದಿಸುತ್ತಿದ್ದೇನೆ.",
        "ಏಳು ಮೂರು ಒಂಬತ್ತು ಒಂದು ನಾಲ್ಕು ಆರು ಎಂಟು ಎರಡು ಸೊನ್ನೆ ಐದು.",
    ],
}


class EnrollmentError(ValueError):
    def __init__(self, message: str, details: list | None = None):
        super().__init__(message)
        self.details = details or []


async def enroll_customer(customer_id: str, raw_samples: list[bytes], actor: str) -> dict:
    s = get_settings()
    if len(raw_samples) < s.enroll_min_samples:
        raise EnrollmentError(f"need at least {s.enroll_min_samples} voice samples, got {len(raw_samples)}")
    async with session_scope() as db:
        cust = await db.get(Customer, customer_id)
        if cust is None:
            raise EnrollmentError("customer not found")

    clips, report = [], []
    for i, raw in enumerate(raw_samples):
        try:
            x = await asyncio.to_thread(decode_any, raw, max_seconds=s.vad_max_utterance_s)
        except Exception as e:
            raise EnrollmentError(f"sample {i + 1}: cannot decode audio ({e})")
        q = assess(x, s.enroll_min_seconds, s.enroll_min_rms_dbfs)
        report.append({"sample": i + 1, **q.as_dict()})
        clips.append(x)
    bad = [r for r in report if not r["ok"]]
    if bad:
        raise EnrollmentError("some samples are not good enough - please re-record them", bad)

    engine = get_voice_engine()
    # Never enroll a synthetic voice (stops an attacker from registering a clone as the 'customer')
    spoof_scores = []
    for i, x in enumerate(clips):
        res = await engine._spoof(x, [])
        p = None if res is None else res.synthetic_prob
        spoof_scores.append(p)
        if p is not None and p >= s.synthetic_hard:
            raise EnrollmentError(f"sample {i + 1} sounds synthetic (p={p:.2f}); enrollment refused", [{"sample": i + 1, "synthetic_prob": p}])

    try:
        res = await engine.enroll(customer_id, clips)
    except ProviderError as e:
        raise EnrollmentError(str(e))

    paths = []
    folder = s.data_dir / "enroll"
    for i, x in enumerate(clips):
        p = folder / f"{customer_id}_{new_id('s')}_{i + 1}.wav"
        p.write_bytes(to_wav_bytes(x))
        paths.append(str(p))

    async with session_scope() as db:
        await db.execute(update(VoiceEnrollment).where(VoiceEnrollment.customer_id == customer_id).values(active=False))
        enr = VoiceEnrollment(
            customer_id=customer_id, active=True, detectifai_ref=res.detectifai_ref, local_embedding=res.local_embedding, sample_paths=paths,
            quality={"samples": report, "spoof_scores": spoof_scores, "engines": res.source, "errors": res.detail.get("errors", []),
                     **({"mock_embedding": res.detail["mock_embedding"]} if "mock_embedding" in res.detail else {})},
        )
        db.add(enr)
        cust = await db.get(Customer, customer_id)
        cust.voice_enrolled = True
        cust.voice_locked = False
        await db.flush()
        enr_id = enr.id
    engine.forget(customer_id)
    await audit.append("voice_enrolled", {"customer_id": customer_id, "enrollment_id": enr_id, "engines": res.source, "samples": len(clips), "actor": actor})
    return {"enrollment_id": enr_id, "engines": res.source, "samples": report, "spoof_scores": spoof_scores, "warnings": res.detail.get("errors", [])}


async def enrollment_info(customer_id: str) -> dict | None:
    async with session_scope() as db:
        enr = (await db.execute(select(VoiceEnrollment).where(VoiceEnrollment.customer_id == customer_id, VoiceEnrollment.active.is_(True)))).scalars().first()
    if not enr:
        return None
    q = dict(enr.quality or {})
    q.pop("mock_embedding", None)
    return {"enrollment_id": enr.id, "created_at": enr.created_at.isoformat() + "Z", "detectifai": bool(enr.detectifai_ref), "local": enr.local_embedding is not None, "quality": q}
