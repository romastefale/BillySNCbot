"""/hitmo — converte um vídeo enviado pelo usuário em nota de voz OGG (opus).

Fluxo FSM (aiogram3):
  1. /hitmo → limpa estado ativo → HitmoFlow.aguardando_video → instrui a enviar vídeo
  2. Usuário envia vídeo/documento-vídeo/GIF → bot faz download, converte com ffmpeg
     via asyncio.create_subprocess_exec (não-bloqueante), envia como voice note, limpa estado
  3. /cancel ou /start enquanto aguardando → limpa estado e avisa
  4. Mídia inválida enquanto aguardando → avisa e mantém estado aguardando

Segurança:
- Rate limit via enforce_message_rate_limit
- Cooldown extra por usuário (10 s — conversão é cara)
- ffmpeg roda em subprocess assíncrono: evento loop não bloqueia
- Arquivos temporários criados em tempfile.TemporaryDirectory e apagados automaticamente
- Nenhum dado salvo permanentemente
"""
from __future__ import annotations

import asyncio
import logging
import tempfile
import time
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, Message

logger = logging.getLogger(__name__)
router = Router(name="hitmo")

_HITMO_COOLDOWN_SECONDS = 10.0   # conversão ffmpeg é pesada
_HITMO_USER_BOUND = 2000
_hitmo_last_use: dict[int, float] = {}

# Limite de tamanho do arquivo de entrada (20 MB — limite Telegram Bot API download)
_HITMO_MAX_FILE_BYTES = 20 * 1024 * 1024

_FFMPEG_TIMEOUT_SECONDS = 60.0


def _check_cooldown(user_id: int) -> float | None:
    now = time.monotonic()
    last = _hitmo_last_use.get(user_id, 0.0)
    elapsed = now - last
    if elapsed < _HITMO_COOLDOWN_SECONDS:
        return _HITMO_COOLDOWN_SECONDS - elapsed
    if len(_hitmo_last_use) >= _HITMO_USER_BOUND:
        _hitmo_last_use.clear()
    _hitmo_last_use[user_id] = now
    return None


class HitmoFlow(StatesGroup):
    aguardando_video = State()


# ── /hitmo ───────────────────────────────────────────────────────────────────

@router.message(Command("hitmo"))
async def hitmo_start(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return

    if message.chat.type != "private":
        await message.answer("🎙 O /hitmo só funciona no privado. Me chama na DM!")
        return

    from app.security.rate_limit import enforce_message_rate_limit
    if not await enforce_message_rate_limit(message, "hitmo"):
        return

    remaining = _check_cooldown(message.from_user.id)
    if remaining is not None:
        await message.answer(f"Aguarda {remaining:.0f}s antes de usar /hitmo novamente.")
        return

    await state.clear()
    await state.set_state(HitmoFlow.aguardando_video)
    await message.answer(
        "🎙 <b>Envie um vídeo</b>\n"
        "Vou transformar em áudio de voz.\n\n"
        "Use /cancel para desistir.",
        parse_mode="HTML",
    )


# ── /cancel e /start cancelam o fluxo ────────────────────────────────────────

@router.message(StateFilter(HitmoFlow), Command("cancel"))
async def hitmo_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Conversão cancelada. Use /hitmo para tentar de novo.")


@router.message(StateFilter(HitmoFlow), Command("start"))
async def hitmo_cancel_on_start(message: Message, state: FSMContext) -> None:
    """Limpa o estado se o usuário mandar /start enquanto aguardando vídeo.

    Em aiogram3, este handler consome o evento — o /start padrão não roda
    em seguida. Por isso, enviamos aviso de cancelamento aqui mesmo.
    """
    await state.clear()
    await message.answer(
        "Conversão cancelada. Use /hitmo para tentar de novo ou /help para ver os comandos."
    )


# ── conversão ────────────────────────────────────────────────────────────────

async def _convert_to_voice(input_bytes: bytes) -> bytes | None:
    """Converte bytes de vídeo em OGG/opus mono 48k via ffmpeg assíncrono.

    Retorna bytes do OGG ou None se a conversão falhar.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        input_path = tmp / "input_video"
        output_path = tmp / "voice_note.ogg"
        input_path.write_bytes(input_bytes)

        cmd = [
            "ffmpeg",
            "-y",
            "-i", str(input_path),
            "-vn",           # sem vídeo
            "-ac", "1",      # mono
            "-c:a", "libopus",
            "-b:a", "48k",
            "-f", "ogg",
            str(output_path),
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=_FFMPEG_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            logger.warning("HITMO_FFMPEG_TIMEOUT")
            try:
                proc.kill()
            except Exception:
                pass
            return None
        except FileNotFoundError:
            logger.error("HITMO_FFMPEG_NOT_FOUND — ffmpeg não está instalado ou não está no PATH")
            return None
        except Exception:
            logger.exception("HITMO_FFMPEG_SUBPROCESS_ERROR")
            return None

        if proc.returncode != 0 or not output_path.exists():
            logger.warning(
                "HITMO_FFMPEG_FAILED returncode=%s stderr=%s",
                proc.returncode,
                (stderr or b"").decode(errors="replace")[:500],
            )
            return None

        return output_path.read_bytes()


async def _handle_video_convert(message: Message, state: FSMContext, file_id: str, file_size: int | None) -> None:
    """Baixa o arquivo, converte e envia a nota de voz. Limpa estado ao final."""
    if not message.from_user:
        return

    # Checa tamanho antes de baixar
    if file_size and file_size > _HITMO_MAX_FILE_BYTES:
        await message.answer(
            f"❌ Arquivo muito grande ({file_size // (1024 * 1024)} MB). "
            "O limite é 20 MB."
        )
        await state.clear()
        return

    await state.clear()

    try:
        await message.bot.send_chat_action(message.chat.id, "record_voice")
    except Exception:
        pass

    try:
        file_info = await message.bot.get_file(file_id)
        input_bytes = await message.bot.download_file(file_info.file_path)
        if hasattr(input_bytes, "read"):
            input_bytes = input_bytes.read()
    except Exception:
        logger.exception("HITMO_DOWNLOAD_FAILED file_id=%s", file_id)
        await message.answer("❌ Não consegui baixar o vídeo. Tente de novo.")
        return

    ogg_bytes = await _convert_to_voice(input_bytes)
    if ogg_bytes is None:
        await message.answer("❌ Não consegui converter o vídeo. Verifique se é um vídeo válido.")
        return

    try:
        voice_file = BufferedInputFile(ogg_bytes, filename="voice_note.ogg")
        await message.answer_voice(voice=voice_file)
    except Exception:
        logger.exception("HITMO_SEND_VOICE_FAILED user_id=%s", message.from_user.id)
        await message.answer("❌ Erro ao enviar o áudio.")


# ── handlers de mídia no estado aguardando_video ─────────────────────────────

@router.message(HitmoFlow.aguardando_video, F.video)
async def hitmo_recv_video(message: Message, state: FSMContext) -> None:
    if not message.video:
        return
    await _handle_video_convert(
        message, state,
        file_id=message.video.file_id,
        file_size=message.video.file_size,
    )


@router.message(HitmoFlow.aguardando_video, F.document)
async def hitmo_recv_document(message: Message, state: FSMContext) -> None:
    """Aceita vídeo enviado como arquivo (documento)."""
    doc = message.document
    if not doc:
        return
    mime = doc.mime_type or ""
    if not mime.startswith("video/"):
        await message.answer(
            "❌ Esse arquivo não parece ser um vídeo. "
            "Envie um vídeo válido ou use /cancel para desistir."
        )
        return
    await _handle_video_convert(
        message, state,
        file_id=doc.file_id,
        file_size=doc.file_size,
    )


@router.message(HitmoFlow.aguardando_video, F.animation)
async def hitmo_recv_animation(message: Message, state: FSMContext) -> None:
    """Aceita GIFs/animações (video sem áudio — resultado será silencioso)."""
    if not message.animation:
        return
    await _handle_video_convert(
        message, state,
        file_id=message.animation.file_id,
        file_size=message.animation.file_size,
    )


@router.message(HitmoFlow.aguardando_video)
async def hitmo_invalid_media(message: Message, state: FSMContext) -> None:
    """Qualquer outra coisa enquanto aguardando vídeo → avisa e mantém estado."""
    await message.answer(
        "Envie um vídeo para converter, ou use /cancel para desistir."
    )
