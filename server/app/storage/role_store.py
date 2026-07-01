"""File-backed authorization role store (IdP subject → role).

Two roles exist: ``editor`` (admin — edits the shared kit catalog and
grants/revokes editor from others) and ``consumer`` (read-only, the default
for any authenticated user not otherwise listed). Records key on the stable
Keycloak ``sub`` and carry a human-readable ``label`` for admin UIs.

Persistence is a single TOML document (per the project's "TOML for now"
mapping choice), written atomically via :func:`atomic_write_text`. Mirrors the
shape of :mod:`app.storage.app_tokens`.

**Bootstrap editors** are supplied out-of-band via ``QM_INITIAL_EDITORS`` and
always resolve to ``editor``: they cannot be demoted or removed through the
store, which makes an editor lockout impossible. They surface in listings as
read-only ``source="bootstrap"`` rows.

Record schema (per subject)::

    [ "<sub>" ]
    role = "editor" | "consumer"
    label = "<display name>"
    updated = "<iso8601>"
"""

from __future__ import annotations

import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import tomli_w

from app.storage.kit_writes import atomic_write_text

EDITOR = "editor"
CONSUMER = "consumer"
VALID_ROLES = frozenset({EDITOR, CONSUMER})


def _load(path: Path) -> dict[str, dict[str, Any]]:
    """Load the subject→record mapping (empty when the file is absent)."""
    if not path.exists():
        return {}
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    # Every top-level table is a subject record; ignore stray scalars.
    return {k: v for k, v in raw.items() if isinstance(v, dict)}


def _save(path: Path, records: dict[str, dict[str, Any]]) -> None:
    """Persist *records* atomically as TOML."""
    atomic_write_text(path, tomli_w.dumps(records))


def get_role(
    path: Path, sub: str, *, initial_editors: list[str] | None = None
) -> str:
    """
    Return the effective role for *sub*.

    Precedence: bootstrap editors (env) always win; then the stored role; then
    the ``consumer`` default (so an unknown user can never mutate the catalog).

    :param path: Role store file path.
    :param sub: The caller's stable subject.
    :param initial_editors: Bootstrap editor subjects that cannot be revoked.
    :returns: ``"editor"`` or ``"consumer"``.
    """
    if sub and sub in (initial_editors or []):
        return EDITOR
    record = _load(path).get(sub)
    if record and record.get("role") in VALID_ROLES:
        return str(record["role"])
    return CONSUMER


def is_bootstrap_editor(sub: str, initial_editors: list[str] | None) -> bool:
    """Return whether *sub* is a non-revocable env-seeded editor."""
    return bool(sub) and sub in (initial_editors or [])


def set_role(
    path: Path, sub: str, role: str, label: str = ""
) -> dict[str, Any]:
    """
    Assign *role* to *sub* and persist it.

    :param path: Role store file path.
    :param sub: Subject to update.
    :param role: ``"editor"`` or ``"consumer"``.
    :param label: Optional human-readable label.
    :returns: The stored record (including ``sub``).
    :raises ValueError: If *role* is not a known role or *sub* is empty.
    """
    if not sub:
        raise ValueError("A subject is required.")
    if role not in VALID_ROLES:
        raise ValueError(f"Unknown role: {role!r}")
    records = _load(path)
    record = {
        "role": role,
        "label": label or records.get(sub, {}).get("label", ""),
        "updated": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    records[sub] = record
    _save(path, records)
    return {"sub": sub, **record}


def remove(
    path: Path, sub: str, *, initial_editors: list[str] | None = None
) -> bool:
    """
    Delete a subject's stored record (reverting them to the default).

    Idempotent. Refuses to remove a bootstrap editor (they are env-defined and
    removing the record would not change their effective role anyway).

    :param path: Role store file path.
    :param sub: Subject to remove.
    :param initial_editors: Bootstrap editors that cannot be removed.
    :returns: ``True`` if a record was deleted.
    :raises ValueError: If *sub* is a bootstrap editor.
    """
    if is_bootstrap_editor(sub, initial_editors):
        raise ValueError(
            "Bootstrap editors (QM_INITIAL_EDITORS) cannot be removed."
        )
    records = _load(path)
    if sub in records:
        del records[sub]
        _save(path, records)
        return True
    return False


def list_all(
    path: Path, *, initial_editors: list[str] | None = None
) -> list[dict[str, Any]]:
    """
    List every known subject with its effective role.

    Unions the stored records with the bootstrap editors so an admin UI shows
    env-seeded editors (as read-only ``source="bootstrap"`` rows) even before
    they have ever been written to the store.

    :param path: Role store file path.
    :param initial_editors: Bootstrap editor subjects.
    :returns: Records sorted by subject, each ``{sub, role, label, updated,
        source}`` where ``source`` is ``"bootstrap"`` or ``"store"``.
    """
    bootstrap = list(initial_editors or [])
    records = _load(path)
    out: list[dict[str, Any]] = []
    for sub in bootstrap:
        stored = records.get(sub, {})
        out.append(
            {
                "sub": sub,
                "role": EDITOR,
                "label": stored.get("label", ""),
                "updated": stored.get("updated", ""),
                "source": "bootstrap",
            }
        )
    for sub, record in records.items():
        if sub in bootstrap:
            continue
        out.append(
            {
                "sub": sub,
                "role": record.get("role", CONSUMER),
                "label": record.get("label", ""),
                "updated": record.get("updated", ""),
                "source": "store",
            }
        )
    return sorted(out, key=lambda r: r["sub"])
