from __future__ import annotations

from app.bot.reactionless_bot import install_reaction_block

# Process-wide policies are installed in layers. Each later guard wraps the
# previous Bot.__call__, preserving reaction blocking and group link safety.
install_reaction_block()

from app.bot.group_link_safety import install_group_link_safety

install_group_link_safety()

# Telegram-local user references are not external links. Install this narrow
# allowance after the external-link guard has defined its policy and before
# progressive rendering starts dispatching frames through that guard.
from app.bot.internal_user_mentions import install_internal_user_mention_allowance

install_internal_user_mention_allowance()

from app.bot.progressive_music_text import install_progressive_music_text

install_progressive_music_text()

from app.bot.telegram import bot_dispatcher

__all__ = ["bot_dispatcher"]
