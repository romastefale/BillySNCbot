from __future__ import annotations

from app.bot.reactionless_bot import install_reaction_block

# Reaction blocking is installed first. The link-safety guard then wraps the
# already-protected Bot.__call__, so both process-wide policies remain active.
install_reaction_block()

from app.bot.group_link_safety import install_group_link_safety

install_group_link_safety()

from app.bot.telegram import bot_dispatcher

__all__ = ["bot_dispatcher"]
