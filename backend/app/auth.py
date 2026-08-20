"""JWT auth dependency -- real JWKS-based signature verification (step 5c).

Verifies the bearer token's signature against Supabase's published JWKS
(`settings.supabase_jwks_url`) before trusting any claim in it, then
extracts `user_id` from the `sub` claim. Every route that depends on
`get_current_user_id` (`app/routers/items.py`) gets this for free via
FastAPI's dependency injection -- no route signatures changed when this
module went from the step-4c stub to real verification.

Deliberately a plain `def`, not `async def`, and PyJWKClient is used
directly rather than reimplemented -- CLAUDE.md's "async all the way
down" is the default for this codebase because the two things that
actually require it (asyncpg's DB pool, LangGraph's SSE-streaming
pipeline) have no sync alternative, not because every dependency must
be non-blocking at all costs. PyJWKClient's key fetch is blocking
(urllib-based, not `requests` -- CLAUDE.md's "no requests, use httpx"
rule is about our own code, not a third-party library's internals) but
FastAPI runs sync dependency callables in its thread pool automatically,
the same way it does sync path operation functions -- so the blocking
call never occupies the event loop shared by other requests. That gets
us PyJWKClient's own battle-tested JWKS caching (`lifespan` param,
default 5 minutes) and refetch-on-unknown-`kid` retry (handles Supabase
rotating signing keys) for free, instead of a hand-rolled, less-tested
copy of the same logic.

`audience="authenticated"` is Supabase's documented default JWT
audience claim, not yet confirmed against a real token -- flagged for
manual verification once real test-user credentials are available (see
kickoff's step 5c checklist). If it turns out to be wrong, this is a
one-line fix.
"""

from __future__ import annotations

from functools import lru_cache
from uuid import UUID

import jwt
from fastapi import Depends, Header, HTTPException, status
from jwt import PyJWKClient

from app.config import get_settings

_ALGORITHMS = ["RS256", "ES256"]
_AUDIENCE = "authenticated"


@lru_cache
def get_jwks_client() -> PyJWKClient:
    """FastAPI dependency -- the process-wide PyJWKClient.

    Same `@lru_cache`-as-singleton pattern as app/storage.py's
    get_storage_client -- no lifespan wiring needed, since (unlike
    asyncpg/psycopg connections) there's no cross-event-loop hazard to
    a plain object that lazily opens/caches its own HTTP fetches.
    Tests override this via `app.dependency_overrides[get_jwks_client]`
    (see tests/conftest.py) rather than hitting Supabase's real JWKS
    endpoint.
    """
    return PyJWKClient(get_settings().supabase_jwks_url)


def get_current_user_id(
    authorization: str | None = Header(default=None),
    jwks_client: PyJWKClient = Depends(get_jwks_client),
) -> UUID:
    """Extract and verify user_id (the `sub` claim) from a bearer JWT.

    Verifies the token's signature against Supabase's JWKS before
    trusting anything in it. Raises 401 if the header is missing or
    malformed, the signing key can't be resolved, the signature/claims
    don't verify (bad signature, expired, wrong audience, ...), or the
    token has no `sub` claim / `sub` isn't a UUID -- SPEC.md: "JWT
    missing or invalid -> 401".
    """
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header",
        )

    token = authorization.removeprefix("Bearer ").strip()

    try:
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            key=signing_key,
            algorithms=_ALGORITHMS,
            audience=_AUDIENCE,
        )
    except jwt.PyJWTError as exc:
        # Covers both PyJWKClient's own errors (unresolvable kid,
        # connection failure -- PyJWKClientError is a PyJWTError
        # subclass) and jwt.decode's (bad signature, expired, wrong
        # audience, malformed token, ...) with one handler, since both
        # collapse to the same response: the token isn't trustworthy.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        ) from exc

    sub = payload.get("sub")
    if sub is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing sub claim"
        )

    try:
        return UUID(sub)
    except (ValueError, AttributeError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token sub claim is not a valid UUID",
        ) from exc
