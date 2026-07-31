from __future__ import annotations

import asyncio
from types import SimpleNamespace

from aiogram.types import (
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
    BotCommandScopeDefault,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from app.bot import allow as allow_bot
from app.bot import setup_commands
from app.services import allow_control


def _message_update(text: str):
    return SimpleNamespace(
        message=SimpleNamespace(text=text, caption=None),
        edited_message=None,
        callback_query=None,
    )


def _callback_update(data: str):
    return SimpleNamespace(
        message=None,
        edited_message=None,
        callback_query=SimpleNamespace(data=data),
    )


def test_state_keys_are_persistent_and_default_to_enabled(monkeypatch) -> None:
    reads: list[tuple[str, bool]] = []
    writes: list[tuple[str, bool, int | None]] = []

    def fake_get(key: str, default: bool = False) -> bool:
        reads.append((key, default))
        return default

    def fake_set(key: str, enabled: bool, *, owner_user_id: int | None = None) -> None:
        writes.append((key, enabled, owner_user_id))

    monkeypatch.setattr(allow_control, "get_state_bool", fake_get)
    monkeypatch.setattr(allow_control, "set_state_bool", fake_set)

    assert allow_control.is_feature_enabled("tnow") is True
    allow_control.set_feature_enabled("tnow", False, owner_user_id=123)

    assert reads == [("allow_feature_tnow", True)]
    assert writes == [("allow_feature_tnow", False, 123)]


def test_disabled_command_is_silently_dropped_only_for_non_owner(monkeypatch) -> None:
    monkeypatch.setattr(
        allow_control,
        "command_is_publicly_enabled",
        lambda command: command != "tnow",
    )

    update = _message_update("/tnow")
    assert allow_control.should_drop_update_for_allow_controls(update, is_owner=False) is True
    assert allow_control.should_drop_update_for_allow_controls(update, is_owner=True) is False
    assert allow_control.should_drop_update_for_allow_controls(
        _message_update("/playing"), is_owner=False
    ) is False


def test_old_callbacks_are_blocked_after_feature_is_disabled(monkeypatch) -> None:
    states = {"songcharts": False, "myself": True, "weekfm": False, "monthfm": True}
    monkeypatch.setattr(
        allow_control,
        "is_feature_enabled",
        lambda feature: states.get(feature, True),
    )

    assert allow_control.should_drop_update_for_allow_controls(
        _callback_update("songcharts:g:w:-100:10"), is_owner=False
    ) is True
    assert allow_control.should_drop_update_for_allow_controls(
        _callback_update("myself:w:10"), is_owner=False
    ) is True
    assert allow_control.should_drop_update_for_allow_controls(
        _callback_update("myself:m:10"), is_owner=False
    ) is False


def test_myself_depends_on_at_least_one_visible_period(monkeypatch) -> None:
    states = {"myself": True, "weekfm": False, "monthfm": False}
    monkeypatch.setattr(
        allow_control,
        "is_feature_enabled",
        lambda feature: states.get(feature, True),
    )
    assert allow_control.command_is_publicly_enabled("myself") is False

    states["monthfm"] = True
    assert allow_control.command_is_publicly_enabled("myself") is True


def test_ux_text_removes_only_disabled_command_lines(monkeypatch) -> None:
    monkeypatch.setattr(
        allow_control,
        "command_is_publicly_enabled",
        lambda command: command not in {"tnow", "weekfm"},
    )
    text = (
        "<b>Comandos</b>\n\n"
        "<code>/playing</code> — música atual.\n"
        "<code>/tnow</code> — mosaico.\n"
        "<code>/weekfm</code> — semana."
    )

    filtered = allow_control.filter_ux_text(text)
    assert "/playing" in filtered
    assert "/tnow" not in filtered
    assert "/weekfm" not in filtered


def test_myself_keyboard_hides_disabled_periods(monkeypatch) -> None:
    states = {"myself": True, "weekfm": False, "monthfm": True}
    monkeypatch.setattr(
        allow_control,
        "is_feature_enabled",
        lambda feature: states.get(feature, True),
    )
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Semanal", callback_data="myself:w:1"),
                InlineKeyboardButton(text="Mensal", callback_data="myself:m:1"),
            ]
        ]
    )

    filtered = allow_control.filter_myself_keyboard(markup)
    assert filtered is not None
    assert [button.text for button in filtered.inline_keyboard[0]] == ["Mensal"]


def test_allow_panel_uses_check_and_x_symbols(monkeypatch) -> None:
    states = {feature: True for feature in allow_control.CONTROLLED_FEATURES}
    states["songcharts"] = False
    monkeypatch.setattr(allow_bot, "feature_states", lambda: states)

    markup = allow_bot._panel_keyboard()
    labels = [row[0].text for row in markup.inline_keyboard]

    assert "✅ /tnow" in labels
    assert "❌ /songcharts" in labels
    assert len(labels) == len(allow_control.CONTROLLED_FEATURES)


class _FakeBot:
    def __init__(self) -> None:
        self.deleted_scopes = []
        self.set_calls = []

    async def delete_my_commands(self, *, scope) -> None:
        self.deleted_scopes.append(scope)

    async def set_my_commands(self, commands, *, scope) -> None:
        self.set_calls.append((commands, scope))


def test_setup_commands_hides_disabled_features_and_group_menu(monkeypatch) -> None:
    bot = _FakeBot()
    monkeypatch.setattr(setup_commands, "ensure_allow_runtime", lambda: None)
    monkeypatch.setattr(setup_commands, "CODE_OWNER_IDS", {123})
    monkeypatch.setattr(
        setup_commands,
        "command_is_publicly_enabled",
        lambda command: command != "tnow" and command != "legacy",
    )

    asyncio.run(setup_commands.setup_bot_commands(bot))

    assert any(isinstance(scope, BotCommandScopeDefault) for scope in bot.deleted_scopes)
    assert any(isinstance(scope, BotCommandScopeAllGroupChats) for scope in bot.deleted_scopes)

    private = next(
        commands
        for commands, scope in bot.set_calls
        if isinstance(scope, BotCommandScopeAllPrivateChats)
    )
    owner = next(
        commands for commands, scope in bot.set_calls if isinstance(scope, BotCommandScopeChat)
    )
    private_names = {item.command for item in private}
    owner_names = {item.command for item in owner}

    assert "tnow" not in private_names
    assert "legacy" not in owner_names
    assert "allow" in owner_names
    assert len([scope for _, scope in bot.set_calls if isinstance(scope, BotCommandScopeAllGroupChats)]) == 0
