"""Auth endpoint — token validation for the Gate UI.

The frontend Gate calls ``POST /api/auth/validate`` once with the token the
user typed. On success the client stashes the token in localStorage and
unmounts the gate; on failure (or when rate-limited) it shows an error.

This endpoint is **not** itself behind ``require_access_token`` (clients
without a valid token need a way to acquire one) but it IS rate-limited per
source IP so brute-force is impractical. The rate limit also covers the
absence of any token (empty body) so probing for the endpoint's existence
costs an attempt.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from core.auth import check_rate_limit, is_token_valid

router = APIRouter(prefix="/api/auth", tags=["auth"])


class ValidateRequest(BaseModel):
    token: str = Field(..., max_length=256)


class ValidateResponse(BaseModel):
    valid: bool


@router.post("/validate", response_model=ValidateResponse)
async def validate_token(
    body: ValidateRequest,
    _: None = Depends(check_rate_limit),
) -> ValidateResponse:
    """Return ``{valid: true|false}`` for the provided token.

    A 429 from ``check_rate_limit`` short-circuits before we ever touch the
    token, so a brute-forcer is throttled at 10 attempts/minute per IP.
    """
    return ValidateResponse(valid=is_token_valid(body.token))
