from __future__ import annotations

import logging
from typing import Any

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
        "Toque em um recurso para alternar o estado. "
        "Use o botão de sincronização para republicar e conferir a lista privada."
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
    rows.append(
        [
            InlineKeyboardButton(
                text="↻ Sincronizar lista privada",
                callback_data="allow:sync",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _sync_private_command_menu(bot: Any) -> None:
    from app.bot.setup_commands import setup_bot_commands

    await setup_bot_commands(bot, raise_on_error=True)


async def _toggle_feature_with_verified_menu(
    bot: Any,
    *,
    feature: str,
    owner_user_id: int,
) -> bool:
    """Persist a feature toggle only when Telegram confirms the new menu.

    If publication or readback fails, the previous feature state is restored and
    the previous command menu is republished best-effort. The caller receives the
    original synchronization error and must not report success.
    """
    previous_enabled = is_feature_enabled(feature)
    enabled = not previous_enabled
    set_feature_enabled(feature, enabled, owner_user_id=owner_user_id)

    try:
        await _sync_private_command_menu(bot)
    except Exception:
        logger.exception(
            "ALLOW_MENU_SYNC_FAILED_ROLLING_BACK owner_id=%s feature=%s target=%s",
            owner_user_id,
            feature,
            enabled,
        )
        try:
            set_feature_enabled(feature, previous_enabled, owner_user_id=owner_user_id)
        except Exception:
            logger.critical(
                "ALLOW_STATE_ROLLBACK_FAILED owner_id=%s feature=%s previous=%s",
                owner_user_id,
                feature,
                previous_enabled,
                exc_info=True,
            )
        else:
            try:
                await _sync_private_command_menu(bot)
            except Exception:
                logger.critical(
                    "ALLOW_MENU_ROLLBACK_SYNC_FAILED owner_id=%s feature=%s previous=%s",
                    owner_user_id,
                    feature,
                    previous_enabled,
                    exc_info=True,
                )
        raise

    return enabled


@router.message(Command("allow"))
async def allow_command(message: Message) -> None:
    if not _is_private_owner(message, getattr(message.from_user, "id", None)):
        return
    await message.answer(_panel_text(), parse_mode="HTML", reply_markup=_panel_keyboard())


@router.callback_query(F.data == "allow:sync")
async def allow_sync(query: CallbackQuery) -> None:
    message = query.message if isinstance(query.message, Message) else None
    if not _is_private_owner(message, getattr(query.from_user, "id", None)):
        return

    try:
        await _sync_private_command_menu(query.bot)
    except Exception:
        logger.exception("ALLOW_EXPLICIT_MENU_SYNC_FAILED owner_id=%s", query.from_user.id)
        await query.answer(
            "O Telegram não confirmou a atualização da lista privada.",
            show_alert=True,
        )
        return

    await query.answer("Lista privada sincronizada e conferida.", show_alert=True)


@router.callback_query(F.data.startswith("allow:toggle:"))
async def allow_toggle(query: CallbackQuery) -> None:
    message = query.message if isinstance(query.message, Message) else None
    if not _is_private_owner(message, getattr(query.from_user, "id", None)):
        return

    feature = str(query.data or "").split(":", 2)[-1].strip().lower()
    if feature not in CONTROLLED_FEATURES:
        await query.answer()
        return

    try:
        enabled = await _toggle_feature_with_verified_menu(
            query.bot,
            feature=feature,
            owner_user_id=query.from_user.id,
        )
    except Exception:
        logger.exception("ALLOW_TOGGLE_FAILED owner_id=%s feature=%s", query.from_user.id, feature)
        await query.answer(
            "A lista privada não foi confirmada pelo Telegram. O estado anterior foi restaurado.",
            show_alert=True,
        )
        try:
            await message.edit_text(_panel_text(), parse_mode="HTML", reply_markup=_panel_keyboard())
        except Exception:
            logger.debug(
                "ALLOW_PANEL_ROLLBACK_EDIT_FAILED owner_id=%s feature=%s",
                query.from_user.id,
                feature,
                exc_info=True,
            )
        return

    await query.answer(
        f"/{FEATURE_LABELS[feature]} {'ativado' if enabled else 'desativado'} e lista conferida"
    )
    try:
        await message.edit_text(_panel_text(), parse_mode="HTML", reply_markup=_panel_keyboard())
    except Exception:
        logger.debug("ALLOW_PANEL_EDIT_FAILED owner_id=%s feature=%s", query.from_user.id, feature, exc_info=True)
