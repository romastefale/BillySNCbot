from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot
from aiogram.methods import SetMessageReaction

logger = logging.getLogger(__name__)


class ReactionlessBot(Bot):
    """Telegram client that never sends native message reactions.

    User-generated reaction updates are unaffected because this policy only
    intercepts outbound ``SetMessageReaction`` methods. Both the convenience
    method and direct TelegramMethod dispatch are blocked so existing and
    future callers cannot bypass the policy accidentally.
    """

    async def set_message_reaction(self, *args: Any, **kwargs: Any) -> bool:
        logger.debug("TELEGRAM_REACTION_SUPPRESSED method=set_message_reaction")
        return True

    async def __call__(self, method: Any, request_timeout: int | None = None) -> Any:
        if isinstance(method, SetMessageReaction):
            logger.debug("TELEGRAM_REACTION_SUPPRESSED method=SetMessageReaction")
            return True
        return await super().__call__(method, request_timeout=request_timeout)
