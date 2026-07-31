"""Verifica status de admin do bot ao entrar em grupos.

Comportamento:
- Bot entra sem admin → manda a frase de lamento uma única vez e fica quieto.
- Bot é promovido a admin → anuncia que agora está operacional.

Handler de my_chat_member (aiogram3): dispara somente quando o STATUS DO
PRÓPRIO BOT muda num chat. Nunca confundir com chat_member (status de outros
membros).

Não usa banco: a mensagem é enviada uma única vez no evento — sem registro
persistente de "já avisou". Se o bot for removido e readicionado, avisa de novo.
"""
from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import IS_MEMBER, IS_NOT_MEMBER, ChatMemberUpdatedFilter
from aiogram.types import ChatMemberUpdated

logger = logging.getLogger(__name__)
router = Router(name="group_admin")

# Statuses que indicam presença sem privilégio de admin
_NON_ADMIN_STATUSES = {"member", "restricted"}
# Statuses que indicam ausência
_ABSENT_STATUSES = {"left", "kicked", "banned"}


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
            "Agora sim, tô valendo! 💪🎶",
        )
    except Exception:
        logger.debug(
            "GROUP_ADMIN_PROMOTED_MSG_FAILED chat=%s", event.chat.id, exc_info=True
        )
