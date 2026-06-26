"""Rate limiting helper (module-http-middleware-hardening).

A thin wrapper over the maintained ``limits`` library. Routes invoke
:func:`enforce_limit_or_429` explicitly with a stable throttle key (rather
than relying on implicit global middleware), so each protected surface picks
its own limit and key.

The backend is ``memory://`` — **per-process**. It does not coordinate across
workers or replicas, nor survive restarts. When running more than one
process/instance (or to make limits durable), switch ``_storage`` to a shared
store such as ``redis://...``.
"""

from __future__ import annotations

import time

from fastapi import HTTPException
from limits import RateLimitItemPerSecond
from limits.storage import storage_from_string
from limits.strategies import MovingWindowRateLimiter

_storage = storage_from_string("memory://")
_limiter = MovingWindowRateLimiter(_storage)


def enforce_limit_or_429(
    *, key: str, limit: int, window_seconds: int, scope: str
) -> None:
    """Allow the call, or raise **HTTP 429** when the limit is exceeded.

    :param key: Stable throttle key (e.g. client identity + scope).
    :param limit: Maximum number of hits permitted within the window.
    :param window_seconds: Length of the moving window, in seconds.
    :param scope: Human-readable scope name, used in the 429 detail.
    :raises HTTPException: 429 with the full RFC 6585 header set when the
        limit is exceeded.
    """
    item = RateLimitItemPerSecond(limit, window_seconds)
    allowed = _limiter.hit(item, key)
    stats = _limiter.get_window_stats(item, key)
    reset = max(1, int(stats.reset_time - time.time()))
    if allowed:
        return
    raise HTTPException(
        status_code=429,
        detail=f"Rate limit exceeded for {scope}",
        headers={
            "RateLimit-Limit": str(limit),
            "RateLimit-Remaining": str(max(0, stats.remaining)),
            "RateLimit-Reset": str(reset),
            "Retry-After": str(reset),
        },
    )
