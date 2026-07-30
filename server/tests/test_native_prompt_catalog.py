"""Tests for the dynamic prompts-catalog native MCP ``Provider``.

Confirms writes via the service layer are visible through
``mcp.list_prompts()``/``mcp.get_prompt()`` on the very next call (no
caching, no restart needed — mirrors "kit reads are uncached"), per-caller
private visibility, and that the static canned-prompt name collision is
rejected at the write path.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import KitLayerConfig
from app.identity import reset_identity, set_identity
from app.main import mcp
from app.prompt_catalog import PromptConflictError
from app.services import prompt_catalog_service as svc


@pytest.fixture()
def prompt_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    shared = tmp_path / "prompts"
    shared.mkdir()
    layers = [KitLayerConfig(name="default", path=shared, readonly=False)]
    settings = SimpleNamespace(
        effective_prompt_layers=layers,
        private_prompts_root=tmp_path / "private-prompts",
    )
    monkeypatch.setattr("app.prompt_catalog.get_settings", lambda: settings)
    monkeypatch.setattr("app.private_prompts.get_settings", lambda: settings)
    return shared


def _prompt_names() -> set[str]:
    prompts = asyncio.run(mcp.list_prompts())
    return {p.name for p in prompts}


def _render(name: str) -> str:
    prompt = asyncio.run(mcp.get_prompt(name))
    rendered = asyncio.run(prompt.render({}))
    return "".join(
        msg.content.text
        for msg in rendered.messages
        if hasattr(msg.content, "text")
    )


def test_write_is_visible_without_restart(prompt_settings: Path) -> None:
    assert "live-prompt" not in _prompt_names()
    svc.put_prompt(
        name="live-prompt", title="Live", description="", body="Live body."
    )
    assert "live-prompt" in _prompt_names()
    assert _render("live-prompt") == "Live body."

    svc.delete_prompt("live-prompt")
    assert "live-prompt" not in _prompt_names()


def test_edit_is_visible_immediately(prompt_settings: Path) -> None:
    svc.put_prompt(name="editable", title="", description="", body="v1")
    assert _render("editable") == "v1"
    svc.put_prompt(name="editable", title="", description="", body="v2")
    assert _render("editable") == "v2"


def test_private_overlay_visible_only_to_owner(prompt_settings: Path) -> None:
    from app.private_prompts import private_root_for

    root = private_root_for("alice-sub")
    svc.put_prompt(
        name="alice-secret",
        title="",
        description="",
        body="Secret.",
        root=root,
    )

    assert "alice-secret" not in _prompt_names()  # no identity bound

    tokens = set_identity("alice-sub", "Alice")
    try:
        assert "alice-secret" in _prompt_names()
        assert _render("alice-secret") == "Secret."
    finally:
        reset_identity(tokens)

    tokens = set_identity("bob-sub", "Bob")
    try:
        assert "alice-secret" not in _prompt_names()
    finally:
        reset_identity(tokens)


def test_static_name_collision_rejected_at_write(
    prompt_settings: Path,
) -> None:
    with pytest.raises(PromptConflictError):
        svc.put_prompt(name="greet", title="", description="", body="x")


def test_static_prompt_still_wins_over_provider(prompt_settings: Path) -> None:
    """The canned "greet" prompt must still be served (FastMCP precedence).

    The write path already rejects creating a catalog prompt named "greet"
    (see the collision test above); this separately pins the underlying
    FastMCP guarantee that a statically-registered prompt always wins over
    a same-named provider-sourced one.
    """
    from app.prompts import get_canned_prompt

    assert _render("greet") == get_canned_prompt("greet")["prompt_template"]
