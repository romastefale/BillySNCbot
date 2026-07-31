from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.config.settings import is_code_owner
from app.services.allow_control import (
    CONTROLLED_FEATURES,
    FEATURE_LABELS,
    feature_states,
    is_feature_enabled,
    set_feature_enabled,
)

logger = logging.getLogger(__name__)
router = Router(name="allow")


def _is_private_owner(message: Message | None, user_id: int | None) -> bool:
    return bool(
        message is not None
        and message.chat.type == "private"
        and user_id is not None
        and is_code_owner(user_id)
    )


def _panel_text() -> str:
    return (
        "<b>/allow</b>\n\n"
        "✅ ativo para todos\n"
        "❌ oculto e silencioso para usuários comuns; o owner continua com acesso\n\n"
        "Toque em um recurso para alternar o estado."
    )


def _panel_keyboard() -> InlineKeyboardMarkup:
    states = feature_states()
    rows = []
    for feature in CONTROLLED_FEATURES:
        enabled = states[feature]
        symbol = "✅" if enabled else "❌"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{symbol} /{FEATURE_LABELS[feature]}",
                    callback_data=f"allow:toggle:{feature}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("allow"))
async def allow_command(message: Message) -> None:
    if not _is_private_owner(message, getattr(message.from_user, "id", None)):
        return
    await message.answer(_panel_text(), parse_mode="HTML", reply_markup=_panel_keyboard())


@router.callback_query(F.data.startswith("allow:toggle:"))
async def allow_toggle(query: CallbackQuery) -> None:
    message = query.message if isinstance(query.message, Message) else None
    if not _is_private_owner(message, getattr(query.from_user, "id", None)):
        return

    feature = str(query.data or "").split(":", 2)[-1].strip().lower()
    if feature not in CONTROLLED_FEATURES:
        await query.answer()
        return

    enabled = not is_feature_enabled(feature)
    try:
        set_feature_enabled(feature, enabled, owner_user_id=query.from_user.id)
        from app.bot.setup_commands import setup_bot_commands

        await setup_bot_commands(query.bot)
    except Exception:
        logger.exception("ALLOW_TOGGLE_FAILED owner_id=%s feature=%s", query.from_user.id, feature)
        await query.answer("Não foi possível alterar o estado.", show_alert=True)
        return

    await query.answer(f"/{FEATURE_LABELS[feature]} {'ativado' if enabled else 'desativado'}")
    try:
        await message.edit_text(_panel_text(), parse_mode="HTML", reply_markup=_panel_keyboard())
    except Exception:
        logger.debug("ALLOW_PANEL_EDIT_FAILED owner_id=%s feature=%s", query.from_user.id, feature, exc_info=True)
