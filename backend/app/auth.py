"""JWT auth dependency -- stub for now (step 4c).

Parses the bearer token's payload without verifying its signature.
Real JWKS-based verification is step 5, once Supabase's JWKS URL
exists. pyjwt was chosen specifically because it covers both this
stub's unverified decode (`options={"verify_signature": False}`) and
step 5's real verification (`jwt.decode(token, key, algorithms=[...])`)
-- no library swap needed when step 5 lands.

**This stub is not secure.** It trusts whatever claims are in the
token without checking who signed it -- anyone can construct a JWT
claiming any user_id. Fine for local development ahead of step 5;
must never be the auth path in a deployed environment. There's no
per-environment gate here (app.config.Environment) because step 5
replaces this function's body entirely rather than adding a bypass
flag to it -- there's no "stub in production" state to guard against
once real verification lands, only a before-step-5 and an
after-step-5.
"""

from __future__ import annotations

from uuid import UUID

import jwt
from fastapi import Header, HTTPException, status


async def get_current_user_id(authorization: str | None = Header(default=None)) -> UUID:
    """Extract user_id (the `sub` claim) from a bearer JWT.

    Does NOT verify the token's signature -- see module docstring.
    Raises 401 if the header is missing or malformed, the token can't
    be parsed, or it has no `sub` claim / `sub` isn't a UUID -- SPEC.md:
    "JWT missing or invalid -> 401".
    """
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header",
        )

    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = jwt.decode(token, options={"verify_signature": False})
    except jwt.PyJWTError as exc:
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
