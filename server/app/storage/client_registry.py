"""
File-backed registry of recognised client User-Agents.

Non-browser clients (coding agents, scripts) must register their
User-Agent before using the API or MCP endpoint, so each client can be
uniquely identified. This is an *identification* aid, not a strong
security gate — the registry is a small JSON file written atomically via
the shared kit writer.

Record shape: ``{"id": <hash>, "user_agent": <str>, "label": <str>}``.
The id is a stable short hash of the User-Agent, so re-registering the
same User-Agent updates the existing record rather than duplicating it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.storage.kit_writes import atomic_write_text


def client_id(user_agent: str) -> str:
    """
    Return a stable short id for a User-Agent string.

    :param user_agent: The client's User-Agent.
    :returns: First 12 hex chars of its SHA-256 digest.
    """
    return hashlib.sha256(user_agent.encode("utf-8")).hexdigest()[:12]


def load_clients(path: Path) -> list[dict[str, Any]]:
    """
    Load all registered clients.

    :param path: Registry file path.
    :returns: List of client records (empty if the file is absent).
    """
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, list) else []


def is_registered(path: Path, user_agent: str) -> bool:
    """
    Report whether *user_agent* is registered.

    :param path: Registry file path.
    :param user_agent: User-Agent to look up.
    :returns: ``True`` if a matching record exists.
    """
    if not user_agent:
        return False
    target = client_id(user_agent)
    return any(c.get("id") == target for c in load_clients(path))


def register(path: Path, user_agent: str, label: str = "") -> dict[str, Any]:
    """
    Register (or update the label of) a client User-Agent. Idempotent.

    :param path: Registry file path.
    :param user_agent: User-Agent to register (must be non-empty).
    :param label: Optional human-readable label.
    :returns: The stored client record.
    :raises ValueError: If *user_agent* is empty.
    """
    if not user_agent.strip():
        raise ValueError("user_agent must not be empty")
    clients = load_clients(path)
    cid = client_id(user_agent)
    for record in clients:
        if record.get("id") == cid:
            record["label"] = label or record.get("label", "")
            break
    else:
        record = {"id": cid, "user_agent": user_agent, "label": label}
        clients.append(record)
    atomic_write_text(path, json.dumps(clients, indent=2) + "\n")
    return record


def unregister(path: Path, client_id_value: str) -> None:
    """
    Remove a client by id. Idempotent.

    :param path: Registry file path.
    :param client_id_value: The id to remove (no error if absent).
    """
    clients = load_clients(path)
    remaining = [c for c in clients if c.get("id") != client_id_value]
    if len(remaining) != len(clients):
        atomic_write_text(path, json.dumps(remaining, indent=2) + "\n")
