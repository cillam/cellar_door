"""Unit tests for app.auth.get_current_user_id -- the stub JWT
dependency. Signature verification isn't tested here because the stub
deliberately doesn't do it (see app/auth.py's module docstring); step 5
adds real JWKS verification and its own tests.
"""

from __future__ import annotations

from uuid import uuid4

import jwt
import pytest
from fastapi import HTTPException

from app.auth import get_current_user_id


def _make_token(payload: dict[str, object]) -> str:
    # Signature is never verified by the stub (see app/auth.py), so this
    # secret's only job is to be long enough that pyjwt doesn't warn
    # about it -- the actual value is irrelevant.
    return jwt.encode(payload, "test-secret-that-is-long-enough-to-not-warn", algorithm="HS256")


async def test_valid_token_returns_sub_as_uuid() -> None:
    user_id = uuid4()
    token = _make_token({"sub": str(user_id), "role": "authenticated"})

    result = await get_current_user_id(authorization=f"Bearer {token}")

    assert result == user_id


async def test_missing_header_raises_401() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user_id(authorization=None)
    assert exc_info.value.status_code == 401


async def test_header_without_bearer_prefix_raises_401() -> None:
    token = _make_token({"sub": str(uuid4())})
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user_id(authorization=token)  # missing "Bearer " prefix
    assert exc_info.value.status_code == 401


async def test_malformed_token_raises_401() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user_id(authorization="Bearer not-a-real-jwt")
    assert exc_info.value.status_code == 401


async def test_token_missing_sub_claim_raises_401() -> None:
    token = _make_token({"role": "authenticated"})  # no sub
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user_id(authorization=f"Bearer {token}")
    assert exc_info.value.status_code == 401


async def test_token_with_non_uuid_sub_raises_401() -> None:
    token = _make_token({"sub": "not-a-uuid"})
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user_id(authorization=f"Bearer {token}")
    assert exc_info.value.status_code == 401
