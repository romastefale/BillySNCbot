"""Verifica status de admin do bot ao entrar em grupos.

Comportamento:
- Bot entra sem admin → manda a frase de lamento uma única vez e fica quieto.
- Bot é promovido a admin → anuncia com referência ao /god.
- /god → mostra as permissões atuais do bot no grupo (só funciona em grupo).

Handler de my_chat_member (aiogram3): dispara somente quando o STATUS DO
PRÓPRIO BOT muda num chat. Nunca confundir com chat_member (status de outros
membros).

Não usa banco: a mensagem é enviada uma única vez no evento — sem registro
persistente de "já avisou". Se o bot for removido e readicionado, avisa de novo.
"""
from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import IS_MEMBER, IS_NOT_MEMBER, ChatMemberUpdatedFilter, Command
from aiogram.types import ChatMemberAdministrator, ChatMemberUpdated, Message

logger = logging.getLogger(__name__)
router = Router(name="group_admin")


def _is_admin(member) -> bool:
    return getattr(member, "status", "") == "administrator"


# ── bot entra no grupo SEM ser admin ─────────────────────────────────────────

@router.my_chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def bot_joined_as_member(event: ChatMemberUpdated) -> None:
    """Dispara quando o bot é adicionado ao grupo como membro comum (não admin)."""
    if _is_admin(event.new_chat_member):
        # Foi adicionado já como admin — não reclamar
        return
    if event.chat.type not in ("group", "supergroup"):
        return
    try:
        await event.bot.send_message(
            event.chat.id,
            "não to valendo nada mesmo 😩🤣",
        )
    except Exception:
        logger.debug(
            "GROUP_ADMIN_JOIN_MSG_FAILED chat=%s", event.chat.id, exc_info=True
        )


# ── bot é promovido a admin ───────────────────────────────────────────────────

@router.my_chat_member()
async def bot_promoted_to_admin(event: ChatMemberUpdated) -> None:
    """Dispara quando o status do bot muda para administrator."""
    old_status = getattr(event.old_chat_member, "status", "")
    new_status = getattr(event.new_chat_member, "status", "")

    # Só interessa a promoção de não-admin → admin
    if new_status != "administrator":
        return
    if old_status == "administrator":
        return  # já era admin, não anunciar de novo
    if event.chat.type not in ("group", "supergroup"):
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


# ── /god — mostra permissões atuais do bot no grupo ──────────────────────────

@router.message(Command("god"))
async def god_command(message: Message) -> None:
    """/god: exibe o status de admin e as permissões do bot no grupo atual."""
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("Use /god dentro de um grupo.")
        return

    bot_id = message.bot.id
    try:
        member = await message.bot.get_chat_member(message.chat.id, bot_id)
    except Exception:
        logger.debug("GOD_GET_CHAT_MEMBER_FAILED chat=%s", message.chat.id, exc_info=True)
        await message.answer("Não consegui verificar minhas permissões aqui.")
        return

    status = getattr(member, "status", "")

    if status != "administrator":
        await message.answer("não to valendo nada mesmo 😩🤣")
        return

    # É admin — lista o que pode fazer
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
