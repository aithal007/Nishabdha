"""Audio helpers: decoding, resampling, quality checks, VAD segmentation, waveform envelopes.

Internal format everywhere: mono float32 numpy array in [-1, 1] at 16 kHz.
Network format (WebSocket): little-endian PCM16 mono, 16 kHz by default.
"""
from __future__ import annotations

import io
import subprocess
import wave
from dataclasses import dataclass, field
from math import gcd

import numpy as np

SR = 16_000


class AudioError(ValueError):
    pass


# ---------------------------------------------------------------- decoding

def pcm16_to_float(buf: bytes) -> np.ndarray:
    if len(buf) % 2:
        buf = buf[:-1]
    return np.frombuffer(buf, dtype="<i2").astype(np.float32) / 32768.0


def float_to_pcm16(x: np.ndarray) -> bytes:
    return (np.clip(x, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()


def resample(x: np.ndarray, sr_in: int, sr_out: int = SR) -> np.ndarray:
    if sr_in == sr_out or x.size == 0:
        return x.astype(np.float32, copy=False)
    from scipy.signal import resample_poly

    g = gcd(int(sr_in), int(sr_out))
    return resample_poly(x, sr_out // g, sr_in // g).astype(np.float32)


class StreamResampler:
    """Click-free streaming resampler for arbitrary packet sizes (browsers send 48 kHz in 128/2048/4096-sample
    packets). Overlap-save around scipy's polyphase filter: blocks are multiples of the decimation factor and
    each block is filtered with left/right context, so packet edges never create artefacts (which could
    otherwise look 'synthetic' to the deepfake detector). Adds ~`ctx` samples of latency (~10 ms)."""

    def __init__(self, sr_in: int, sr_out: int = SR):
        g = gcd(int(sr_in), int(sr_out))
        self.up, self.down = sr_out // g, sr_in // g
        self.ctx = self.down * max(1, 480 // self.down)  # ~10 ms of context at 48 kHz, multiple of down
        self.hist = np.zeros(self.ctx, np.float32)
        self.buf = np.zeros(0, np.float32)

    def feed(self, x: np.ndarray) -> np.ndarray:
        from scipy.signal import resample_poly

        self.buf = np.concatenate([self.buf, x.astype(np.float32)])
        usable = len(self.buf) - self.ctx  # keep ctx samples of look-ahead
        n = (usable // self.down) * self.down
        if n <= 0:
            return np.zeros(0, np.float32)
        block = self.buf[:n]
        look = self.buf[n : n + self.ctx]
        seg = np.concatenate([self.hist, block, look])
        y = resample_poly(seg, self.up, self.down)
        a = self.ctx * self.up // self.down
        out = y[a : a + n * self.up // self.down].astype(np.float32)
        self.hist = seg[len(self.hist) + n - self.ctx : len(self.hist) + n]
        self.buf = self.buf[n:]
        return out


def _ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # pragma: no cover
        return "ffmpeg"


def decode_any(data: bytes) -> np.ndarray:
    """Decode wav/mp3/webm/ogg/m4a bytes -> 16 kHz mono float32."""
    if not data:
        raise AudioError("empty audio")
    # Fast path: WAV via soundfile (no subprocess)
    try:
        import soundfile as sf

        x, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
        return resample(x.mean(axis=1), sr)
    except Exception:
        pass
    try:
        proc = subprocess.run(
            [_ffmpeg_exe(), "-v", "error", "-i", "pipe:0", "-ac", "1", "-ar", str(SR), "-f", "f32le", "pipe:1"],
            input=data,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise AudioError(f"ffmpeg failed: {e}") from e
    if proc.returncode != 0 or not proc.stdout:
        raise AudioError("could not decode audio (unsupported or corrupt file)")
    return np.frombuffer(proc.stdout, dtype=np.float32).copy()


def to_wav_bytes(x: np.ndarray, sr: int = SR) -> bytes:
    bio = io.BytesIO()
    with wave.open(bio, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(float_to_pcm16(x))
    return bio.getvalue()


# ---------------------------------------------------------------- quality

@dataclass
class Quality:
    duration_s: float
    speech_s: float
    rms_dbfs: float
    clipping_ratio: float
    snr_db: float
    ok: bool
    problems: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in self.__dict__.items()}


def rms_dbfs(x: np.ndarray) -> float:
    if x.size == 0:
        return -120.0
    r = float(np.sqrt(np.mean(np.square(x, dtype=np.float64))))
    return 20 * np.log10(max(r, 1e-6))


def assess(x: np.ndarray, min_speech_s: float = 1.0, min_rms_dbfs: float = -45.0) -> Quality:
    dur = x.size / SR
    voiced = speech_mask(x)
    speech_s = float(voiced.sum()) * FRAME_MS / 1000.0
    level = rms_dbfs(x)
    clip = float(np.mean(np.abs(x) > 0.98)) if x.size else 0.0
    # SNR estimate: energy of voiced frames vs unvoiced frames
    frames = _frames(x)
    if frames.size and voiced.any() and (~voiced).any():
        e = np.mean(frames**2, axis=1) + 1e-10
        snr = float(10 * np.log10(e[voiced].mean() / e[~voiced].mean()))
    else:
        snr = 30.0 if voiced.any() else 0.0
    problems = []
    if speech_s < min_speech_s:
        problems.append(f"too little speech ({speech_s:.1f}s < {min_speech_s:.1f}s)")
    if level < min_rms_dbfs:
        problems.append("too quiet - move closer to the microphone")
    if clip > 0.01:
        problems.append("audio is clipping - speak softer or lower mic gain")
    if snr < 6:
        problems.append("too noisy")
    return Quality(dur, speech_s, level, clip, snr, not problems, problems)


# ---------------------------------------------------------------- VAD

FRAME_MS = 30
FRAME_LEN = SR * FRAME_MS // 1000  # 480 samples


def _frames(x: np.ndarray) -> np.ndarray:
    n = x.size // FRAME_LEN
    return x[: n * FRAME_LEN].reshape(n, FRAME_LEN) if n else np.zeros((0, FRAME_LEN), np.float32)


class _Vad:
    """webrtcvad if available, else adaptive energy VAD."""

    def __init__(self, aggressiveness: int = 2):
        self.thresh_db = -42.0
        try:
            import webrtcvad

            self._v = webrtcvad.Vad(aggressiveness)
        except Exception:  # pragma: no cover
            self._v = None

    def is_speech(self, frame: np.ndarray) -> bool:
        if rms_dbfs(frame) < -55:  # digital silence never counts
            return False
        if self._v is not None:
            try:
                return self._v.is_speech(float_to_pcm16(frame), SR)
            except Exception:
                pass
        return rms_dbfs(frame) > self.thresh_db


def speech_mask(x: np.ndarray, aggressiveness: int = 2) -> np.ndarray:
    v = _Vad(aggressiveness)
    fr = _frames(x)
    return np.array([v.is_speech(f) for f in fr], dtype=bool)


@dataclass
class Utterance:
    audio: np.ndarray
    t_start: float  # seconds since stream start
    t_end: float
    speech_onset: float  # first voiced frame time


class StreamSegmenter:
    """Feeds raw PCM, emits (a) complete utterances (end-of-speech) and (b) fixed-size speech-only chunks
    for continuous voice checks. Pure, synchronous and cheap (~0.05 ms per frame)."""

    def __init__(self, aggressiveness=2, end_silence_ms=700, min_utt_ms=300, max_utt_s=15.0, chunk_s=3.0, min_chunk_s=1.5):
        self.vad = _Vad(aggressiveness)
        self.end_frames = max(1, end_silence_ms // FRAME_MS)
        self.min_utt_frames = max(1, min_utt_ms // FRAME_MS)
        self.max_utt_frames = int(max_utt_s * 1000 // FRAME_MS)
        self.chunk_frames = int(chunk_s * 1000 // FRAME_MS)
        self.min_chunk_frames = int(min_chunk_s * 1000 // FRAME_MS)
        self._pending = np.zeros(0, np.float32)
        self.frames_seen = 0
        # utterance state
        self._utt: list[np.ndarray] = []
        self._utt_start = 0
        self._utt_voiced = 0
        self._onset: int | None = None
        self._silence = 0
        self._preroll: list[np.ndarray] = []
        # chunk state
        self._chunk: list[np.ndarray] = []
        self._chunk_t0: float | None = None
        self.last_voiced_t: float | None = None

    @property
    def now(self) -> float:
        return self.frames_seen * FRAME_MS / 1000.0

    def feed(self, x: np.ndarray) -> tuple[list[Utterance], list[tuple[np.ndarray, float, float]]]:
        utts: list[Utterance] = []
        chunks: list[tuple[np.ndarray, float, float]] = []
        buf = np.concatenate([self._pending, x]) if self._pending.size else x
        n = buf.size // FRAME_LEN
        self._pending = buf[n * FRAME_LEN :].copy()
        for i in range(n):
            f = buf[i * FRAME_LEN : (i + 1) * FRAME_LEN]
            t = self.frames_seen * FRAME_MS / 1000.0
            self.frames_seen += 1
            voiced = self.vad.is_speech(f)
            # ---- continuous check chunks (speech frames only)
            if voiced:
                self.last_voiced_t = t
                if self._chunk_t0 is None:
                    self._chunk_t0 = t
                self._chunk.append(f)
                if len(self._chunk) >= self.chunk_frames:
                    chunks.append((np.concatenate(self._chunk), self._chunk_t0, t + FRAME_MS / 1000))
                    self._chunk, self._chunk_t0 = [], None
            # ---- utterances
            if self._utt:
                self._utt.append(f)
                if voiced:
                    self._utt_voiced += 1
                    self._silence = 0
                else:
                    self._silence += 1
                too_long = len(self._utt) >= self.max_utt_frames
                if self._silence >= self.end_frames or too_long:
                    u = self._close_utt()
                    if u is not None:
                        utts.append(u)
            elif voiced:
                self._utt = self._preroll + [f]
                self._utt_start = self.frames_seen - len(self._utt)
                self._utt_voiced = 1
                self._onset = self.frames_seen - 1
                self._silence = 0
                self._preroll = []
            else:
                self._preroll = (self._preroll + [f])[-10:]  # 300 ms pre-roll so first syllable is kept
        return utts, chunks

    def _close_utt(self) -> Utterance | None:
        frames, voiced = self._utt, self._utt_voiced
        start, onset = self._utt_start, self._onset or self._utt_start
        self._utt, self._utt_voiced, self._silence, self._onset = [], 0, 0, None
        if voiced < self.min_utt_frames:
            return None
        audio = np.concatenate(frames)
        t0 = start * FRAME_MS / 1000.0
        return Utterance(audio, t0, t0 + len(frames) * FRAME_MS / 1000.0, onset * FRAME_MS / 1000.0)

    def reset_utterance(self) -> None:
        self._utt, self._utt_voiced, self._silence, self._onset, self._preroll = [], 0, 0, None, []

    def flush(self) -> tuple[list[Utterance], list[tuple[np.ndarray, float, float]]]:
        """Force-close the current utterance (client said end_of_utterance / push-to-talk released)."""
        utts, chunks = [], []
        if self._utt:
            u = self._close_utt()
            if u is not None:
                utts.append(u)
        if len(self._chunk) >= self.min_chunk_frames and self._chunk_t0 is not None:
            chunks.append((np.concatenate(self._chunk), self._chunk_t0, self.now))
            self._chunk, self._chunk_t0 = [], None
        return utts, chunks


# ---------------------------------------------------------------- visuals

def envelope(x: np.ndarray, bins: int = 200) -> list[float]:
    """Peak envelope for waveform drawing (0..1)."""
    if x.size == 0:
        return [0.0] * bins
    idx = np.linspace(0, x.size, bins + 1, dtype=int)
    out = [float(np.max(np.abs(x[a:b]))) if b > a else 0.0 for a, b in zip(idx[:-1], idx[1:], strict=False)]
    m = max(out) or 1.0
    return [round(v / m, 4) for v in out]
