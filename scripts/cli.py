"""Terminal tools to run the whole system BEFORE the frontend exists.

  python scripts/cli.py enroll  --customer cus_ananya --mic            (or --wav a.wav b.wav c.wav)
  python scripts/cli.py call    --customer cus_ananya --mic            (push-to-talk with Enter)
  python scripts/cli.py call    --customer cus_ananya --wav req.wav answer.wav
  python scripts/cli.py app     --customer cus_ananya                  (simulated phone: approve/deny)
  python scripts/cli.py desk                                           (fraud desk live feed)
  python scripts/cli.py bankcall --customer cus_ananya                 (bank calls the customer)

Mic + speaker need:  pip install sounddevice
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.audio import decode_any, float_to_pcm16  # noqa: E402
from app.config import get_settings  # noqa: E402

S = get_settings()
BASE = os.environ.get("UNCLONE_URL", f"http://127.0.0.1:{S.port}")
WS = BASE.replace("http", "ws", 1)
STAFF = {"X-Staff-Key": S.staff_api_key}
TOKENS = {"cus_ananya": "app-ananya-demo", "cus_rahul": "app-rahul-demo", "cus_lakshmi": "app-lakshmi-demo"}

try:
    import sounddevice as sd
except Exception:  # pragma: no cover
    sd = None


def record_until_enter(prompt: str) -> np.ndarray:
    if sd is None:
        sys.exit("pip install sounddevice  (needed for --mic)")
    input(f"{prompt}  [Enter to START]")
    frames = []
    stream = sd.InputStream(samplerate=16000, channels=1, dtype="float32", callback=lambda d, *_: frames.append(d.copy()))
    with stream:
        input("   recording... [Enter to STOP]")
    return np.concatenate(frames)[:, 0] if frames else np.zeros(0, np.float32)


def play_mp3(b64: str | None):
    if not b64 or sd is None:
        return
    try:
        import imageio_ffmpeg

        pcm = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "quiet", "-i", "pipe:0", "-ac", "1", "-ar", "24000", "-f", "f32le", "pipe:1"],
                             input=base64.b64decode(b64), capture_output=True).stdout
        sd.play(np.frombuffer(pcm, np.float32), 24000)
        sd.wait()
    except Exception as e:
        print("   (playback failed:", e, ")")


# ------------------------------------------------------------------ enroll
def cmd_enroll(a):
    with httpx.Client(base_url=BASE, timeout=300) as c:
        phrases = c.get("/api/enrollment/phrases", params={"lang": a.lang}).json()["phrases"]
        files = []
        if a.mic:
            for i, ph in enumerate(phrases[:4]):
                x = record_until_enter(f'\nSample {i + 1}: read aloud -> "{ph}"')
                q = c.post("/api/audio/quality", files={"file": ("s.wav", _wav(x), "audio/wav")}).json()
                print("   quality:", "OK" if q["ok"] else q["problems"])
                files.append(("files", (f"s{i}.wav", _wav(x), "audio/wav")))
        else:
            files = [("files", (Path(f).name, Path(f).read_bytes(), "audio/wav")) for f in a.wav]
        r = c.post(f"/api/customers/{a.customer}/enroll", headers=STAFF, files=files)
        print(json.dumps(r.json(), indent=2)[:1500])


def _wav(x):
    from app.audio import to_wav_bytes

    return to_wav_bytes(x)


# ------------------------------------------------------------------ call
async def _stream(ws, x: np.ndarray):
    for i in range(0, x.size, 1600):
        await ws.send(float_to_pcm16(x[i : i + 1600]))
        await asyncio.sleep(0.1)  # real time
    await ws.send(json.dumps({"type": "end_utterance"}))


async def cmd_call(a):
    import websockets

    async with httpx.AsyncClient(base_url=BASE, timeout=60) as c:
        j = (await c.post("/api/calls", json={"customer_id": a.customer, "lang": a.lang})).json()
    print("call:", j["call_id"])
    turn_done = asyncio.Event()

    async with websockets.connect(f"{WS}{j['ws_url']}", max_size=None) as ws:

        async def reader():
            async for raw in ws:
                m = json.loads(raw)
                ev, d = m["event"], m["data"]
                if ev == "agent_say":
                    print(f"\nAGENT [{d.get('kind')}]: {d['text']}")
                    await asyncio.to_thread(play_mp3, d.get("audio_mp3_b64"))
                    await ws.send(json.dumps({"type": "playback", "id": d["id"], "state": "ended"}))
                    turn_done.set()
                elif ev == "transcript":
                    print(f"YOU (heard): {d['text']}")
                elif ev == "call_ended":
                    print("\n[call ended]", d.get("outcome"))
                    return

        rt = asyncio.create_task(reader())
        await asyncio.wait_for(turn_done.wait(), 30)  # greeting
        if a.mic:
            while not rt.done():
                x = await asyncio.to_thread(record_until_enter, "\nSpeak")
                if x.size == 0:
                    break
                turn_done.clear()
                await _stream(ws, x)
                await asyncio.wait_for(turn_done.wait(), 120)
        else:
            for f in a.wav:
                await asyncio.sleep(0.8)
                turn_done.clear()
                print(f"\n>> sending {f}")
                await _stream(ws, decode_any(Path(f).read_bytes()))
                await asyncio.wait_for(turn_done.wait(), 120)
                await asyncio.sleep(2.0)
        await ws.send(json.dumps({"type": "hangup"}))
        await asyncio.sleep(1)
        rt.cancel()
    async with httpx.AsyncClient(base_url=BASE, timeout=60) as c:
        rep = (await c.get(f"/api/calls/{j['call_id']}/report", headers=STAFF)).json()
    print("\nVERDICT:", json.dumps(rep.get("verdict"), indent=2))


# ------------------------------------------------------------------ app / desk
async def _listen(url, on_msg):
    import websockets

    async with websockets.connect(url, max_size=None) as ws:
        async for raw in ws:
            await on_msg(json.loads(raw))


async def cmd_app(a):
    token = a.token or TOKENS.get(a.customer, "")
    hdr = {"X-App-Token": token}
    latest: dict = {}

    async def on(m):
        ev, d = m["event"], m["data"]
        print(f"\n[PHONE] {ev}: {json.dumps(d, ensure_ascii=False)[:400]}")
        if ev == "stepup_request":
            latest["id"] = d["stepup_id"]
            print("   type 'a' + Enter to APPROVE, 'd' + Enter to DENY")

    async def keys():
        async with httpx.AsyncClient(base_url=BASE, timeout=60) as c:
            while True:
                k = (await asyncio.to_thread(input)).strip().lower()
                if k in ("a", "d") and latest.get("id"):
                    r = await c.post(f"/api/app/stepups/{latest['id']}/{'approve' if k == 'a' else 'deny'}", headers=hdr)
                    print("   ->", r.json())

    await asyncio.gather(_listen(f"{WS}/ws/customer/{a.customer}?token={token}", on), keys())


async def cmd_desk(a):
    async def on(m):
        d = {k: v for k, v in m["data"].items() if k not in ("call_id",)}
        print(f"[{m['data'].get('call_id', '')[-6:]}] {m['event']}: {json.dumps(d, ensure_ascii=False)[:300]}")

    await _listen(f"{WS}/ws/dashboard?staff_key={S.staff_api_key}", on)


async def cmd_bankcall(a):
    async with httpx.AsyncClient(base_url=BASE, timeout=60) as c:
        print((await c.post("/api/bank-calls", headers=STAFF, json={"customer_id": a.customer, "reason": a.reason})).json())


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("enroll")
    e.add_argument("--customer", required=True)
    e.add_argument("--lang", default="en")
    g = e.add_mutually_exclusive_group(required=True)
    g.add_argument("--mic", action="store_true")
    g.add_argument("--wav", nargs="+")
    c = sub.add_parser("call")
    c.add_argument("--customer")
    c.add_argument("--lang", default="en")
    g = c.add_mutually_exclusive_group(required=True)
    g.add_argument("--mic", action="store_true")
    g.add_argument("--wav", nargs="+")
    ap = sub.add_parser("app")
    ap.add_argument("--customer", required=True)
    ap.add_argument("--token")
    sub.add_parser("desk")
    b = sub.add_parser("bankcall")
    b.add_argument("--customer", required=True)
    b.add_argument("--reason", default="Suspicious card activity")
    a = p.parse_args()
    if a.cmd == "enroll":
        cmd_enroll(a)
    else:
        asyncio.run({"call": cmd_call, "app": cmd_app, "desk": cmd_desk, "bankcall": cmd_bankcall}[a.cmd](a))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
