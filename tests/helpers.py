from __future__ import annotations

from app.core import session as session_mod
from app.i18n import speak_digits

from .conftest import STAFF, wav

GENUINE_ENROLL = ["real_1089_0.wav", "real_1089_1.wav", "real_1089_2.wav"]


async def enroll(client, customer_id: str, files=GENUINE_ENROLL):
    r = await client.post(
        f"/api/customers/{customer_id}/enroll",
        headers=STAFF,
        files=[("files", (f, wav(f), "audio/wav")) for f in files],
    )
    assert r.status_code == 200, r.text
    return r.json()


async def start_call(client, customer_id: str | None = None, lang: str = "en", **kw):
    r = await client.post("/api/calls", json={"customer_id": customer_id, "lang": lang, **kw})
    assert r.status_code == 200, r.text
    j = r.json()
    return j["call_id"], {"X-Call-Token": j["call_token"]}


async def turn(client, call_id, hdr, wavname: str):
    r = await client.post(f"/api/calls/{call_id}/turn", headers={**hdr, **STAFF}, files={"file": (wavname, wav(wavname), "audio/wav")})
    assert r.status_code == 200, r.text
    return r.json()["internal"]


async def text(client, call_id, hdr, t: str):
    r = await client.post(f"/api/calls/{call_id}/text", headers={**hdr, **STAFF}, json={"text": t})
    assert r.status_code == 200, r.text
    return r.json()["internal"]


def names(events) -> list[str]:
    return [e["event"] for e in events]


def first(events, name):
    return next((e["data"] for e in events if e["event"] == name), None)


def said(events) -> list[str]:
    return [e["data"]["text"] for e in events if e["event"] == "agent_say"]


def challenge_words(call_id: str) -> str:
    sess = session_mod.SESSIONS[call_id]
    assert sess.pending and sess.pending.stage == "challenge", "no open challenge"
    return speak_digits(sess.pending.challenge_digits, "en").replace(",", "")


async def card(client, customer_id: str, last4: str) -> dict:
    r = await client.get(f"/api/customers/{customer_id}", headers=STAFF)
    return next(c for c in r.json()["cards"] if c["last4"] == last4)
