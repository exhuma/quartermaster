"""Behavioural tests for the shipped Claude Code hook scripts.

The three hook scripts under ``webui/src/docs/claude-code/`` are the canonical,
copy-pasteable reference that the Integrate page inlines verbatim (via Vite
``?raw``) and that this repo dogfoods through ``.claude/settings.json``. These
tests run the *actual* scripts with sample hook payloads so the documented
behaviour can never silently drift from what ships.

They shell out to ``bash`` and ``jq``; the whole module is skipped when either
is unavailable (e.g. a minimal CI image).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

# server/tests/ -> repo root -> webui/src/docs/claude-code/
_HOOKS_DIR = (
    Path(__file__).resolve().parents[2] / "webui" / "src" / "docs" / "claude-code"
)
_EDIT = _HOOKS_DIR / "qm-edit-reminder.sh"
_RECORD = _HOOKS_DIR / "qm-record-resolve.sh"
_PROMPT = _HOOKS_DIR / "qm-prompt-reminder.sh"
_SETTINGS = _HOOKS_DIR / "settings.json"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("jq") is None,
    reason="hook scripts require bash and jq",
)


def _run(script: Path, payload: str, cache_home: Path) -> subprocess.CompletedProcess:
    """Run a hook script with *payload* on stdin and an isolated cache dir."""
    return subprocess.run(
        ["bash", str(script)],
        input=payload,
        capture_output=True,
        text=True,
        env={"HOME": str(cache_home), "XDG_CACHE_HOME": str(cache_home), "PATH": _path()},
        check=True,
    )


def _path() -> str:
    import os

    return os.environ.get("PATH", "")


def test_scripts_exist_and_executable() -> None:
    for script in (_EDIT, _RECORD, _PROMPT):
        assert script.is_file(), f"missing hook script: {script}"


def test_nudge_before_resolve(tmp_path: Path) -> None:
    """A fresh session with no resolve recorded → non-blocking JSON nudge."""
    result = _run(_EDIT, json.dumps({"session_id": "s1"}), tmp_path)
    payload = json.loads(result.stdout)  # must be valid JSON
    hook_out = payload["hookSpecificOutput"]
    assert hook_out["hookEventName"] == "PreToolUse"
    assert "resolve_kits" in hook_out["additionalContext"]
    # Non-blocking: no permission decision is emitted, so the edit proceeds.
    assert "permissionDecision" not in hook_out


def test_silent_after_resolve(tmp_path: Path) -> None:
    """Once resolve_kits is recorded for the session, the nudge goes silent."""
    _run(_RECORD, json.dumps({"session_id": "s1"}), tmp_path)
    result = _run(_EDIT, json.dumps({"session_id": "s1"}), tmp_path)
    assert result.stdout.strip() == ""


def test_renudge_in_new_session(tmp_path: Path) -> None:
    """Recording one session must not silence a different session."""
    _run(_RECORD, json.dumps({"session_id": "s1"}), tmp_path)
    result = _run(_EDIT, json.dumps({"session_id": "s2"}), tmp_path)
    payload = json.loads(result.stdout)
    assert payload["hookSpecificOutput"]["hookEventName"] == "PreToolUse"


def test_prompt_reminder_mentions_resolve_kits(tmp_path: Path) -> None:
    result = _run(_PROMPT, "", tmp_path)
    assert result.stdout.strip()
    assert "resolve_kits" in result.stdout


def test_settings_json_is_valid_and_wires_three_hooks() -> None:
    hooks = json.loads(_SETTINGS.read_text())["hooks"]
    assert set(hooks) == {"UserPromptSubmit", "PreToolUse", "PostToolUse"}
    assert hooks["PreToolUse"][0]["matcher"] == "Edit|Write|MultiEdit|NotebookEdit"
    assert (
        hooks["PostToolUse"][0]["matcher"] == "mcp__quartermaster__resolve_kits"
    )
