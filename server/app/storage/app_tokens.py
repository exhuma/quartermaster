"""
File-backed registry of per-user application tokens for WebDAV access.

OS WebDAV mount dialogs speak HTTP Basic, which cannot carry an OIDC
browser flow. A user therefore mints a long-lived **app token** from the
web UI (while authenticated via OIDC) and uses it as the Basic password
when mounting the kit catalog. Tokens are bound to the minting user, stored
**hashed** (only the hash is persisted; the plaintext is shown once), and
individually revocable.

This is a server-issued credential bound to the OIDC identity at mint time
— deliberately self-contained rather than a Keycloak offline-token /
introspection round-trip per WebDAV request. Records:
``{"id", "user", "label", "token_hash", "created"}``.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.storage.kit_writes import atomic_write_text


def _hash(token: str) -> str:
    """Return the SHA-256 hex digest of *token*."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _load(path: Path) -> list[dict[str, Any]]:
    """Load all token records (empty if the file is absent)."""
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, list) else []


def _save(path: Path, records: list[dict[str, Any]]) -> None:
    """Persist *records* atomically."""
    atomic_write_text(path, json.dumps(records, indent=2) + "\n")


def _public(record: dict[str, Any]) -> dict[str, Any]:
    """Return a record without the secret hash, safe to return to clients."""
    return {
        "id": record["id"],
        "user": record["user"],
        "label": record.get("label", ""),
        "created": record.get("created", ""),
    }


def mint(
    path: Path, user: str, label: str = ""
) -> tuple[dict[str, Any], str]:
    """
    Create a new app token for *user*.

    :param path: Registry file path.
    :param user: Owning user identifier (from the OIDC token).
    :param label: Optional human-readable label.
    :returns: ``(public_record, plaintext_token)``. The plaintext is shown
        once and never stored.
    """
    token = secrets.token_urlsafe(32)
    record = {
        "id": secrets.token_hex(6),
        "user": user,
        "label": label,
        "token_hash": _hash(token),
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    records = _load(path)
    records.append(record)
    _save(path, records)
    return _public(record), token


def list_for(path: Path, user: str) -> list[dict[str, Any]]:
    """
    List a user's tokens (public fields only; never the hash).

    :param path: Registry file path.
    :param user: Owning user identifier.
    :returns: Public token records owned by *user*.
    """
    return [_public(r) for r in _load(path) if r.get("user") == user]


def verify(path: Path, token: str) -> dict[str, Any] | None:
    """
    Return the record matching *token*, or ``None``.

    Uses a constant-time comparison against every stored hash.

    :param path: Registry file path.
    :param token: Candidate plaintext token (the Basic password).
    :returns: The matching public record, or ``None``.
    """
    if not token:
        return None
    candidate = _hash(token)
    for record in _load(path):
        if secrets.compare_digest(record.get("token_hash", ""), candidate):
            return _public(record)
    return None


def revoke(path: Path, token_id: str, user: str) -> bool:
    """
    Revoke a token by id, restricted to its owner. Idempotent.

    :param path: Registry file path.
    :param token_id: Token id to revoke.
    :param user: Requesting user; only their own tokens are removable.
    :returns: ``True`` if a token was removed.
    """
    records = _load(path)
    remaining = [
        r
        for r in records
        if not (r.get("id") == token_id and r.get("user") == user)
    ]
    if len(remaining) != len(records):
        _save(path, remaining)
        return True
    return False
