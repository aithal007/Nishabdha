"""Day-1 tool: verify the DetectifAI settings in .env against their real API.

    python scripts/check_detectifai.py --audio my_voice.wav [--audio2 other_voice.wav] [--raw]

Calls enroll -> verify(same clip) -> verify(other clip) -> deepfake, printing the RAW JSON so you can set
DETECTIFAI_*_PATH settings correctly, then the parsed scores the policy will see.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.audio import decode_any  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.providers.detectifai import DetectifAIClient  # noqa: E402


async def main(a):
    s = get_settings()
    if not s.detectifai_base_url:
        sys.exit("DETECTIFAI_BASE_URL is empty in .env")
    cl = DetectifAIClient(s)
    x = decode_any(Path(a.audio).read_bytes())
    x2 = decode_any(Path(a.audio2).read_bytes()) if a.audio2 else None
    print(f"Base URL: {s.detectifai_base_url}  mode={s.detectifai_verify_mode} upload={s.detectifai_upload_mode}")

    async def raw(path, audio, fields, ref=None):
        try:
            return await cl._request(path, audio, fields, ref_audio=ref)
        except Exception as e:
            return {"ERROR": str(e)}

    print("\n--- enroll raw ---")
    ref_id = "check_" + Path(a.audio).stem
    if s.detectifai_verify_mode == "enrolled_id":
        r = await raw(s.detectifai_enroll_path, x, {s.detectifai_speaker_field: ref_id})
        print(json.dumps(r, indent=2)[:2000])
        try:
            ref_id, _ = await cl.enroll(ref_id, x)
        except Exception as e:
            print("parse error:", e)
    else:
        print("(pair mode - no enrollment call)")

    print("\n--- verify (same clip) raw ---")
    fields = {} if s.detectifai_verify_mode == "pair" else {s.detectifai_speaker_field: ref_id}
    print(json.dumps(await raw(s.detectifai_verify_path, x, fields, x if s.detectifai_verify_mode == "pair" else None), indent=2)[:2000])
    try:
        r = await cl.verify(ref_id, x, x)
        print(f"PARSED speaker prob = {r.prob:.3f} (raw {r.raw})  <- should be HIGH")
    except Exception as e:
        print("PARSE FAILED:", e, "\n-> fix DETECTIFAI_VERIFY_SCORE_PATH / _MAX")
    if x2 is not None:
        try:
            r = await cl.verify(ref_id, x2, x)
            print(f"PARSED speaker prob (other clip) = {r.prob:.3f}  <- should be LOW if a different person")
        except Exception as e:
            print("verify other failed:", e)

    print("\n--- deepfake raw ---")
    print(json.dumps(await raw(s.detectifai_deepfake_path, x, {}), indent=2)[:2000])
    try:
        d = await cl.deepfake(x)
        print(f"PARSED synthetic prob = {d.synthetic_prob:.3f}  <- should be LOW for a real recording")
        print("   (if it is HIGH for real voices, set DETECTIFAI_DEEPFAKE_SCORE_IS_REAL=true)")
    except Exception as e:
        print("PARSE FAILED:", e, "\n-> fix DETECTIFAI_DEEPFAKE_SCORE_PATH")
    await cl.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--audio", required=True)
    p.add_argument("--audio2")
    asyncio.run(main(p.parse_args()))
