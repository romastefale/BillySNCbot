from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Dispatcher
from aiogram.types import TelegramObject

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


def all_features_enabled() -> bool:
    return all(feature_states().values())


def command_feature(command: str | None) -> str | None:
    return _COMMAND_TO_FEATURE.get((command or "").strip().lower())


def command_is_publicly_enabled(command: str) -> bool:
    feature = command_feature(command)
    return True if feature is None else is_feature_enabled(feature)


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
        return "weekfm" if is_feature_enabled("myself") else "myself"
    if data.startswith("myself:m:"):
        return "monthfm" if is_feature_enabled("myself") else "myself"
    return None


def should_drop_update_for_allow_controls(update: Any, *, is_owner: bool) -> bool:
    if is_owner:
        return False
    feature = command_feature(_message_command(update)) or _callback_feature(update)
    return bool(feature and not is_feature_enabled(feature))


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
