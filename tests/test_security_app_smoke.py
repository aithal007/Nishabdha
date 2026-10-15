"""HTTP assets and published security endpoints used by the browser."""

import pytest


@pytest.mark.asyncio
async def test_security_assets_and_contract(client):
    page = await client.get("/")
    assert page.status_code == 200
    assert 'src="/static/security.js"' in page.text
    for control in (
        "provisionPasskey",
        "delegateDemo",
        "runDelegate",
        "revokeDelegate",
    ):
        assert f'id="{control}"' in page.text
    script = await client.get("/static/security.js")
    assert script.status_code == 200
    assert "navigator.credentials.get" in script.text
    endpoints = (await client.get("/openapi.json")).json()["paths"]
    for endpoint in (
        "/api/app/passkeys/options",
        "/api/app/passkeys/verify",
        "/api/app/agents/grants",
        "/api/agents/support-tickets",
        "/.well-known/jwks.json",
    ):
        assert endpoint in endpoints
    assert (await client.get("/api/agents/support-tickets")).status_code == 401
