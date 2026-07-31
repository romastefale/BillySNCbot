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

    safe_name = html.escape(user_name or "Usuário")
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
    user_name = (user.full_name or "Usuário") if user else "Usuário"
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


async def _send_final_card(call: CallbackQuery, state: FSMContext) -> None:
    """Envia o card publicável e limpa o estado."""
    data = await state.get_data()
    await state.clear()

    user = call.from_user
    user_name = (user.full_name or "Usuário") if user else "Usuário"
    user_id = user.id if user else 0
    caption = _build_caption(data, user_name, user_id)
    capa = data.get("capa")
    chat_id = call.message.chat.id if call.message else (call.from_user.id if call.from_user else 0)

    try:
        if capa:
            tipo, file_id = capa
            if tipo == "photo":
                await call.bot.send_photo(chat_id, photo=file_id, caption=caption, parse_mode="HTML")
            elif tipo == "video":
                await call.bot.send_video(chat_id, video=file_id, caption=caption, parse_mode="HTML")
            elif tipo == "animation":
                await call.bot.send_animation(chat_id, animation=file_id, caption=caption,
                                              parse_mode="HTML")
            else:
                await call.bot.send_message(chat_id, caption, parse_mode="HTML",
                                            disable_web_page_preview=True)
        else:
            await call.bot.send_message(chat_id, caption, parse_mode="HTML",
                                        disable_web_page_preview=True)
    except Exception:
        logger.exception("TIDDD_FINAL_SEND_FAILED user_id=%s", user_id)


# ── /tiddd ───────────────────────────────────────────────────────────────────

@router.message(Command("tiddd"))
async def tiddd_start(message: Message, state: FSMContext) -> None:
    if not message.from_user:
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
