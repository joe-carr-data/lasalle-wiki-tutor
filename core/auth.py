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


# ── Per-IP token-bucket rate limiter ──────────────────────────
#
# Plain in-memory token bucket per source IP. Process-local, so multi-process
# deploys would need Redis — but the demo runs in a single uvicorn worker, so
# this is fine. Two named buckets share the same machinery on independent
# limits: `auth_validate` (10/min, brute-force guard on the token check) and
# `stream` (60/min, gpt-5.4-spend guard on the SSE endpoint).

_BUCKETS: dict[str, dict[str, Deque[float]]] = defaultdict(lambda: defaultdict(deque))

_LIMITS: dict[str, tuple[int, float]] = {
    "auth_validate": (10, 60.0),   # 10 attempts / 60s — token brute-force guard
    "stream": (60, 60.0),          # 60 stream calls / 60s — gpt-5.4 spend cap
    "admin": (30, 60.0),           # 30 admin calls / 60s — DoS + probe guard on the public admin surface
}


def _client_ip(request: Request) -> str:
    """Best-effort source IP. Honors X-Forwarded-For (Caddy/ALB sets it).

    Caddy on the same box is the only proxy in front of us, so the leftmost
    XFF entry is the real client. If a second proxy is ever added, this
    helper must be revisited — the leftmost entry is attacker-controlled
    when more than one trusted hop sits between client and app.
    """
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _enforce_bucket(request: Request, bucket_name: str) -> None:
    """Raise 429 if the source IP has exceeded the named bucket's budget.

    Side effect: records the attempt in the bucket. Call on every hit, not
    just on failure — otherwise an attacker can probe for free as long as
    they happen to guess right.
    """
    max_attempts, window_s = _LIMITS[bucket_name]
    ip = _client_ip(request)
    now = time.monotonic()
    bucket = _BUCKETS[bucket_name][ip]

    cutoff = now - window_s
    while bucket and bucket[0] < cutoff:
        bucket.popleft()

    if len(bucket) >= max_attempts:
        retry_after = int(window_s - (now - bucket[0])) + 1
        raise HTTPException(
            status_code=429,
            detail="too many attempts; try again later",
            headers={"Retry-After": str(retry_after)},
        )

    bucket.append(now)


def check_rate_limit(request: Request) -> None:
    """Per-IP rate limit on `/api/auth/validate` — token brute-force guard."""
    _enforce_bucket(request, "auth_validate")


def check_stream_rate_limit(request: Request) -> None:
    """Per-IP rate limit on the SSE stream — protects against runaway spend.

    A leaked or compromised access token would otherwise allow unlimited
    `gpt-5.4` calls until the operator notices and rotates. The 60/min cap
    is far above typical human use and far below "burn the budget overnight".
    """
    _enforce_bucket(request, "stream")


def check_admin_rate_limit(request: Request) -> None:
    """Per-IP rate limit on the admin surface — DoS and probe guard.

    The admin token is 32 url-safe chars (~190 bits) so brute-forcing it
    is computationally infeasible anyway. This bucket exists so an
    attacker can't pound the endpoint for hours to fish for timing leaks
    or to amplify a DoS into Mongo reads.
    """
    _enforce_bucket(request, "admin")


# ── Admin endpoints: token gate, public surface ────────────────


def _expected_admin_token() -> Optional[str]:
    raw = os.getenv("WIKI_TUTOR_ADMIN_TOKEN", "")
    return raw or None


async def require_admin(
    x_admin_token: Optional[str] = Header(default=None),
) -> None:
    """FastAPI dependency for ``/api/admin/*`` routes.

    The admin surface is reachable from the public internet — the only
    gate is the ``WIKI_TUTOR_ADMIN_TOKEN`` shared secret presented as the
    ``X-Admin-Token`` header. Per-IP rate limiting (see
    ``check_admin_rate_limit``) is the second layer that bounds
    brute-force probing and DoS.

    In non-local environments the env var must be set; falling open on
    an unset secret would expose the dashboard to the world. Local dev
    (``ENVIRONMENT=local``) with an empty token falls open so the
    dashboard works without setup.
    """
    expected = _expected_admin_token()
    if expected is None:
        env = os.getenv("ENVIRONMENT", "local")
        if env == "local":
            return
        raise HTTPException(
            status_code=503,
            detail="admin surface is not configured; set WIKI_TUTOR_ADMIN_TOKEN",
        )
    if not x_admin_token or not _tokens_match(x_admin_token, expected):
        raise HTTPException(status_code=401, detail="invalid admin token")


__all__ = [
    "require_access_token",
    "require_admin",
    "is_token_valid",
    "check_rate_limit",
    "check_stream_rate_limit",
    "check_admin_rate_limit",
    "_client_ip",
]
