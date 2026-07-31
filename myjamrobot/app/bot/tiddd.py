"""/tiddd — Track ID manual: usuário informa música, álbum, artista e capa
e recebe um card visual no estilo do /playing.

Fluxo FSM (aiogram3 — sem register_next_step_handler):
  1. /tiddd  → limpa estado ativo → TidddFlow.musica  → pede nome da música
  2. texto   → salva → TidddFlow.album   → pede álbum (inline "Pular")
  3. texto / Pular → salva → TidddFlow.artista → pede artista (inline "Pular")
  4. texto / Pular → salva → TidddFlow.capa   → pede capa: foto/vídeo/GIF (inline "Pular")
  5. mídia / Pular → salva → TidddFlow.preview → mostra card com botões Editar/Enviar
  6. "✅ Enviar"  → envia o card publicável e limpa estado
  7. /cancel ou /start enquanto em estado → limpa e avisa

Segurança:
- Rate limit via enforce_message_rate_limit
- Cooldown extra por usuário (3 s)
- Botões inline com prefixo "tiddd:" para não colidir com outros handlers
- FSM MemoryStorage (default do dispatcher): estado é limpo ao enviar ou cancelar
- Nenhuma informação persistida em banco
"""
from __future__ import annotations

import html
import logging
import time

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.bot.group_admin import _admin_cache

logger = logging.getLogger(__name__)
router = Router(name="tiddd")

# ── cooldown leve pra evitar spam de /tiddd ──────────────────────────────────
_TIDDD_COOLDOWN_SECONDS = 3.0
_TIDDD_USER_BOUND = 5000
_tiddd_last_use: dict[int, float] = {}


def _check_cooldown(user_id: int) -> float | None:
    now = time.monotonic()
    last = _tiddd_last_use.get(user_id, 0.0)
    elapsed = now - last
    if elapsed < _TIDDD_COOLDOWN_SECONDS:
        return _TIDDD_COOLDOWN_SECONDS - elapsed
    if len(_tiddd_last_use) >= _TIDDD_USER_BOUND:
        _tiddd_last_use.clear()
    _tiddd_last_use[user_id] = now
    return None


# ── estados FSM ──────────────────────────────────────────────────────────────

class TidddFlow(StatesGroup):
    musica = State()
    album = State()
    artista = State()
    capa = State()
    preview = State()
    publicar = State()   # aguardando decisão/forward pra postar em grupo


# ── teclados inline ──────────────────────────────────────────────────────────

def _kb_skip_album() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭️ Pular", callback_data="tiddd:skip_album")],
    ])


def _kb_skip_artista() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭️ Pular", callback_data="tiddd:skip_artista")],
    ])


def _kb_skip_capa() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭️ Pular", callback_data="tiddd:skip_capa")],
    ])


def _kb_publicar() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Sim, postar no grupo", callback_data="tiddd:postar_sim"),
        InlineKeyboardButton(text="❌ Não", callback_data="tiddd:postar_nao"),
    ]])


def _kb_preview() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Enviar", callback_data="tiddd:confirmar")],
        [
            InlineKeyboardButton(text="🎧 Editar Música", callback_data="tiddd:edit_musica"),
            InlineKeyboardButton(text="🎹 Editar Álbum", callback_data="tiddd:edit_album"),
        ],
        [InlineKeyboardButton(text="🙍 Editar Artista", callback_data="tiddd:edit_artista")],
    ])


# ── helpers de conteúdo ──────────────────────────────────────────────────────

def _build_caption(data: dict, user_name: str, user_id: int) -> str:
    """Monta legenda no estilo /playing: link de menção + linha musical."""
    musica = html.escape(data.get("musica") or "Sem título")
    album_raw = data.get("album") or ""
    artista_raw = data.get("artista") or ""

    from app.bot.telegram import _visible_name

    safe_name = html.escape(_visible_name(user_name) or "Usuário")
    user_link = html.escape(f"tg://user?id={user_id}", quote=True)
    mention = f'<b><a href="{user_link}">{safe_name}</a></b>'

    partes: list[str] = []
    if album_raw:
        partes.append(f"<i>{html.escape(album_raw)}</i>")
    if artista_raw:
        partes.append(f"— <i>{html.escape(artista_raw)}</i>")
    extra = " ".join(partes)

    linha_musical = f"🎧 <b>{musica}</b>"
    if extra:
        linha_musical += f" {extra}"

    return f"{mention} está ouvindo...\n{linha_musical}"


# ── helpers de transição ─────────────────────────────────────────────────────

async def _ask_musica(target: Message, state: FSMContext) -> None:
    await state.set_state(TidddFlow.musica)
    await target.answer("🎧 Qual é o nome da música?")


async def _ask_album(target: Message, state: FSMContext) -> None:
    await state.set_state(TidddFlow.album)
    await target.answer("🖼️ Qual é o álbum? (opcional)", reply_markup=_kb_skip_album())


async def _ask_artista(target: Message, state: FSMContext) -> None:
    await state.set_state(TidddFlow.artista)
    await target.answer("🙍 Quem é o artista? (opcional)", reply_markup=_kb_skip_artista())


async def _ask_capa(target: Message, state: FSMContext) -> None:
    await state.set_state(TidddFlow.capa)
    await target.answer(
        "📸 Envie a capa (foto, vídeo ou GIF) — opcional",
        reply_markup=_kb_skip_capa(),
    )


async def _show_preview(target: Message, state: FSMContext) -> None:
    """Exibe o card de preview com botões Editar/Enviar."""
    await state.set_state(TidddFlow.preview)
    data = await state.get_data()
    user = target.from_user
    from app.bot.telegram import user_display_label

    user_name = user_display_label(user) if user else "Usuário"
    user_id = user.id if user else 0
    caption = _build_caption(data, user_name, user_id)
    capa = data.get("capa")  # (tipo, file_id) ou None

    try:
        if capa:
            tipo, file_id = capa
            if tipo == "photo":
                await target.answer_photo(photo=file_id, caption=caption, parse_mode="HTML",
                                          reply_markup=_kb_preview())
            elif tipo == "video":
                await target.answer_video(video=file_id, caption=caption, parse_mode="HTML",
                                          reply_markup=_kb_preview())
            elif tipo == "animation":
                await target.answer_animation(animation=file_id, caption=caption,
                                              parse_mode="HTML", reply_markup=_kb_preview())
            else:
                await target.answer(caption, parse_mode="HTML", reply_markup=_kb_preview())
        else:
            await target.answer(caption, parse_mode="HTML", reply_markup=_kb_preview())
    except Exception:
        logger.exception("TIDDD_PREVIEW_SEND_FAILED user_id=%s", user_id)
        await target.answer(caption, parse_mode="HTML", reply_markup=_kb_preview())


_HTTP_LINK_RE = __import__("re").compile(r'<a href="https?://[^"]*">([^<]*)</a>')


def _strip_http_links(text: str) -> str:
    """Remove hrefs http(s) de tags <a>, mantendo o texto âncora (mesma lógica de telegram.py)."""
    return _HTTP_LINK_RE.sub(r"\1", text)


async def _bot_can_post(bot, group_id: int) -> tuple[bool, bool]:
    """Verifica se o bot pode enviar mensagens no grupo.

    Retorna (can_post, is_admin).
    Atualiza _admin_cache como efeito colateral para manter consistência com group_admin.py.
    """
    try:
        member = await bot.get_chat_member(group_id, bot.id)
    except Exception:
        # Bot não está no grupo ou grupo inválido
        return False, False

    status = getattr(member, "status", "")

    if status in ("creator", "administrator"):
        _admin_cache[group_id] = True
        return True, True
    elif status == "member":
        _admin_cache[group_id] = False
        return True, False
    elif status == "restricted":
        can_send = bool(getattr(member, "can_send_messages", False))
        _admin_cache[group_id] = False
        return can_send, False
    else:  # left, kicked, banned
        _admin_cache.pop(group_id, None)
        return False, False


async def _send_card_to(bot, chat_id: int, caption: str, capa) -> None:
    """Envia o card (foto/vídeo/animação/texto) para o chat_id indicado.

    Depois de enviar, o bot reage 🔥 no próprio post (mesmo comportamento
    dos cards musicais)."""
    if capa:
        tipo, file_id = capa
        if tipo == "photo":
            sent = await bot.send_photo(chat_id, photo=file_id, caption=caption, parse_mode="HTML")
        elif tipo == "video":
            sent = await bot.send_video(chat_id, video=file_id, caption=caption, parse_mode="HTML")
        elif tipo == "animation":
            sent = await bot.send_animation(chat_id, animation=file_id, caption=caption, parse_mode="HTML")
        else:
            sent = await bot.send_message(chat_id, caption, parse_mode="HTML", disable_web_page_preview=True)
    else:
        sent = await bot.send_message(chat_id, caption, parse_mode="HTML", disable_web_page_preview=True)
    from app.bot.telegram import _react_to_own_card, _CARD_EMOJI_DEFAULT

    await _react_to_own_card(bot, sent.chat.id, sent.message_id, _CARD_EMOJI_DEFAULT)


async def _send_final_card(call: CallbackQuery, state: FSMContext) -> None:
    """Envia o card na DM e salva caption+capa no estado para postar em grupo depois."""
    data = await state.get_data()
    # Não limpa o estado aqui — o fluxo de publicação (publicar state) faz isso.

    user = call.from_user
    from app.bot.telegram import user_display_label

    user_name = user_display_label(user) if user else "Usuário"
    user_id = user.id if user else 0
    caption = _build_caption(data, user_name, user_id)
    capa = data.get("capa")
    chat_id = call.message.chat.id if call.message else (call.from_user.id if call.from_user else 0)

    # Persiste caption/capa no estado para uso eventual na postagem em grupo.
    await state.update_data(caption=caption, capa=capa)

    try:
        await _send_card_to(call.bot, chat_id, caption, capa)
    except Exception:
        logger.exception("TIDDD_FINAL_SEND_FAILED user_id=%s", user_id)


# ── /tiddd ───────────────────────────────────────────────────────────────────

@router.message(Command("tiddd"))
async def tiddd_start(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return

    if message.chat.type != "private":
        await message.answer("🎧 O /tiddd só funciona no privado. Me chama na DM!")
        return

    from app.security.rate_limit import enforce_message_rate_limit
    if not await enforce_message_rate_limit(message, "tiddd"):
        return

    remaining = _check_cooldown(message.from_user.id)
    if remaining is not None:
        await message.answer(f"Aguarda {remaining:.0f}s antes de usar /tiddd novamente.")
        return

    await state.clear()
    await state.update_data(musica=None, album=None, artista=None, capa=None)
    await message.answer("🎶 <b>Bora montar sua TRACK ID</b>", parse_mode="HTML")
    await _ask_musica(message, state)


# ── /cancel e /start cancelam o fluxo ────────────────────────────────────────

@router.message(StateFilter(TidddFlow), Command("cancel"))
async def tiddd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Track ID cancelada. Use /tiddd para começar de novo.")


@router.message(StateFilter(TidddFlow), Command("start"))
async def tiddd_cancel_on_start(message: Message, state: FSMContext) -> None:
    """Limpa o fluxo se o usuário mandar /start enquanto em estado tiddd.

    Em aiogram3, este handler consome o evento — o /start padrão não roda
    em seguida. Por isso, enviamos a mensagem de cancelamento aqui mesmo e
    orientamos o usuário a usar /tiddd para recomeçar.
    """
    await state.clear()
    await message.answer(
        "Track ID cancelada. Use /tiddd para criar uma nova ou /help para ver os comandos."
    )


# ── handlers de texto por estado ─────────────────────────────────────────────

@router.message(TidddFlow.musica, F.text)
async def tiddd_get_musica(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    text = (message.text or "").strip()
    if not text:
        await message.answer("Manda o nome da música em texto.")
        return
    await state.update_data(musica=text)
    await _ask_album(message, state)


@router.message(TidddFlow.album, F.text)
async def tiddd_get_album(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    await state.update_data(album=(message.text or "").strip() or None)
    await _ask_artista(message, state)


@router.message(TidddFlow.artista, F.text)
async def tiddd_get_artista(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    await state.update_data(artista=(message.text or "").strip() or None)
    await _ask_capa(message, state)


@router.message(TidddFlow.capa, F.photo)
async def tiddd_get_capa_photo(message: Message, state: FSMContext) -> None:
    if not message.from_user or not message.photo:
        return
    file_id = message.photo[-1].file_id
    await state.update_data(capa=("photo", file_id))
    await _show_preview(message, state)


@router.message(TidddFlow.capa, F.video)
async def tiddd_get_capa_video(message: Message, state: FSMContext) -> None:
    if not message.from_user or not message.video:
        return
    await state.update_data(capa=("video", message.video.file_id))
    await _show_preview(message, state)


@router.message(TidddFlow.capa, F.animation)
async def tiddd_get_capa_animation(message: Message, state: FSMContext) -> None:
    if not message.from_user or not message.animation:
        return
    await state.update_data(capa=("animation", message.animation.file_id))
    await _show_preview(message, state)


@router.message(TidddFlow.capa)
async def tiddd_capa_invalid(message: Message, state: FSMContext) -> None:
    """Mídia inválida no estado de capa: pede de novo sem quebrar o fluxo."""
    await message.answer(
        "Envie uma foto, vídeo ou GIF — ou use o botão ⏭️ Pular.",
        reply_markup=_kb_skip_capa(),
    )


@router.message(TidddFlow.musica)
async def tiddd_musica_invalid(message: Message, state: FSMContext) -> None:
    await message.answer("Manda o nome da música em texto.")


@router.message(TidddFlow.album)
async def tiddd_album_invalid(message: Message, state: FSMContext) -> None:
    await message.answer("Manda o nome do álbum em texto, ou use o botão ⏭️ Pular.",
                         reply_markup=_kb_skip_album())


@router.message(TidddFlow.artista)
async def tiddd_artista_invalid(message: Message, state: FSMContext) -> None:
    await message.answer("Manda o nome do artista em texto, ou use o botão ⏭️ Pular.",
                         reply_markup=_kb_skip_artista())


# ── callbacks inline ─────────────────────────────────────────────────────────

@router.callback_query(F.data == "tiddd:skip_album")
async def tiddd_cb_skip_album(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.update_data(album=None)
    if call.message:
        await _ask_artista(call.message, state)


@router.callback_query(F.data == "tiddd:skip_artista")
async def tiddd_cb_skip_artista(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.update_data(artista=None)
    if call.message:
        await _ask_capa(call.message, state)


@router.callback_query(F.data == "tiddd:skip_capa")
async def tiddd_cb_skip_capa(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.update_data(capa=None)
    if call.message:
        await _show_preview(call.message, state)


@router.callback_query(F.data == "tiddd:confirmar")
async def tiddd_cb_confirmar(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer("🎉 Enviando...")
    await _send_final_card(call, state)
    await state.set_state(TidddFlow.publicar)
    if call.message:
        await call.message.answer(
            "Card salvo no DM! 🎉\n\nQuer postar em algum grupo também?",
            reply_markup=_kb_publicar(),
        )


@router.callback_query(F.data == "tiddd:postar_nao")
async def tiddd_cb_postar_nao(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.clear()
    if call.message:
        await call.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data == "tiddd:postar_sim")
async def tiddd_cb_postar_sim(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    if call.message:
        await call.message.edit_text(
            "📨 Encaminhe (<b>forward</b>) qualquer mensagem do grupo onde quer postar o card,\n"
            "ou <b>digite o @username ou o ID numérico</b> do grupo.\n\n"
            "Use /cancel para desistir.",
            parse_mode="HTML",
            reply_markup=None,
        )


@router.message(StateFilter(TidddFlow.publicar))
async def tiddd_recv_forward(message: Message, state: FSMContext) -> None:
    """Recebe forward ou @username/ID do grupo-alvo, verifica permissões e posta o card."""
    # /cancel já é capturado pelo handler genérico acima — aqui chegam só msgs normais

    group_id: int | None = None
    group_name: str = "grupo"

    # 1) Mensagem encaminhada com forward_from_chat (grupos sem restrição)
    forward_chat = message.forward_from_chat
    if forward_chat and forward_chat.type in ("group", "supergroup"):
        group_id = forward_chat.id
        group_name = forward_chat.title or "grupo"

    # 2) Texto digitado: @username ou ID numérico (grupos que bloqueiam forward)
    if group_id is None and message.text:
        text = message.text.strip()
        if text.lstrip("-").isdigit():
            # ID numérico (pode ser negativo para grupos)
            group_id = int(text)
        elif text.startswith("@") and len(text) > 1:
            # @username — resolve via API
            try:
                chat = await message.bot.get_chat(text)
                if chat.type not in ("group", "supergroup"):
                    await message.answer(
                        f"<b>{html.escape(text)}</b> não é um grupo. "
                        "Encaminhe uma mensagem do grupo, ou /cancel para sair.",
                        parse_mode="HTML",
                    )
                    return
                group_id = chat.id
                group_name = chat.title or text
            except Exception:
                logger.warning("TIDDD_GET_CHAT_FAILED username=%s", text, exc_info=True)
                await message.answer(
                    f"Não consegui encontrar o grupo <b>{html.escape(text)}</b>. "
                    "Verifique o @username e tente novamente, ou /cancel para sair.",
                    parse_mode="HTML",
                )
                return

    if group_id is None:
        await message.answer(
            "Não consegui identificar o grupo. "
            "Encaminhe uma mensagem do grupo, ou digite o @username ou ID numérico — "
            "ou /cancel para sair."
        )
        return

    safe_group_name = html.escape(group_name)

    # Verifica o que o bot pode fazer nesse grupo antes de tentar enviar
    can_post, is_admin = await _bot_can_post(message.bot, group_id)
    if not can_post:
        await message.answer(
            f"Não tenho permissão pra enviar mensagens em <b>{safe_group_name}</b>.\n"
            "Verifique se o bot está no grupo e com permissão de enviar.",
            parse_mode="HTML",
        )
        return  # Mantém o estado — usuário pode tentar outro grupo

    data = await state.get_data()
    caption: str = data.get("caption", "")
    capa = data.get("capa")

    # Aplica strip de links externos quando não é admin (igual telegram.py / radiofm.py)
    safe_caption = caption if is_admin else _strip_http_links(caption)

    await state.clear()

    try:
        await _send_card_to(message.bot, group_id, safe_caption, capa)
        await message.answer(f"✅ Card postado em <b>{safe_group_name}</b>!", parse_mode="HTML")
    except Exception:
        logger.warning("TIDDD_GROUP_POST_FAILED group_id=%s", group_id, exc_info=True)
        await message.answer(
            f"Não consegui postar em <b>{safe_group_name}</b>. "
            "O bot está presente lá?",
            parse_mode="HTML",
        )


@router.callback_query(F.data == "tiddd:edit_musica")
async def tiddd_cb_edit_musica(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    if call.message:
        await _ask_musica(call.message, state)


@router.callback_query(F.data == "tiddd:edit_album")
async def tiddd_cb_edit_album(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    if call.message:
        await _ask_album(call.message, state)


@router.callback_query(F.data == "tiddd:edit_artista")
async def tiddd_cb_edit_artista(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    if call.message:
        await _ask_artista(call.message, state)
