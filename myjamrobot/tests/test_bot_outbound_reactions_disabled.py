from __future__ import annotations

from pathlib import Path

import pytest
from aiogram import Bot
from aiogram.methods import SetMessageReaction
from aiogram.types import ReactionTypeEmoji

from app.bot.reactionless_bot import install_reaction_block

ROOT = Path(__file__).resolve().parents[1]
BOT_INIT_SRC = (ROOT / "app" / "bot" / "__init__.py").read_text(encoding="utf-8")
TELEGRAM_SRC = (ROOT / "app" / "bot" / "telegram.py").read_text(encoding="utf-8")

_FAKE_TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"


@pytest.mark.asyncio
async def test_set_message_reaction_is_acknowledged_without_network() -> None:
    install_reaction_block()
    bot = Bot(token=_FAKE_TOKEN)
    try:
        result = await bot.set_message_reaction(
            chat_id=-1001234567890,
            message_id=42,
            reaction=[ReactionTypeEmoji(emoji="🔥")],
        )
    finally:
        await bot.session.close()

    assert result is True


@pytest.mark.asyncio
async def test_direct_set_message_reaction_method_is_also_blocked() -> None:
    install_reaction_block()
    bot = Bot(token=_FAKE_TOKEN)
    method = SetMessageReaction(
        chat_id=-1001234567890,
        message_id=42,
        reaction=[ReactionTypeEmoji(emoji="❤")],
    )
    try:
        result = await bot(method)
    finally:
        await bot.session.close()

    assert result is True


def test_reaction_block_is_installed_before_dispatcher_import() -> None:
    install_pos = BOT_INIT_SRC.index("install_reaction_block()")
    dispatcher_pos = BOT_INIT_SRC.index("from app.bot.telegram import bot_dispatcher")
    assert install_pos < dispatcher_pos


def test_human_reaction_tracking_handler_remains_registered() -> None:
    assert "@dp.message_reaction()" in TELEGRAM_SRC
    assert "apply_reaction_change" in TELEGRAM_SRC
