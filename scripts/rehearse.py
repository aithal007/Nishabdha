"""Isolated cloud-only rehearsal; never touches the configured demo database.

Usage: .venv/Scripts/python scripts/rehearse.py --duration 1800
Reports real HTTP/WebSocket latency and process RSS, not model accuracy.
"""

import argparse
import asyncio
import ctypes
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import websockets


def process_tree(pid):
    """Include venv launcher children; measuring the launcher alone underreports RSS."""
    if sys.platform != "win32":
        children = Path(f"/proc/{pid}/task/{pid}/children")
        return [pid] + [
            descendant
            for child in children.read_text().split()
            for descendant in process_tree(int(child))
        ]
    from ctypes import wintypes

    class Entry(ctypes.Structure):
        _fields_ = [
            ("size", wintypes.DWORD),
            ("usage", wintypes.DWORD),
            ("pid", wintypes.DWORD),
            ("heap", ctypes.c_size_t),
            ("module", wintypes.DWORD),
            ("threads", wintypes.DWORD),
            ("parent", wintypes.DWORD),
            ("priority", wintypes.LONG),
            ("flags", wintypes.DWORD),
            ("exe", wintypes.WCHAR * 260),
        ]

    dll = ctypes.WinDLL("kernel32", use_last_error=True)
    dll.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    dll.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    dll.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    dll.CloseHandle.argtypes = [wintypes.HANDLE]
    snapshot = dll.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise OSError("Cannot enumerate rehearsal process tree")
    entries = []
    try:
        entry = Entry()
        entry.size = ctypes.sizeof(entry)
        found = dll.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            entries.append((entry.pid, entry.parent))
            found = dll.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        dll.CloseHandle(snapshot)
    pids = {pid}
    while True:
        children = {child for child, parent in entries if parent in pids}
        if children <= pids:
            return list(pids)
        pids |= children


def single_rss_bytes(pid, peak=False):
    if sys.platform == "win32":
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
                (name, ctypes.c_size_t)
                for name in (
                    "peak",
                    "working",
                    "quota_peak",
                    "quota",
                    "pool_peak",
                    "pool",
                    "page",
                    "page_peak",
                )
            ]

        dll = ctypes.WinDLL("kernel32", use_last_error=True)
        dll.OpenProcess.restype = wintypes.HANDLE
        dll.CloseHandle.argtypes = [wintypes.HANDLE]
        psapi = ctypes.WinDLL("psapi")
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        handle = dll.OpenProcess(0x0400 | 0x0010, False, pid)
        if not handle:
            raise OSError("Cannot inspect rehearsal server memory")
        try:
            c = Counters()
            c.cb = ctypes.sizeof(c)
            if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(c), c.cb):
                raise OSError("Cannot read rehearsal server memory")
            return c.peak if peak else c.working
        finally:
            dll.CloseHandle(handle)
    return int(Path(f"/proc/{pid}/statm").read_text().split()[1]) * os.sysconf(
        "SC_PAGE_SIZE"
    )


def rss_bytes(pid):
    return sum(single_rss_bytes(child) for child in process_tree(pid))


def peak_rss_bytes(pid):
    return sum(single_rss_bytes(child, peak=True) for child in process_tree(pid))


async def run(args):
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="nishabdha_rehearsal_") as directory:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = {
            **os.environ,
            "DATA_DIR": directory,
            "DATABASE_URL": "",
            "APP_ENV": "demo",
            "VOICE_PRIMARY": "detectifai",
            "VOICE_FALLBACK": "none",
            "DETECTIFAI_BASE_URL": "",
            "STT_PROVIDER": "none",
            "STT_FALLBACK": "none",
            "TTS_PROVIDER": "none",
            "LLM_PROVIDER": "none",
            "STAFF_API_KEY": secrets.token_urlsafe(24),
            "AUDIT_HMAC_SECRET": secrets.token_urlsafe(32),
            "RENDER": "true",
            "NISHABHA_ALLOW_LOCAL_MODELS": "false",
            "PORT": str(port),
        }
        base = f"http://127.0.0.1:{port}"
        started = time.monotonic()
        samples, latencies = [], []
        with open(Path(directory) / "server.log", "w", encoding="utf-8") as log:  # noqa: ASYNC230 -- CLI setup, outside measured turns
            process = await asyncio.to_thread(
                subprocess.Popen,
                [sys.executable, "run.py"],
                cwd=root,
                env=env,
                stdout=log,
                stderr=log,
            )
            try:
                async with httpx.AsyncClient(base_url=base, timeout=20) as client:
                    for _ in range(90):
                        if process.poll() is not None:
                            raise RuntimeError("Rehearsal server exited during startup")
                        try:
                            if (await client.get("/health")).status_code == 200:
                                break
                        except httpx.HTTPError:
                            pass
                        await asyncio.sleep(1)
                    else:
                        raise RuntimeError("Rehearsal server did not become healthy")
                    initial = (
                        await client.get(
                            "/api/app/me", headers={"X-App-Token": "app-ananya-demo"}
                        )
                    ).json()
                    calls = [
                        (
                            await client.post(
                                "/api/calls",
                                json={"customer_id": "cus_ananya", "greet": False},
                            )
                        ).json()
                        for _ in range(3)
                    ]
                    sockets = []
                    try:
                        for call in calls:
                            sockets.append(
                                await websockets.connect(
                                    f"ws://127.0.0.1:{port}" + call["ws_url"]
                                )
                            )
                            await sockets[-1].recv()  # ready
                        if args.preload_audio_seconds:
                            print(
                                f"Sending {args.preload_audio_seconds}s of synthetic silence per session to exercise bounded recording buffers (accelerated, not real-time audio).",
                                flush=True,
                            )
                            for _ in range(args.preload_audio_seconds):
                                await asyncio.gather(
                                    *(ws.send(bytes(32000)) for ws in sockets)
                                )
                        rehearsal_start = time.monotonic()

                        async def turn(ws):
                            before = time.monotonic()
                            await ws.send(
                                json.dumps(
                                    {
                                        "type": "text",
                                        "text": "What can you help me with?",
                                    }
                                )
                            )
                            while True:
                                event = json.loads(
                                    await asyncio.wait_for(ws.recv(), timeout=20)
                                )
                                if event["event"] == "agent_say":
                                    latencies.append((time.monotonic() - before) * 1000)
                                    return

                        while time.monotonic() - rehearsal_start < args.duration:
                            await asyncio.gather(*(turn(ws) for ws in sockets))
                            if (await client.get("/health")).status_code != 200:
                                raise RuntimeError("Health check failed")
                            samples.append(
                                {
                                    "at_s": round(
                                        time.monotonic() - rehearsal_start, 1
                                    ),
                                    "rss_bytes": rss_bytes(process.pid),
                                }
                            )
                            if len(samples) % 6 == 1:
                                print(
                                    f"Rehearsal {samples[-1]['at_s']:.0f}s: 3 sessions, RSS {samples[-1]['rss_bytes'] / 1024**2:.1f} MiB, {len(latencies)} completed turns",
                                    flush=True,
                                )
                            if samples[-1]["rss_bytes"] >= 400 * 1024 * 1024:
                                raise RuntimeError(
                                    "Rehearsal server exceeded 400 MiB RSS budget"
                                )
                            await asyncio.sleep(
                                min(
                                    args.interval,
                                    max(
                                        0,
                                        args.duration
                                        - (time.monotonic() - rehearsal_start),
                                    ),
                                )
                            )
                        final = (
                            await client.get(
                                "/api/app/me",
                                headers={"X-App-Token": "app-ananya-demo"},
                            )
                        ).json()
                        assert initial["accounts"] == final["accounts"], (
                            "Balances changed during read-only rehearsal"
                        )
                        health = (await client.get("/api/health")).json()
                        assert health["live_calls"] == 3, "Live sessions were lost"
                        for ws in sockets:
                            await ws.close()
                        sockets.clear()
                        for _ in range(30):
                            if (await client.get("/api/health")).json()[
                                "live_calls"
                            ] == 0:
                                break
                            await asyncio.sleep(0.5)
                        else:
                            raise RuntimeError(
                                "Sessions did not clean up after disconnect"
                            )
                        peak = max(peak_rss_bytes(process.pid), max(sample["rss_bytes"] for sample in samples))
                        if peak >= 400 * 1024 * 1024:
                            raise RuntimeError(
                                f"Peak server process-tree memory {peak / 1024**2:.1f} MiB exceeded 400 MiB, including disconnect cleanup"
                            )
                        result = {
                            "status": "passed",
                            "simulation": True,
                            "model_benchmark": False,
                            "duration_s": round(time.monotonic() - rehearsal_start, 1),
                            "concurrent_sessions": 3,
                            "turn_count": len(latencies),
                            "peak_rss_mib": round(peak / 1024**2, 2),
                            "preloaded_audio_seconds_per_session": args.preload_audio_seconds,
                            "memory_measurement": "sum of process peak working sets, including venv children and disconnect cleanup (Windows); sampled RSS on Linux",
                            "latency_p50_ms": round(
                                sorted(latencies)[len(latencies) // 2], 2
                            ),
                            "latency_p95_ms": round(
                                sorted(latencies)[
                                    min(len(latencies) - 1, int(len(latencies) * 0.95))
                                ],
                                2,
                            ),
                            "samples": samples,
                            "total_elapsed_s": round(time.monotonic() - started, 1),
                            "limitations": "Local Windows cloud-only profile; providers disabled. Does not establish hosted memory, audio latency or DetectifAI performance.",
                        }
                        args.output.parent.mkdir(parents=True, exist_ok=True)
                        args.output.write_text(
                            json.dumps(result, indent=2), encoding="utf-8"
                        )
                        print(
                            json.dumps(
                                {k: v for k, v in result.items() if k != "samples"}
                            ),
                            flush=True,
                        )
                    finally:
                        for ws in sockets:
                            await ws.close()
            finally:
                if sys.platform == "win32":
                    await asyncio.to_thread(
                        subprocess.run,
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        capture_output=True,
                        check=False,
                    )
                else:
                    process.terminate()
                await asyncio.to_thread(process.wait, timeout=15)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=1800)
    parser.add_argument("--interval", type=float, default=10)
    parser.add_argument("--preload-audio-seconds", type=int, default=0)
    parser.add_argument("--output", type=Path, default=Path("data/rehearsal.json"))
    args = parser.parse_args()
    if args.duration <= 0 or args.interval <= 0:
        parser.error("duration and interval must be positive")
    asyncio.run(run(args))
