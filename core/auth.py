"""Single-token access gate for the LaSalle Wiki Tutor.

Demo-grade authentication: one shared secret, set via the
``WIKI_TUTOR_ACCESS_TOKEN`` environment variable, distributed by hand to the
university evaluators. The token is presented by the client as the
``X-Access-Token`` header on every API call.

Why a header (not a cookie):

- No CSRF surface, no signed-cookie machinery.
- Simpler revocation: rotate the env var, redeploy, every client re-auths once.
- Works identically for ``fetch`` and the ``fetch``-based SSE stream — no
  EventSource quirks.

What's gated:

- Every ``/api/wiki-tutor/*`` route (stream, cancel, conversations).
- The ``POST /api/auth/validate`` endpoint is itself NOT gated (it's the
  endpoint the gate calls to check the token before storing it) but is
  rate-limited per-IP so brute-force is impractical.

What's NOT gated:

- ``/health`` — load balancers need to probe it.
- ``/`` and ``/assets/*`` — the static bundle. The gate UI is part of the
  bundle, so serving the bundle to anonymous clients is the whole point.
"""

from __future__ import annotations

import hmac
import logging
import os
import time
from collections import defaultdict, deque
from typing import Deque, Optional

from fastapi import Depends, Header, HTTPException, Request

logger = logging.getLogger(__name__)


# ── Token check ──────────────────────────────────────────────


def _expected_token() -> Optional[str]:
    """Read the configured token. Empty string and unset both mean "no token"."""
    raw = os.getenv("WIKI_TUTOR_ACCESS_TOKEN", "")
    return raw or None


def _tokens_match(provided: str, expected: str) -> bool:
    """Constant-time comparison so a wrong token doesn't leak its length."""
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


def is_token_valid(token: Optional[str]) -> bool:
    """Pure helper: True iff `token` matches the configured secret.

    If no secret is configured, the gate is *open* — useful for local dev.
    Production deployments must set ``WIKI_TUTOR_ACCESS_TOKEN``.
    """
    expected = _expected_token()
    if expected is None:
        return True
    if not token:
        return False
    return _tokens_match(token, expected)


# ── FastAPI dependency ───────────────────────────────────────


async def require_access_token(
    x_access_token: Optional[str] = Header(default=None),
) -> None:
    """FastAPI dependency. 401s on missing or wrong token.

    Routes use it as ``dependencies=[Depends(require_access_token)]`` so the
    handler signature stays clean.
    """
    if is_token_valid(x_access_token):
        return
    # Don't leak whether the token was missing vs. wrong — both look the same
    # to a brute-forcer.
    raise HTTPException(status_code=401, detail="invalid access token")


# ── Per-IP rate limiter for /api/auth/validate ────────────────
#
# Plain in-memory token bucket per source IP. Process-local, so multi-process
# deploys would need Redis — but the demo runs in a single uvicorn worker, so
# this is fine. 10 attempts per 60-second window is enough for fat-fingering
# while making brute-force of a 32-char random token take ~10^60 years.

_RATE_LIMIT_MAX_ATTEMPTS = 10
_RATE_LIMIT_WINDOW_S = 60.0
_attempts: dict[str, Deque[float]] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    """Best-effort source IP. Honors X-Forwarded-For (Caddy/ALB sets it)."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_rate_limit(request: Request) -> None:
    """Raise 429 if the source IP has exceeded its attempt budget.

    Side effect: records the attempt in the bucket. Call this on every hit,
    not just on failure — otherwise an attacker can probe for free as long as
    they happen to guess right (which they won't, but defense in depth).
    """
    ip = _client_ip(request)
    now = time.monotonic()
    bucket = _attempts[ip]

    # Drop expired entries from the left.
    cutoff = now - _RATE_LIMIT_WINDOW_S
    while bucket and bucket[0] < cutoff:
        bucket.popleft()

    if len(bucket) >= _RATE_LIMIT_MAX_ATTEMPTS:
        retry_after = int(_RATE_LIMIT_WINDOW_S - (now - bucket[0])) + 1
        raise HTTPException(
            status_code=429,
            detail="too many attempts; try again later",
            headers={"Retry-After": str(retry_after)},
        )

    bucket.append(now)


__all__ = [
    "require_access_token",
    "is_token_valid",
    "check_rate_limit",
]
