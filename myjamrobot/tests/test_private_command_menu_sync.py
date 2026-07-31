from __future__ import annotations

import re
from pathlib import Path

from app.bot import setup_commands


ROOT = Path(__file__).resolve().parents[1]
ALLOW_CONTROL_SRC = (ROOT / "app" / "services" / "allow_control.py").read_text(encoding="utf-8")
_HELP_COMMAND_RE = re.compile(r"<code>/([a-z0-9_]+)</code>")


def _command_names(*, is_owner: bool) -> list[str]:
    return [
        item.command
        for item in setup_commands.private_command_definitions(is_owner=is_owner)
    ]


def _help_names(*, is_owner: bool) -> list[str]:
    return _HELP_COMMAND_RE.findall(
        setup_commands.private_help_text(is_owner=is_owner)
    )


def test_common_private_help_exactly_matches_published_menu(monkeypatch) -> None:
    monkeypatch.setattr(
        setup_commands,
        "command_is_publicly_enabled",
        lambda command: command not in {"login", "tcanvas", "weekfm"},
    )

    names = _command_names(is_owner=False)

    assert _help_names(is_owner=False) == names
    assert "login" not in names
    assert "tcanvas" not in names
    assert "weekfm" not in names
    assert "tiddd" in names
    assert "hitmo" in names


def test_owner_private_help_exactly_matches_published_menu(monkeypatch) -> None:
    monkeypatch.setattr(
        setup_commands,
        "command_is_publicly_enabled",
        lambda command: command != "legacy",
    )

    names = _command_names(is_owner=True)

    assert _help_names(is_owner=True) == names
    assert "legacy" not in names
    assert "allow" in names
    assert "tnow" in names
    assert "lfmcheckauth" in names
    assert "lfmimportcsv" in names
    assert "tmn" in names
    assert "tpv" in names
    assert "onoff" in names
    assert "listening" in names


def test_private_catalog_has_no_duplicate_commands() -> None:
    for is_owner in (False, True):
        names = _command_names(is_owner=is_owner)
        assert len(names) == len(set(names))


def test_private_help_runtime_uses_shared_catalog() -> None:
    assert "from app.bot.setup_commands import private_help_text" in ALLOW_CONTROL_SRC
    assert "return private_help_text(is_owner=is_code_owner(user_id))" in ALLOW_CONTROL_SRC
