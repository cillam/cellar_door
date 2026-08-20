"""Unit tests for app.auth.get_current_user_id -- real JWKS-based
signature verification (step 5c). Exercises app.auth directly (not
through the FastAPI app/TestClient), so app.dependency_overrides
doesn't apply here -- each test builds its own PyJWKClient, with
fetch_data monkeypatched to serve tests/conftest.py's test JWKS instead
of hitting Supabase, and passes it explicitly as get_current_user_id's
jwks_client argument. tests/test_routes.py's autouse jwks_override
fixture does the equivalent for route tests that go through the app.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from jwt import PyJWKClient

from app.auth import get_current_user_id
from tests.conftest import _TEST_KID, _TEST_PRIVATE_KEY, _test_jwks_response


def _jwks_client() -> PyJWKClient:
    """A PyJWKClient serving tests/conftest.py's test JWKS, network-free."""
    client = PyJWKClient("https://example.invalid/jwks.json")
    client.fetch_data = _test_jwks_response  # type: ignore[method-assign]
    return client


def _make_token(
    payload: dict[str, object],
    *,
    key: rsa.RSAPrivateKey | str = _TEST_PRIVATE_KEY,
    kid: str | None = _TEST_KID,
    algorithm: str = "RS256",
) -> str:
    headers = {"kid": kid} if kid is not None else {}
    return jwt.encode(payload, key, algorithm=algorithm, headers=headers)


def _valid_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {"sub": str(uuid4()), "aud": "authenticated"}
    payload.update(overrides)
    return payload


def test_valid_token_returns_sub_as_uuid() -> None:
    user_id = uuid4()
    token = _make_token(_valid_payload(sub=str(user_id)))

    result = get_current_user_id(authorization=f"Bearer {token}", jwks_client=_jwks_client())

    assert result == user_id


def test_missing_header_raises_401() -> None:
    with pytest.raises(HTTPException) as exc_info:
        get_current_user_id(authorization=None, jwks_client=_jwks_client())
    assert exc_info.value.status_code == 401


def test_header_without_bearer_prefix_raises_401() -> None:
    token = _make_token(_valid_payload())
    with pytest.raises(HTTPException) as exc_info:
        get_current_user_id(authorization=token, jwks_client=_jwks_client())  # no "Bearer " prefix
    assert exc_info.value.status_code == 401


def test_malformed_token_raises_401() -> None:
    with pytest.raises(HTTPException) as exc_info:
        get_current_user_id(authorization="Bearer not-a-real-jwt", jwks_client=_jwks_client())
    assert exc_info.value.status_code == 401


def test_token_missing_sub_claim_raises_401() -> None:
    token = _make_token({"aud": "authenticated"})  # no sub
    with pytest.raises(HTTPException) as exc_info:
        get_current_user_id(authorization=f"Bearer {token}", jwks_client=_jwks_client())
    assert exc_info.value.status_code == 401


def test_token_with_non_uuid_sub_raises_401() -> None:
    token = _make_token(_valid_payload(sub="not-a-uuid"))
    with pytest.raises(HTTPException) as exc_info:
        get_current_user_id(authorization=f"Bearer {token}", jwks_client=_jwks_client())
    assert exc_info.value.status_code == 401


def test_token_signed_with_wrong_key_raises_401() -> None:
    # A different keypair, but the *same* kid -- so PyJWKClient finds a
    # "matching" key by kid, and the signature check itself must be what
    # rejects this, not a kid-lookup miss. This is the case that
    # actually proves signatures are verified at all: the pre-5c stub
    # would have accepted this token outright.
    attacker_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = _make_token(_valid_payload(), key=attacker_key)

    with pytest.raises(HTTPException) as exc_info:
        get_current_user_id(authorization=f"Bearer {token}", jwks_client=_jwks_client())
    assert exc_info.value.status_code == 401


def test_token_with_unknown_kid_raises_401() -> None:
    token = _make_token(_valid_payload(), kid="some-other-key-id")

    with pytest.raises(HTTPException) as exc_info:
        get_current_user_id(authorization=f"Bearer {token}", jwks_client=_jwks_client())
    assert exc_info.value.status_code == 401


def test_token_missing_kid_raises_401() -> None:
    token = _make_token(_valid_payload(), kid=None)

    with pytest.raises(HTTPException) as exc_info:
        get_current_user_id(authorization=f"Bearer {token}", jwks_client=_jwks_client())
    assert exc_info.value.status_code == 401


def test_expired_token_raises_401() -> None:
    expired = datetime.now(UTC) - timedelta(hours=1)
    token = _make_token(_valid_payload(exp=int(expired.timestamp())))

    with pytest.raises(HTTPException) as exc_info:
        get_current_user_id(authorization=f"Bearer {token}", jwks_client=_jwks_client())
    assert exc_info.value.status_code == 401


def test_wrong_audience_raises_401() -> None:
    token = _make_token(_valid_payload(aud="some-other-audience"))

    with pytest.raises(HTTPException) as exc_info:
        get_current_user_id(authorization=f"Bearer {token}", jwks_client=_jwks_client())
    assert exc_info.value.status_code == 401


def test_unsupported_algorithm_raises_401() -> None:
    # HS256 (symmetric) rather than the RS256/ES256 app.auth allows --
    # even if an attacker knew a plausible-looking secret, the algorithm
    # itself isn't in app.auth's allowlist, so this must fail before any
    # key material is considered.
    token = _make_token(
        _valid_payload(),
        key="attacker-controlled-secret-long-enough-to-not-warn",
        algorithm="HS256",
    )

    with pytest.raises(HTTPException) as exc_info:
        get_current_user_id(authorization=f"Bearer {token}", jwks_client=_jwks_client())
    assert exc_info.value.status_code == 401
