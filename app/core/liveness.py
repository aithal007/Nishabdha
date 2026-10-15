"""Random-digit liveness challenge (feature 4).

Random digits reduce simple prerecorded replay. Response timing is advisory telemetry:
playback estimates and network delays cannot reliably identify interactive clones.
Digits are used (not words) because they are robust across English/Hindi/Kannada speech recognition.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field

from app.config import get_settings
from app.i18n import digits_match, extract_digits


def new_challenge_digits(n: int = 4, avoid: str = "") -> str:
    """Random digits, no immediate repeats (hard to mis-hear), never equal to the previous challenge."""
    while True:
        out = []
        for _ in range(n):
            d = secrets.choice("0123456789")
            while out and d == out[-1]:
                d = secrets.choice("0123456789")
            out.append(d)
        code = "".join(out)
        if code != avoid:
            return code


@dataclass
class AnswerEval:
    passed: bool
    heard: str
    similarity: float
    retryable: bool
    reasons: list[str] = field(default_factory=list)


def evaluate_answer(
    expected: str, transcript: str, latency_s: float | None, expired: bool
) -> AnswerEval:
    s = get_settings()
    heard = extract_digits(transcript)
    if expired:
        return AnswerEval(False, heard, 0.0, False, ["challenge expired"])
    ok, sim = digits_match(expected, heard)
    reasons: list[str] = []
    # Anti-brute-force: reciting a long digit string to 'contain' the code is not accepted
    if ok and len(heard) > len(expected) + 4:
        ok = False
        reasons.append("too many digits spoken")
    if latency_s is not None and latency_s < -0.5:
        reasons.append(
            "answer overlapped the estimated prompt playback; timing is advisory"
        )
    if not ok:
        reasons.append(f"digits did not match (heard '{heard or '-'}')")
        return AnswerEval(False, heard, sim, True, reasons)
    if latency_s is not None and latency_s > s.challenge_slow_latency_s:
        reasons.append(
            f"slow response {latency_s:.1f}s"
        )  # not a fail on its own - feeds the decision
    return AnswerEval(True, heard, sim, False, reasons)
