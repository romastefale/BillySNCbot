from __future__ import annotations

import logging
import re
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Dispatcher
from aiogram.types import InlineKeyboardMarkup, TelegramObject

from app.services.ops_control import get_state_bool, set_state_bool

logger = logging.getLogger(__name__)

CONTROLLED_FEATURES: tuple[str, ...] = (
    "tnow",
    "songcharts",
    "weekfm",
    "monthfm",
    "tcanvas",
    "login",
    "albnow",
    "myself",
    "legacy",
)

FEATURE_LABELS: dict[str, str] = {
    "tnow": "tnow",
    "songcharts": "songcharts",
    "weekfm": "weekfm",
    "monthfm": "monthfm",
    "tcanvas": "tcanvas",
    "login": "login",
    "albnow": "albnow",
    "myself": "myself",
    "legacy": "legacy",
}

_COMMAND_TO_FEATURE: dict[str, str] = {
    "tnow": "tnow",
    "songcharts": "songcharts",
    "weekfm": "weekfm",
    "monthfm": "monthfm",
    "tcanvas": "tcanvas",
    "login": "login",
    "albnow": "albnow",
    "myself": "myself",
    "legacy": "legacy",
}


def _state_key(feature: str) -> str:
    if feature not in CONTROLLED_FEATURES:
        raise ValueError(f"Unknown controlled feature: {feature}")
    return f"allow_feature_{feature}"


def is_feature_enabled(feature: str) -> bool:
    return get_state_bool(_state_key(feature), default=True)


def set_feature_enabled(feature: str, enabled: bool, *, owner_user_id: int | None = None) -> None:
    set_state_bool(_state_key(feature), enabled, owner_user_id=owner_user_id)


def feature_states() -> dict[str, bool]:
    return {feature: is_feature_enabled(feature) for feature in CONTROLLED_FEATURES}


def command_feature(command: str | None) -> str | None:
    return _COMMAND_TO_FEATURE.get((command or "").strip().lower())


def command_is_publicly_enabled(command: str) -> bool:
    feature = command_feature(command)
    if feature is None:
        return True
    if feature == "myself":
        return bool(
            is_feature_enabled("myself")
            and (is_feature_enabled("weekfm") or is_feature_enabled("monthfm"))
        )
    return is_feature_enabled(feature)


def _command_name_from_text(value: str | None) -> str | None:
    if not value:
        return None
    token = value.strip().split(maxsplit=1)[0]
    if not token.startswith("/"):
        return None
    return token[1:].split("@", 1)[0].strip().lower() or None


def _message_command(update: Any) -> str | None:
    message = getattr(update, "message", None) or getattr(update, "edited_message", None)
    if message is None:
        return None
    return _command_name_from_text(getattr(message, "text", None) or getattr(message, "caption", None))


def _callback_feature(update: Any) -> str | None:
    callback = getattr(update, "callback_query", None)
    data = str(getattr(callback, "data", "") or "")
    if data.startswith("songcharts:"):
        return "songcharts"
    if data.startswith("myself:w:"):
        if not is_feature_enabled("myself"):
            return "myself"
        return "weekfm"
    if data.startswith("myself:m:"):
        if not is_feature_enabled("myself"):
            return "myself"
        return "monthfm"
    return None


def should_drop_update_for_allow_controls(update: Any, *, is_owner: bool) -> bool:
    if is_owner:
        return False
    command = _message_command(update)
    if command is not None and not command_is_publicly_enabled(command):
        return True
    feature = _callback_feature(update)
    return bool(feature and not is_feature_enabled(feature))


def filter_ux_text(text: str) -> str:
    """Remove linhas que anunciam comandos desativados, preservando o resto da mensagem."""
    disabled = tuple(
        command for command in _COMMAND_TO_FEATURE if not command_is_publicly_enabled(command)
    )
    if not disabled:
        return text

    command_patterns = tuple(re.compile(rf"/{re.escape(command)}(?:\b|<)", re.IGNORECASE) for command in disabled)
    kept = [line for line in str(text).splitlines() if not any(pattern.search(line) for pattern in command_patterns)]
    cleaned = "\n".join(kept)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def filter_myself_keyboard(markup: InlineKeyboardMarkup | None) -> InlineKeyboardMarkup | None:
    if markup is None or not is_feature_enabled("myself"):
        return None
    rows = []
    for row in markup.inline_keyboard:
        visible = []
        for button in row:
            data = str(button.callback_data or "")
            if data.startswith("myself:w:") and not is_feature_enabled("weekfm"):
                continue
            if data.startswith("myself:m:") and not is_feature_enabled("monthfm"):
                continue
            visible.append(button)
        if visible:
            rows.append(visible)
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def install_allow_ux_filters() -> None:
    """Instala filtros dinâmicos sem alterar os handlers funcionais existentes."""
    from app.bot import myself as myself_module
    from app.bot import telegram as telegram_module

    if not getattr(telegram_module, "_myjam_allow_ux_installed", False):
        original_start = telegram_module._start_text
        original_help = telegram_module._help_text

        def _start_text_filtered(message):
            return filter_ux_text(original_start(message))

        def _help_text_filtered(message):
            if getattr(getattr(message, "chat", None), "type", None) == "private":
                from app.bot.setup_commands import private_help_text
                from app.config.settings import is_code_owner

                user_id = getattr(getattr(message, "from_user", None), "id", None)
                return private_help_text(is_owner=is_code_owner(user_id))
            return filter_ux_text(original_help(message))

        telegram_module._start_text = _start_text_filtered
        telegram_module._help_text = _help_text_filtered
        setattr(telegram_module, "_myjam_allow_ux_installed", True)

    if not getattr(myself_module, "_myjam_allow_ux_installed", False):
        original_menu = myself_module._menu_keyboard

        def _menu_keyboard_filtered(requester_id: int):
            return filter_myself_keyboard(original_menu(requester_id))

        myself_module._menu_keyboard = _menu_keyboard_filtered
        setattr(myself_module, "_myjam_allow_ux_installed", True)


class AllowControlMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        from app.config.settings import is_code_owner
        from app.services.ops_control import user_id_from_update

        user_id = user_id_from_update(event)
        if should_drop_update_for_allow_controls(event, is_owner=is_code_owner(user_id)):
            logger.info("DISPATCHER_UPDATE_DROPPED_BY_ALLOW_CONTROL user_id=%s", user_id)
            return None
        return await handler(event, data)


def install_allow_control_middleware(dispatcher: Dispatcher) -> None:
    if getattr(dispatcher, "_myjam_allow_control_middleware_installed", False):
        return
    dispatcher.update.outer_middleware(AllowControlMiddleware())
    setattr(dispatcher, "_myjam_allow_control_middleware_installed", True)


def ensure_allow_runtime() -> None:
    """Conecta o /allow ao dispatcher global uma única vez durante o startup."""
    from app.bot.telegram import bot_dispatcher

    install_allow_control_middleware(bot_dispatcher)
    install_allow_ux_filters()
    if getattr(bot_dispatcher, "_myjam_allow_router_installed", False):
        return

    from app.bot.allow import router as allow_router

    bot_dispatcher.include_router(allow_router)
    setattr(bot_dispatcher, "_myjam_allow_router_installed", True)
