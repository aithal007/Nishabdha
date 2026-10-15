"""DetectifAI adapter.

Their API spec is only revealed at the event, so everything (paths, field names, auth, where the score
lives in the JSON, score scale and direction) is configured from .env - see the DETECTIFAI_* settings.
Day-1 job: read their docs, fill .env, run `python scripts/check_detectifai.py`. Only if their API is
shaped very differently does `_request()` need editing.
"""

from __future__ import annotations

import base64
import json
import math
import time
from typing import Any

import httpx
import numpy as np

from app.audio import to_wav_bytes
from app.config import Settings
from app.providers.base import ProviderError, SpeakerResult, SpoofResult, clamp01


def json_path(obj: Any, path: str) -> Any:
    """'data.result.score' / 'results.0.prob' -> value."""
    cur = obj
    for part in [p for p in path.split(".") if p]:
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError) as e:
                raise ProviderError(f"path {path!r}: bad list index {part!r}") from e
        elif isinstance(cur, dict):
            if part not in cur:
                raise ProviderError(
                    f"path {path!r}: key {part!r} missing; got keys {list(cur)[:10]}"
                )
            cur = cur[part]
        else:
            raise ProviderError(
                f"path {path!r}: cannot descend into {type(cur).__name__}"
            )
    return cur


def _to_float(v: Any) -> float:
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, str):
        v = v.strip().rstrip("%")
    try:
        result = float(v)
        if not math.isfinite(result):
            raise ValueError("non-finite score")
        return result
    except (TypeError, ValueError) as e:
        raise ProviderError(f"score is not numeric: {v!r}") from e


class DetectifAIClient:
    def __init__(self, s: Settings):
        self.s = s
        self._client: httpx.AsyncClient | None = None
        try:
            self.extra = (
                json.loads(s.detectifai_extra_json)
                if s.detectifai_extra_json.strip()
                else {}
            )
        except json.JSONDecodeError as e:
            raise ProviderError(f"DETECTIFAI_EXTRA_JSON is not valid JSON: {e}") from e

    @property
    def configured(self) -> bool:
        return bool(self.s.detectifai_base_url)

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {}
            if self.s.detectifai_api_key:
                scheme = self.s.detectifai_auth_scheme.strip()
                headers[self.s.detectifai_auth_header] = (
                    f"{scheme} {self.s.detectifai_api_key}".strip()
                )
            self._client = httpx.AsyncClient(
                base_url=self.s.detectifai_base_url.rstrip("/"),
                headers=headers,
                timeout=httpx.Timeout(self.s.voice_timeout_s, connect=4.0),
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        path: str,
        audio: np.ndarray,
        fields: dict[str, Any],
        ref_audio: np.ndarray | None = None,
    ) -> dict:
        if not self.configured:
            raise ProviderError("DetectifAI not configured (DETECTIFAI_BASE_URL empty)")
        s = self.s
        fields = {**self.extra, **{k: v for k, v in fields.items() if v is not None}}
        wav = to_wav_bytes(audio)
        if s.detectifai_upload_mode == "multipart":
            files = {s.detectifai_audio_field: ("audio.wav", wav, "audio/wav")}
            if ref_audio is not None:
                files[s.detectifai_reference_field] = (
                    "reference.wav",
                    to_wav_bytes(ref_audio),
                    "audio/wav",
                )
            data = {
                k: (json.dumps(v) if isinstance(v, (dict, list)) else str(v))
                for k, v in fields.items()
            }
            resp = await self._http().post(path, files=files, data=data)
        else:
            body = {**fields, s.detectifai_audio_field: base64.b64encode(wav).decode()}
            if ref_audio is not None:
                body[s.detectifai_reference_field] = base64.b64encode(
                    to_wav_bytes(ref_audio)
                ).decode()
            resp = await self._http().post(path, json=body)
        if resp.status_code >= 400:
            raise ProviderError(
                f"DetectifAI {path} HTTP {resp.status_code}: {resp.text[:300]}"
            )
        try:
            return resp.json()
        except ValueError as e:
            raise ProviderError(
                f"DetectifAI {path} returned non-JSON: {resp.text[:200]}"
            ) from e

    # ------------------------------------------------------------------ API
    async def enroll(
        self, customer_id: str, audio: np.ndarray
    ) -> tuple[str | None, dict]:
        """Returns (speaker reference id, raw response). In pair mode there is nothing to enroll remotely."""
        if self.s.detectifai_verify_mode == "pair":
            return None, {"mode": "pair"}
        data = await self._request(
            self.s.detectifai_enroll_path,
            audio,
            {self.s.detectifai_speaker_field: customer_id},
        )
        try:
            ref = str(json_path(data, self.s.detectifai_enroll_id_path))
        except ProviderError:
            ref = customer_id  # many APIs just use the id we pass
        return ref, data

    async def verify(
        self, ref: str | None, audio: np.ndarray, ref_audio: np.ndarray | None = None
    ) -> SpeakerResult:
        t0 = time.perf_counter()
        if self.s.detectifai_verify_mode == "pair":
            if ref_audio is None:
                raise ProviderError("pair mode needs enrollment reference audio")
            data = await self._request(
                self.s.detectifai_verify_path, audio, {}, ref_audio=ref_audio
            )
        else:
            if not ref:
                raise ProviderError("no DetectifAI speaker reference for this customer")
            data = await self._request(
                self.s.detectifai_verify_path,
                audio,
                {self.s.detectifai_speaker_field: ref},
            )
        raw = _to_float(json_path(data, self.s.detectifai_verify_score_path))
        if (
            self.s.detectifai_verify_score_max <= 0
            or not 0 <= raw <= self.s.detectifai_verify_score_max
        ):
            raise ProviderError("speaker score outside configured range")
        prob = clamp01(raw / (self.s.detectifai_verify_score_max or 1.0))
        return SpeakerResult(
            prob=prob,
            raw=raw,
            source="detectifai",
            latency_ms=int((time.perf_counter() - t0) * 1000),
        )

    async def deepfake(self, audio: np.ndarray) -> SpoofResult:
        t0 = time.perf_counter()
        data = await self._request(self.s.detectifai_deepfake_path, audio, {})
        raw = _to_float(json_path(data, self.s.detectifai_deepfake_score_path))
        if (
            self.s.detectifai_deepfake_score_max <= 0
            or not 0 <= raw <= self.s.detectifai_deepfake_score_max
        ):
            raise ProviderError("authenticity score outside configured range")
        p = clamp01(raw / (self.s.detectifai_deepfake_score_max or 1.0))
        if self.s.detectifai_deepfake_score_is_real:
            p = 1.0 - p
        return SpoofResult(
            synthetic_prob=p,
            source="detectifai",
            latency_ms=int((time.perf_counter() - t0) * 1000),
            detail={"raw": raw},
        )
