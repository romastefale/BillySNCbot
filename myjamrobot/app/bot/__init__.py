from __future__ import annotations

from app.bot.reactionless_bot import install_reaction_block

install_reaction_block()

from app.bot.telegram import bot_dispatcher

__all__ = ["bot_dispatcher"]
