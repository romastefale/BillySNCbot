from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import Bot
from aiogram.methods import SetMessageReaction

logger = logging.getLogger(__name__)

_ORIGINAL_CALL_ATTR = "_myjam_original_bot_call"
_INSTALLED_ATTR = "_myjam_reaction_block_installed"


async def _suppress_set_message_reaction(self: Bot, *args: Any, **kwargs: Any) -> bool:
    """Acknowledge the request locally without contacting Telegram."""
    logger.debug("TELEGRAM_REACTION_SUPPRESSED method=set_message_reaction")
    return True


async def _guard_bot_call(self: Bot, method: Any, request_timeout: int | None = None) -> Any:
    """Block direct ``bot(SetMessageReaction(...))`` dispatch as well."""
    if isinstance(method, SetMessageReaction):
        logger.debug("TELEGRAM_REACTION_SUPPRESSED method=SetMessageReaction")
        return True

    original = getattr(Bot, _ORIGINAL_CALL_ATTR)
    return await original(self, method, request_timeout=request_timeout)


def install_reaction_block() -> None:
    """Disable native Telegram reactions for every Bot instance in the process.

    The installation is idempotent and affects outbound calls only. Telegram
    updates produced by human reactions continue through the dispatcher and the
    existing reaction tracking handlers unchanged.
    """
    if getattr(Bot, _INSTALLED_ATTR, False):
        return

    original_call: Callable[..., Awaitable[Any]] = Bot.__call__
    setattr(Bot, _ORIGINAL_CALL_ATTR, original_call)
    Bot.set_message_reaction = _suppress_set_message_reaction  # type: ignore[method-assign]
    Bot.__call__ = _guard_bot_call  # type: ignore[method-assign]
    setattr(Bot, _INSTALLED_ATTR, True)
    logger.info("TELEGRAM_OUTBOUND_REACTIONS_DISABLED")
