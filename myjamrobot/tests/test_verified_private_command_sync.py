from __future__ import annotations

import asyncio

import pytest
from aiogram.types import BotCommandScopeAllPrivateChats, BotCommandScopeChat

from app.bot import allow as allow_bot
from app.bot import setup_commands


def _scope_key(scope) -> tuple[str, int | None]:
    if isinstance(scope, BotCommandScopeChat):
        return ("chat", int(scope.chat_id))
    return (type(scope).__name__, None)


class _VerifiableBot:
    def __init__(self) -> None:
        self.commands: dict[tuple[str, int | None], list] = {}
        self.publish_count = 0

    async def delete_my_commands(self, *, scope) -> None:
        self.commands[_scope_key(scope)] = []

    async def set_my_commands(self, commands, *, scope) -> None:
        self.publish_count += 1
        self.commands[_scope_key(scope)] = list(commands)

    async def get_my_commands(self, *, scope):
        return list(self.commands.get(_scope_key(scope), []))


class _AlwaysMismatchedBot(_VerifiableBot):
    async def get_my_commands(self, *, scope):
        if isinstance(scope, BotCommandScopeAllPrivateChats):
            return []
        return await super().get_my_commands(scope=scope)


class _MismatchOnceBot(_VerifiableBot):
    def __init__(self) -> None:
        super().__init__()
        self.private_reads = 0

    async def get_my_commands(self, *, scope):
        if isinstance(scope, BotCommandScopeAllPrivateChats):
            self.private_reads += 1
            if self.private_reads == 1:
                return []
        return await super().get_my_commands(scope=scope)


def _isolate_catalog(monkeypatch) -> None:
    monkeypatch.setattr(setup_commands, "ensure_allow_runtime", lambda: None)
    monkeypatch.setattr(setup_commands, "command_is_publicly_enabled", lambda _command: True)


def test_setup_commands_raises_when_telegram_readback_does_not_match(monkeypatch) -> None:
    bot = _AlwaysMismatchedBot()
    _isolate_catalog(monkeypatch)
    monkeypatch.setattr(setup_commands, "CODE_OWNER_IDS", {123})

    with pytest.raises(setup_commands.CommandMenuSyncError):
        asyncio.run(
            setup_commands.setup_bot_commands(
                bot,
                attempts=1,
                raise_on_error=True,
            )
        )


def test_setup_commands_retries_and_only_returns_after_verified_readback(monkeypatch) -> None:
    bot = _MismatchOnceBot()
    _isolate_catalog(monkeypatch)
    monkeypatch.setattr(setup_commands, "CODE_OWNER_IDS", {123})
    monkeypatch.setattr(setup_commands, "_COMMAND_SYNC_RETRY_SECONDS", 0)

    result = asyncio.run(
        setup_commands.setup_bot_commands(
            bot,
            attempts=2,
            raise_on_error=True,
        )
    )

    assert result is True
    assert bot.private_reads == 2
    assert ("chat", 123) in bot.commands


def test_setup_commands_returns_false_in_non_raising_startup_mode(monkeypatch) -> None:
    bot = _AlwaysMismatchedBot()
    _isolate_catalog(monkeypatch)
    monkeypatch.setattr(setup_commands, "CODE_OWNER_IDS", set())

    result = asyncio.run(
        setup_commands.setup_bot_commands(
            bot,
            attempts=1,
            raise_on_error=False,
        )
    )

    assert result is False


def test_allow_toggle_rolls_back_state_when_menu_sync_fails(monkeypatch) -> None:
    state = {"login": True}
    writes: list[bool] = []
    sync_calls = 0

    monkeypatch.setattr(allow_bot, "is_feature_enabled", lambda feature: state[feature])

    def fake_set(feature: str, enabled: bool, *, owner_user_id: int | None = None) -> None:
        assert owner_user_id == 123
        state[feature] = enabled
        writes.append(enabled)

    async def fake_sync(_bot) -> None:
        nonlocal sync_calls
        sync_calls += 1
        if sync_calls == 1:
            raise RuntimeError("Telegram did not confirm the menu")

    monkeypatch.setattr(allow_bot, "set_feature_enabled", fake_set)
    monkeypatch.setattr(allow_bot, "_sync_private_command_menu", fake_sync)

    with pytest.raises(RuntimeError, match="did not confirm"):
        asyncio.run(
            allow_bot._toggle_feature_with_verified_menu(
                object(),
                feature="login",
                owner_user_id=123,
            )
        )

    assert state["login"] is True
    assert writes == [False, True]
    assert sync_calls == 2


def test_allow_toggle_commits_state_after_verified_sync(monkeypatch) -> None:
    state = {"login": True}
    writes: list[bool] = []

    monkeypatch.setattr(allow_bot, "is_feature_enabled", lambda feature: state[feature])

    def fake_set(feature: str, enabled: bool, *, owner_user_id: int | None = None) -> None:
        state[feature] = enabled
        writes.append(enabled)

    async def fake_sync(_bot) -> None:
        return None

    monkeypatch.setattr(allow_bot, "set_feature_enabled", fake_set)
    monkeypatch.setattr(allow_bot, "_sync_private_command_menu", fake_sync)

    enabled = asyncio.run(
        allow_bot._toggle_feature_with_verified_menu(
            object(),
            feature="login",
            owner_user_id=123,
        )
    )

    assert enabled is False
    assert state["login"] is False
    assert writes == [False]
