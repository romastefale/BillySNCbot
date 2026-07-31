"""Verifica e mantém o status administrativo do próprio bot em grupos.

A segurança de links usa este módulo como fonte de capacidade. Antes de qualquer
saída clicável, o status pode ser confirmado novamente pela API do Telegram.
Falha ou estado desconhecido é tratado como não-admin.
"""
from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot, Router
from aiogram.filters import IS_MEMBER, IS_NOT_MEMBER, ChatMemberUpdatedFilter, Command
from aiogram.types import ChatMemberAdministrator, ChatMemberUpdated, Message

logger = logging.getLogger(__name__)
router = Router(name="group_admin")

# chat_id -> True (administrator/creator) | False (membro comum/restrito).
_admin_cache: dict[int, bool] = {}
_ADMIN_STATUSES = {"administrator", "creator"}
_NON_ADMIN_STATUSES = {"member", "restricted", "left", "kicked", "banned"}


def _numeric_chat_id(chat_id: Any) -> int | None:
    try:
        return int(chat_id)
    except (TypeError, ValueError):
        return None


def set_bot_admin_status(chat_id: Any, is_admin: bool) -> None:
    numeric = _numeric_chat_id(chat_id)
    if numeric is not None:
        _admin_cache[numeric] = bool(is_admin)


def forget_bot_admin_status(chat_id: Any) -> None:
    numeric = _numeric_chat_id(chat_id)
    if numeric is not None:
        _admin_cache.pop(numeric, None)


def bot_is_admin_in(chat_id: Any) -> bool:
    """Return the legacy cached hint used by older command-specific code.

    Unknown remains optimistic here to avoid degrading an administrator group
    before the central guard runs. This helper never authorizes final linked
    output: ``resolve_bot_is_admin(..., require_fresh=True)`` does that.
    """
    numeric = _numeric_chat_id(chat_id)
    if numeric is None:
        return False
    return _admin_cache.get(numeric, True)


def _is_admin(member: Any) -> bool:
    return str(getattr(member, "status", "")) in _ADMIN_STATUSES


async def resolve_bot_is_admin(
    bot: Bot,
    chat_id: Any,
    *,
    require_fresh: bool = False,
) -> bool:
    """Resolve current status and fail closed on every uncertainty.

    ``require_fresh=True`` bypasses both positive and negative cached values.
    The outbound link guard uses this mode before every clickable group output.
    """
    numeric = _numeric_chat_id(chat_id)
    if not require_fresh and numeric is not None and numeric in _admin_cache:
        return _admin_cache[numeric]

    try:
        member = await bot.get_chat_member(chat_id, bot.id)
    except Exception:
        logger.warning(
            "BOT_ADMIN_STATUS_RESOLVE_FAILED chat=%s; links will be suppressed",
            chat_id,
            exc_info=True,
        )
        if numeric is not None:
            _admin_cache[numeric] = False
        return False

    status = str(getattr(member, "status", ""))
    is_admin = status in _ADMIN_STATUSES
    if numeric is not None:
        _admin_cache[numeric] = is_admin
    if status not in _ADMIN_STATUSES | _NON_ADMIN_STATUSES:
        logger.warning(
            "BOT_ADMIN_STATUS_UNKNOWN chat=%s status=%r; links will be suppressed",
            chat_id,
            status,
        )
    return is_admin


@router.my_chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def bot_joined_as_member(event: ChatMemberUpdated) -> None:
    """Record whether the bot entered a group with administrative status."""
    if event.chat.type not in ("group", "supergroup"):
        return

    if _is_admin(event.new_chat_member):
        set_bot_admin_status(event.chat.id, True)
        return

    set_bot_admin_status(event.chat.id, False)
    try:
        await event.bot.send_message(
            event.chat.id,
            "não to valendo nada mesmo 😩🤣",
        )
    except Exception:
        logger.debug(
            "GROUP_ADMIN_JOIN_MSG_FAILED chat=%s", event.chat.id, exc_info=True
        )


@router.my_chat_member()
async def bot_promoted_to_admin(event: ChatMemberUpdated) -> None:
    """Refresh cached status on every membership-status transition."""
    old_status = str(getattr(event.old_chat_member, "status", ""))
    new_status = str(getattr(event.new_chat_member, "status", ""))

    if event.chat.type not in ("group", "supergroup"):
        return

    if new_status in _ADMIN_STATUSES:
        set_bot_admin_status(event.chat.id, True)
    elif new_status in {"member", "restricted"}:
        set_bot_admin_status(event.chat.id, False)
    elif new_status in {"left", "kicked", "banned"}:
        forget_bot_admin_status(event.chat.id)

    if new_status not in _ADMIN_STATUSES or old_status in _ADMIN_STATUSES:
        return

    try:
        await event.bot.send_message(
            event.chat.id,
            "Agora sim, tô valendo! 💪🎶\n/god",
        )
    except Exception:
        logger.debug(
            "GROUP_ADMIN_PROMOTED_MSG_FAILED chat=%s", event.chat.id, exc_info=True
        )


@router.message(Command("god"))
async def god_command(message: Message) -> None:
    """/god: exibe o status de admin e as permissões do bot no grupo atual."""
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("Use /god dentro de um grupo.")
        return

    try:
        member = await message.bot.get_chat_member(message.chat.id, message.bot.id)
    except Exception:
        logger.debug("GOD_GET_CHAT_MEMBER_FAILED chat=%s", message.chat.id, exc_info=True)
        set_bot_admin_status(message.chat.id, False)
        await message.answer("Não consegui verificar minhas permissões aqui.")
        return

    status = str(getattr(member, "status", ""))
    is_admin = status in _ADMIN_STATUSES
    set_bot_admin_status(message.chat.id, is_admin)

    if not is_admin:
        await message.answer("não to valendo nada mesmo 😩🤣")
        return

    adm: ChatMemberAdministrator = member  # type: ignore[assignment]
    perms: list[str] = []

    if getattr(adm, "can_delete_messages", False):
        perms.append("🗑 Apagar mensagens")
    if getattr(adm, "can_restrict_members", False):
        perms.append("🔇 Restringir membros")
    if getattr(adm, "can_pin_messages", False):
        perms.append("📌 Fixar mensagens")
    if getattr(adm, "can_invite_users", False):
        perms.append("🔗 Adicionar membros")
    if getattr(adm, "can_manage_video_chats", False):
        perms.append("🎙 Gerenciar videochamadas")
    if getattr(adm, "can_change_info", False):
        perms.append("✏️ Alterar info do grupo")
    if getattr(adm, "can_promote_members", False):
        perms.append("👑 Promover admins")
    if getattr(adm, "is_anonymous", False):
        perms.append("🕶 Anônimo")

    if perms:
        body = "\n".join(f"• {p}" for p in perms)
        text = f"⚡ <b>God mode ativo</b>\n\n{body}"
    else:
        text = "⚡ <b>Sou admin</b>, mas sem permissões extras configuradas."

    await message.answer(text, parse_mode="HTML")
