"""
Dev-only authentication bypass (module-dev-auth-bypass).

Lets the app run locally and in E2E without standing up Keycloak, by
accepting **self-minted HS256 dev tokens** alongside real RS256/ES256 IdP
tokens. The two halves are independent and both default off:

- ``dev_shared_secret`` gates HS256 *acceptance* in the middleware — unset
  means HS256 is rejected outright (the safe default).
- ``dev_auth_enabled`` gates whether the ``/auth/dev/*`` token-minting
  router is mounted at all (see ``app.routers.auth_dev``).

Dev tokens are **not** a separate identity path: they carry the same
``iss``/``aud`` as real tokens and flow through the exact same validation,
so dev and prod behave identically. None of this is reachable in production
as long as the deploy invariants hold (both settings unset).
"""

from __future__ import annotations

import time

import jwt

from app.config import Settings

ALGORITHM = "HS256"
_DEFAULT_TTL_SECONDS = 12 * 60 * 60


def mint_dev_token(
    settings: Settings,
    *,
    sub: str = "dev-user",
    username: str = "dev",
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> str:
    """
    Mint an HS256 dev token signed with the dev shared secret.

    The token carries the same ``iss`` (and ``aud`` when configured) as a
    real Keycloak token, so it satisfies the identical validation contract.

    :param settings: Application settings (must have ``dev_shared_secret``).
    :param sub: Subject claim for the dev identity.
    :param username: ``preferred_username`` claim.
    :param ttl_seconds: Token lifetime.
    :returns: A signed HS256 JWT.
    :raises RuntimeError: If the dev shared secret is not configured.
    """
    if not settings.dev_shared_secret:
        raise RuntimeError("dev_shared_secret is not configured")
    now = int(time.time())
    payload: dict[str, object] = {
        "iss": settings.keycloak_issuer,
        "sub": sub,
        "preferred_username": username,
        "scope": "openid profile email",
        "iat": now,
        "exp": now + ttl_seconds,
    }
    if settings.keycloak_audience:
        payload["aud"] = settings.keycloak_audience
    return jwt.encode(payload, settings.dev_shared_secret, algorithm=ALGORITHM)


def decode_dev_token(token: str, settings: Settings) -> dict:
    """
    Validate an HS256 dev token, enforcing the same ``iss``/``aud``.

    :param token: The HS256 token.
    :param settings: Application settings (provides the secret + issuer).
    :returns: Decoded claims.
    :raises jwt.PyJWTError: If validation fails.
    """
    decode_kwargs: dict = {
        "algorithms": [ALGORITHM],
        "issuer": settings.keycloak_issuer,
    }
    if settings.keycloak_audience:
        decode_kwargs["audience"] = settings.keycloak_audience
    else:
        decode_kwargs["options"] = {"verify_aud": False}
    return jwt.decode(token, settings.dev_shared_secret, **decode_kwargs)


def _main() -> None:
    """CLI: print a dev token for scripts/E2E (requires the dev secret)."""
    from app.config import get_settings

    settings = get_settings()
    if not settings.dev_shared_secret:
        raise SystemExit(
            "DEV_SHARED_SECRET is not set; cannot mint a dev token."
        )
    print(mint_dev_token(settings))


if __name__ == "__main__":
    _main()
