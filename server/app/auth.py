"""
JWT authentication middleware.

Validates Keycloak-issued bearer tokens on every request except those
on the health-check path.  Uses PyJWKClient for automatic JWKS
retrieval and key rotation handling.
"""

from __future__ import annotations

import base64
import binascii
import logging
import ssl
from collections.abc import Awaitable, Callable

import httpx
import jwt
from jwt import PyJWKClient
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from app.config import Settings, get_settings
from app.dev_auth import decode_dev_token
from app.storage import app_tokens

logger = logging.getLogger(__name__)


def _build_ssl_context(settings: Settings) -> ssl.SSLContext | None:
    """
    Build the TLS context for outbound Keycloak calls (JWKS fetch and the
    optional Copilot token-endpoint check).

    Precedence:

    - ``tls_insecure_skip_verify`` → a context that verifies neither the
      certificate nor the hostname. **POC/testing only**; logs a warning.
    - ``tls_ca_bundle`` → trust the given PEM CA bundle (e.g. a private CA).
    - otherwise → ``None`` so callers use their default system trust store.

    :param settings: Application settings.
    :returns: An :class:`ssl.SSLContext`, or ``None`` for default behaviour.
    """
    if settings.tls_insecure_skip_verify:
        logger.warning(
            "TLS verification DISABLED for Keycloak calls "
            "(TLS_INSECURE_SKIP_VERIFY=true). Never use this in production."
        )
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context
    if settings.tls_ca_bundle:
        return ssl.create_default_context(cafile=str(settings.tls_ca_bundle))
    return None


def _select_token_validation_mode(token: str, settings: Settings) -> str:
    """
    Choose a token validator from the **unverified** ``alg`` header.

    Routing is by algorithm only — validators are never tried in sequence
    (that would defeat the gating). HS256 is accepted *only* when a dev
    shared secret is configured; real RS256/ES256 tokens always go to the
    JWKS validator; anything else is rejected.

    :param token: The raw bearer token.
    :param settings: Application settings.
    :returns: ``"dev-shared-secret"`` or ``"oidc-jwks"``.
    :raises jwt.InvalidTokenError: For HS256 without a dev secret, or an
        unsupported algorithm.
    """
    alg = jwt.get_unverified_header(token).get("alg")
    if alg == "HS256":
        if not settings.dev_shared_secret:
            raise jwt.InvalidTokenError(
                "HS256 token received but dev secret is unset"
            )
        return "dev-shared-secret"
    if alg in ("RS256", "ES256"):
        return "oidc-jwks"
    raise jwt.InvalidTokenError(f"Unsupported token algorithm: {alg!r}")

# Paths that are exempt from authentication.
_PUBLIC_PATHS: frozenset[str] = frozenset({
    "/health",
    "/livez",
    "/readyz",
    "/healthz",
    "/.well-known/oauth-protected-resource",
    "/.well-known/oauth-authorization-server",
})

# Only data surfaces are protected: the REST API, the MCP mount, and the
# WebDAV authoring endpoint. The web-UI shell (index.html, built assets,
# /config.js) and the OAuth/Swagger discovery docs are public — the SPA is
# just static JavaScript that then authenticates against Keycloak via OIDC;
# it must load before any token exists, and deep-link refreshes on
# client-side routes must serve the shell. ``/dav`` uses HTTP Basic
# (username:app-token) instead of bearer because OS mount clients cannot run
# an OIDC browser flow.
_PROTECTED_PREFIXES: tuple[str, ...] = ("/api", "/kits", "/dav")
_DAV_PREFIX = "/dav"


def _requires_auth(path: str) -> bool:
    """
    Return whether *path* is a protected data surface.

    :param path: Request path.
    :returns: ``True`` for the REST API and the MCP mount, ``False`` for
        public paths (health, well-known, the SPA shell, Swagger docs).
    """
    if path in _PUBLIC_PATHS or path.startswith("/.well-known/"):
        return False
    return any(
        path == prefix or path.startswith(prefix + "/")
        for prefix in _PROTECTED_PREFIXES
    )

_COPILOT_CLIENT_ID_HEADER = "X-Client-Id"
_COPILOT_CLIENT_SECRET_HEADER = "X-Client-Secret"


class IDPUnavailableError(Exception):
    """Raised when the identity provider token endpoint is unavailable."""


class JWTAuthMiddleware(BaseHTTPMiddleware):
    """
    Starlette middleware that validates Keycloak-issued JWTs.

        Every request whose path is not in ``_PUBLIC_PATHS`` must be
        authenticated by either:

        - a valid ``Authorization: Bearer <token>`` header, or
        - Copilot headers (``X-Client-Id`` and ``X-Client-Secret``),
            validated against the IDP token endpoint when enabled.

        Bearer tokens are validated against the JWKS endpoint advertised by
        the configured Keycloak realm.  JWKS keys are cached for one hour
        (renewed automatically on key rotation).

    Per-collaborator isolation is enforced at the Keycloak level: each
    collaborator has their own service-account client.  This middleware
    only verifies that the token is cryptographically valid and was
    issued by the expected realm; it does not inspect roles or scopes.
    """

    def __init__(
        self,
        app: ASGIApp,
        settings: Settings | None = None,
    ) -> None:
        """
        Initialise the middleware and warm up the JWKS client.

        :param app: Inner ASGI application.
        :param settings: Optional Settings override; uses
            :func:`~app.config.get_settings` if not provided.
        """
        super().__init__(app)
        self._settings: Settings = settings or get_settings()
        self._www_authenticate = (
            'Bearer realm="Instructions MCP", '
            f'resource_metadata="{self._settings.oauth_metadata_url}"'
        )
        self._ssl_context = _build_ssl_context(self._settings)
        self._jwks_client = PyJWKClient(
            self._settings.jwks_url,
            cache_keys=True,
            cache_jwk_set=True,
            lifespan=3600,
            ssl_context=self._ssl_context,
        )
        self._copilot_auth_enabled = self._settings.copilot_auth_enabled

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """
        Validate the bearer token and pass the request through, or
        return 401.

        :param request: Incoming HTTP request.
        :param call_next: Next middleware or route handler.
        :returns: The downstream response, or a 401 JSON response on
            authentication failure.
        """
        logger.debug(
            "%s %s (client: %s)",
            request.method,
            request.url.path,
            request.client.host if request.client else "unknown",
        )

        if not _requires_auth(request.url.path):
            logger.debug("Public path, skipping auth: %s", request.url.path)
            return await call_next(request)

        # WebDAV authoring uses HTTP Basic (username:app-token), since OS
        # mount clients cannot run an OIDC browser flow.
        if request.url.path.startswith(_DAV_PREFIX):
            return await self._handle_dav(request, call_next)

        auth_header = request.headers.get("Authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:]
            try:
                decoded = self._validate_bearer_token(token)
            except jwt.ExpiredSignatureError:
                return self._unauthorized(
                    "Token has expired", self._www_authenticate
                )
            except jwt.InvalidIssuerError:
                return self._unauthorized(
                    "Invalid token issuer", self._www_authenticate
                )
            except jwt.InvalidAudienceError:
                logger.warning(
                    "Token audience validation failed (expected %r)",
                    self._settings.keycloak_audience,
                )
                return self._unauthorized(
                    "Invalid token audience", self._www_authenticate
                )
            except jwt.PyJWTError as exc:
                # Log the detail, but never echo the raw exception text to the
                # client (module-auth-oidc-python).
                logger.warning("JWT validation failed: %s", exc)
                return self._unauthorized(
                    "Invalid token", self._www_authenticate
                )
            except Exception as exc:  # noqa: BLE001
                # JWKS fetch failures (network errors, unexpected
                # Keycloak responses) must not silently pass.
                logger.warning(
                    "Token validation failed (JWKS error): %s",
                    exc,
                    exc_info=True,
                )
                return self._unauthorized(
                    "Token validation failed", self._www_authenticate
                )

            logger.debug(
                "User authenticated via bearer token: sub=%s scope=%s",
                decoded.get("sub", "unknown"),
                decoded.get("scope", ""),
            )
            # Expose the caller identity to routes (e.g. app-token minting).
            request.state.auth_subject = (
                decoded.get("preferred_username") or decoded.get("sub") or ""
            )
            return await call_next(request)

        if self._copilot_auth_enabled:
            has_headers = self._has_copilot_auth_headers(request)
            if has_headers:
                try:
                    if await self._validate_copilot_headers(request):
                        logger.debug(
                            "User authenticated via IDP-backed Copilot headers"
                        )
                        request.state.auth_subject = request.headers.get(
                            _COPILOT_CLIENT_ID_HEADER, ""
                        )
                        return await call_next(request)
                except IDPUnavailableError:
                    return self._service_unavailable(
                        "Authentication service temporarily unavailable"
                    )
                return self._unauthorized(
                    "Invalid Copilot header credentials",
                    self._www_authenticate,
                )

        return self._unauthorized(
            "Missing or malformed Authorization header",
            self._www_authenticate,
        )

    async def _handle_dav(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """
        Authenticate a ``/dav`` request via HTTP Basic + app token.

        The Basic password is a per-user app token minted from the web UI.
        Credentials must travel over TLS.

        :param request: Incoming WebDAV request.
        :param call_next: Downstream WebDAV handler.
        :returns: The downstream response, or ``401``/``403``.
        """
        if self._settings.dav_require_tls and request.url.scheme != "https":
            return JSONResponse(
                status_code=403,
                content={"detail": "WebDAV requires HTTPS."},
            )
        header = request.headers.get("Authorization", "")
        if header.lower().startswith("basic "):
            token = self._basic_app_token(header)
            if token is not None:
                record = app_tokens.verify(
                    self._settings.app_tokens_path, token
                )
                if record:
                    request.state.auth_subject = record["user"]
                    return await call_next(request)
        return self._basic_unauthorized()

    @staticmethod
    def _basic_app_token(header: str) -> str | None:
        """
        Extract the password (app token) from a Basic auth header.

        :param header: The ``Authorization`` header value.
        :returns: The decoded password, or ``None`` if malformed.
        """
        try:
            raw = base64.b64decode(
                header.split(" ", 1)[1].strip()
            ).decode("utf-8")
        except (IndexError, binascii.Error, UnicodeDecodeError):
            return None
        _, sep, password = raw.partition(":")
        return password if sep else None

    @staticmethod
    def _basic_unauthorized() -> JSONResponse:
        """Return a ``401`` prompting for Basic WebDAV credentials."""
        return JSONResponse(
            status_code=401,
            content={
                "detail": (
                    "Invalid or missing WebDAV credentials. Use any "
                    "username and a valid app token as the password (mint "
                    "one in the web UI)."
                )
            },
            headers={
                "WWW-Authenticate": 'Basic realm="Instructions WebDAV"'
            },
        )

    def _validate_bearer_token(self, token: str) -> dict:
        """
        Validate a bearer token and return decoded claims.

        Routes by the unverified ``alg`` header: HS256 dev tokens to the
        dev-secret validator (only when configured), real RS256/ES256
        tokens to the JWKS validator. Both paths enforce the same
        ``iss``/``aud`` and return the same claim shape.

        :param token: Raw bearer token value.
        :returns: Decoded JWT claims.
        :raises jwt.PyJWTError: If token validation fails.
        """
        if _select_token_validation_mode(token, self._settings) == (
            "dev-shared-secret"
        ):
            return decode_dev_token(token, self._settings)
        signing_key = self._jwks_client.get_signing_key_from_jwt(token)
        decode_kwargs: dict = {
            "algorithms": ["RS256", "ES256"],
            "issuer": self._settings.keycloak_issuer,
        }
        if self._settings.keycloak_audience:
            decode_kwargs["audience"] = self._settings.keycloak_audience
        else:
            decode_kwargs["options"] = {"verify_aud": False}
        return jwt.decode(token, signing_key.key, **decode_kwargs)

    @staticmethod
    def _has_copilot_auth_headers(request: Request) -> bool:
        """
        Return whether both fixed Copilot auth headers are present.

        :param request: Incoming HTTP request.
        :returns: ``True`` when both headers are present.
        """
        return (
            _COPILOT_CLIENT_ID_HEADER in request.headers
            and _COPILOT_CLIENT_SECRET_HEADER in request.headers
        )

    async def _validate_copilot_headers(self, request: Request) -> bool:
        """
        Validate Copilot credentials against the IDP token endpoint.

        :param request: Incoming HTTP request.
        :returns: ``True`` when credentials are accepted by the IDP.
        :raises IDPUnavailableError: If the IDP is unavailable.
        """
        client_id = request.headers.get(_COPILOT_CLIENT_ID_HEADER, "")
        client_secret = request.headers.get(_COPILOT_CLIENT_SECRET_HEADER, "")
        if not client_id or not client_secret:
            logger.debug("Missing fixed-header client credentials")
            return False

        try:
            async with httpx.AsyncClient(
                verify=self._ssl_context or True,
                timeout=self._settings.copilot_auth_timeout_seconds,
            ) as client:
                response = await client.post(
                    self._settings.token_endpoint,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": client_id,
                        "client_secret": client_secret,
                    },
                )
        except httpx.HTTPError as exc:
            logger.warning("IDP request failed: %s", exc)
            raise IDPUnavailableError("Unable to reach IDP") from exc

        if response.status_code == 200:
            return True
        if response.status_code in {400, 401, 403}:
            logger.info(
                "IDP rejected fixed-header credentials: status=%s",
                response.status_code,
            )
            return False
        logger.warning("IDP returned error status=%s", response.status_code)
        raise IDPUnavailableError("IDP returned server error")

    @staticmethod
    def _service_unavailable(detail: str) -> JSONResponse:
        """
        Build a 503 JSON response.

        :param detail: Human-readable explanation of the failure.
        :returns: :class:`~starlette.responses.JSONResponse` with HTTP
            status 503.
        """
        logger.debug("Authentication backend unavailable: %s", detail)
        return JSONResponse(
            {"detail": detail},
            status_code=503,
        )

    @staticmethod
    def _unauthorized(detail: str, www_authenticate: str = "") -> JSONResponse:
        """
        Build a 401 JSON response.

        :param detail: Human-readable explanation of the failure.
        :param www_authenticate: Value for the ``WWW-Authenticate``
            response header.  OAuth-aware clients (e.g. VS Code) use
            this to discover the protected-resource metadata URL and
            initiate an authorization flow automatically.
        :returns: :class:`~starlette.responses.JSONResponse` with HTTP
            status 401.
        """
        logger.debug("Authentication failed: %s", detail)
        if www_authenticate:
            logger.debug("WWW-Authenticate: %s", www_authenticate)
        headers = (
            {"WWW-Authenticate": www_authenticate}
            if www_authenticate
            else {}
        )
        return JSONResponse(
            {"detail": detail}, status_code=401, headers=headers
        )
