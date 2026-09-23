"""The auth seam, on and off.

Real RSA keys and real signatures — only the JWKS *fetch* is stubbed, because
the alternative is standing up an HTTP server to serve two constants. Everything
that decides whether a request is authorized runs exactly as it would in
production.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.api import deps
from app.bus import bus
from app.config import settings
from app.main import app

ISSUER = "https://issuer.test"
AUDIENCE = "clinical-copilot"


@pytest.fixture(scope="module")
def signing_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def auth_enabled(monkeypatch, signing_key):
    """Turn auth on and point the key lookup at our own key."""
    monkeypatch.setattr(settings, "oidc_issuer", ISSUER)
    monkeypatch.setattr(settings, "oidc_audience", AUDIENCE)

    class FakeKey:
        key = signing_key.public_key()

    # monkeypatch undoes all of this itself, so there is nothing to tear down.
    monkeypatch.setattr(deps, "_jwks_client", lambda: _FakeJWKSClient(FakeKey()))


class _FakeJWKSClient:
    def __init__(self, key: Any) -> None:
        self._key = key

    def get_signing_key_from_jwt(self, token: str) -> Any:
        return self._key


def mint(signing_key: rsa.RSAPrivateKey, **overrides: Any) -> str:
    claims: dict[str, Any] = {
        "sub": "user_abc123",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "exp": datetime.now(UTC) + timedelta(minutes=5),
    }
    claims.update(overrides)
    return jwt.encode(claims, signing_key, algorithm="RS256")


@pytest.fixture
async def client():
    await bus.start()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            yield c
    finally:
        await bus.stop()


async def test_with_no_issuer_configured_every_request_is_the_dev_user(client):
    """Auth off is the default, and it is what keeps `docker compose up` working."""
    assert settings.auth_enabled is False
    response = await client.post("/api/conversations")
    assert response.status_code == 201


@pytest.mark.usefixtures("auth_enabled")
async def test_a_valid_token_authenticates_as_its_subject(client, session, signing_key):
    response = await client.post(
        "/api/conversations", headers={"Authorization": f"Bearer {mint(signing_key)}"}
    )
    assert response.status_code == 201

    # The subject became the row's owner, which is what puts it in the WHERE
    # clause of every subsequent query.
    from sqlalchemy import select

    from app.models import Conversation

    owner = (await session.execute(select(Conversation.user_id))).scalar_one()
    assert owner == "user_abc123"


@pytest.mark.usefixtures("auth_enabled")
@pytest.mark.parametrize(
    ("label", "headers"),
    [
        ("no header at all", {}),
        ("not a bearer token", {"Authorization": "Basic abc"}),
        ("garbage", {"Authorization": "Bearer not-a-jwt"}),
    ],
)
async def test_requests_without_a_usable_token_are_rejected(client, label, headers):
    response = await client.post("/api/conversations", headers=headers)
    assert response.status_code == 401, label


@pytest.mark.usefixtures("auth_enabled")
@pytest.mark.parametrize(
    ("label", "claims"),
    [
        ("expired", {"exp": datetime.now(UTC) - timedelta(minutes=1)}),
        ("wrong audience", {"aud": "some-other-api"}),
        ("wrong issuer", {"iss": "https://attacker.test"}),
        ("no subject", {"sub": ""}),
    ],
)
async def test_a_well_formed_but_wrong_token_is_rejected(client, signing_key, label, claims):
    """Each of these verifies cryptographically and must still be refused."""
    token = mint(signing_key, **claims)
    response = await client.post("/api/conversations", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401, label


@pytest.mark.usefixtures("auth_enabled")
async def test_a_token_signed_by_someone_else_is_rejected(client):
    """The signature check itself, with a key the server has never seen."""
    attacker_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = mint(attacker_key)
    response = await client.post("/api/conversations", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
