from __future__ import annotations

import asyncio
import html
import logging
import re
import secrets
from typing import Any, Awaitable, Callable

from aiogram import Bot
from aiogram.methods import EditMessageCaption, EditMessageText, SendMessageDraft

logger = logging.getLogger(__name__)

_ORIGINAL_CALL_ATTR = "_myjam_progressive_music_original_call"
_INSTALLED_ATTR = "_myjam_progressive_music_installed"

_MUSIC_LINE_RE = re.compile(r"(?m)^(?P<line>[^\n]*♫[^\n]*?\s—\s[^\n]+)$")
_BLOCKQUOTE_RE = re.compile(
    r"(?P<open><blockquote(?:\s+expandable)?>)(?P<body>.*?)(?P<close></blockquote>)",
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")
_MAX_FRAMES = 7
_FRAME_DELAY_SECONDS = 0.16


def _plain_html(value: str) -> str:
    return html.unescape(_TAG_RE.sub("", value))


def _progress_points(length: int, *, max_frames: int = _MAX_FRAMES) -> list[int]:
    if length <= 1:
        return [length]
    count = min(max_frames, length)
    points = {max(1, round(length * index / count)) for index in range(1, count + 1)}
    points.add(length)
    return sorted(points)


def _split_music_line(line_html: str) -> tuple[str, str] | None:
    """Return the static prefix and visible title/artist text.

    Counters and the music glyph remain static. Only the title/artist portion is
    progressively revealed. Formatting is restored exactly in the final frame.
    """
    marker = " · "
    if marker in line_html:
        prefix, dynamic = line_html.split(marker, 1)
        return prefix + marker, _plain_html(dynamic)

    glyph = line_html.find("♫")
    if glyph < 0:
        return None
    after = glyph + 1
    while after < len(line_html) and line_html[after].isspace():
        after += 1
    return line_html[:after], _plain_html(line_html[after:])


def build_progressive_frames(value: str | None) -> list[str]:
    """Build bounded HTML-safe frames for one music line or one lyric quote."""
    final = str(value or "")
    if not final:
        return []

    quote = _BLOCKQUOTE_RE.search(final)
    if quote:
        lyric = _plain_html(quote.group("body")).strip()
        if not lyric:
            return []
        frames: list[str] = []
        for point in _progress_points(len(lyric)):
            partial_quote = f"{quote.group('open')}{html.escape(lyric[:point])}{quote.group('close')}"
            frames.append(final[: quote.start()] + partial_quote + final[quote.end() :])
        if frames[-1] != final:
            frames.append(final)
        return frames

    match = _MUSIC_LINE_RE.search(final)
    if not match:
        return []
    split = _split_music_line(match.group("line"))
    if not split:
        return []
    prefix, dynamic = split
    dynamic = dynamic.strip()
    if not dynamic:
        return []

    frames = []
    for point in _progress_points(len(dynamic)):
        partial_line = prefix + html.escape(dynamic[:point])
        frames.append(final[: match.start("line")] + partial_line + final[match.end("line") :])
    if frames[-1] != final:
        frames.append(final)
    return frames


def _payload_field(method: Any) -> str | None:
    caption = getattr(method, "caption", None)
    if isinstance(caption, str):
        return "caption"
    text = getattr(method, "text", None)
    if isinstance(text, str):
        return "text"
    return None


def _copy_method(method: Any, field: str, value: str) -> Any:
    updates: dict[str, Any] = {field: value}
    entity_field = "caption_entities" if field == "caption" else "entities"
    if hasattr(method, entity_field):
        updates[entity_field] = None
    copier = getattr(method, "model_copy", None)
    if callable(copier):
        return copier(update=updates)
    return method


def _numeric_chat_id(method: Any) -> int | None:
    raw = getattr(method, "chat_id", None)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _is_edit_method(method: Any) -> bool:
    name = str(getattr(method, "__api_method__", ""))
    return name in {"editMessageText", "editMessageCaption"}


async def _stream_private_draft(
    bot: Bot,
    original: Callable[..., Awaitable[Any]],
    *,
    chat_id: int,
    frames: list[str],
    request_timeout: int | None,
) -> None:
    draft_id = secrets.randbelow(2_147_483_646) + 1
    for frame in frames[:-1]:
        try:
            await original(
                bot,
                SendMessageDraft(
                    chat_id=chat_id,
                    draft_id=draft_id,
                    text=_plain_html(frame),
                ),
                request_timeout=request_timeout,
            )
        except Exception:
            logger.debug("PRIVATE_MUSIC_DRAFT_FAILED chat=%s", chat_id, exc_info=True)
            return
        await asyncio.sleep(_FRAME_DELAY_SECONDS)


async def _edit_sent_message(
    bot: Bot,
    original: Callable[..., Awaitable[Any]],
    *,
    sent: Any,
    field: str,
    frames: list[str],
    request_timeout: int | None,
) -> None:
    chat_id = getattr(getattr(sent, "chat", None), "id", None)
    message_id = getattr(sent, "message_id", None)
    if chat_id is None or message_id is None:
        return

    for frame in frames[1:]:
        try:
            if field == "caption":
                edit = EditMessageCaption(
                    chat_id=chat_id,
                    message_id=message_id,
                    caption=frame,
                    parse_mode="HTML",
                )
            else:
                edit = EditMessageText(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=frame,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
            await original(bot, edit, request_timeout=request_timeout)
        except Exception:
            logger.debug(
                "PROGRESSIVE_MUSIC_EDIT_STOPPED chat=%s message=%s",
                chat_id,
                message_id,
                exc_info=True,
            )
            # Best-effort final state. A second failure is intentionally ignored.
            try:
                if frame != frames[-1]:
                    if field == "caption":
                        final_edit = EditMessageCaption(
                            chat_id=chat_id,
                            message_id=message_id,
                            caption=frames[-1],
                            parse_mode="HTML",
                        )
                    else:
                        final_edit = EditMessageText(
                            chat_id=chat_id,
                            message_id=message_id,
                            text=frames[-1],
                            parse_mode="HTML",
                            disable_web_page_preview=True,
                        )
                    await original(bot, final_edit, request_timeout=request_timeout)
            except Exception:
                pass
            return
        await asyncio.sleep(_FRAME_DELAY_SECONDS)


async def _guard_bot_call(self: Bot, method: Any, request_timeout: int | None = None) -> Any:
    original = getattr(Bot, _ORIGINAL_CALL_ATTR)
    field = _payload_field(method)
    if field is None:
        return await original(self, method, request_timeout=request_timeout)

    final_value = getattr(method, field)
    frames = build_progressive_frames(final_value)
    if len(frames) < 2:
        return await original(self, method, request_timeout=request_timeout)

    chat_id = _numeric_chat_id(method)

    # Existing messages, including the second /tly phase, are progressively
    # edited in place in both private chats and groups.
    if _is_edit_method(method):
        initial = _copy_method(method, field, frames[0])
        result = await original(self, initial, request_timeout=request_timeout)
        await _edit_sent_message(
            self,
            original,
            sent=result if hasattr(result, "message_id") else None,
            field=field,
            frames=frames,
            request_timeout=request_timeout,
        )
        # editMessage* may return True for inline messages. Ensure the final
        # method is still dispatched when no Message object was returned.
        if not hasattr(result, "message_id"):
            return await original(self, method, request_timeout=request_timeout)
        return result

    # Native Telegram draft animation is used only for positive private chat
    # IDs. The actual card/message is sent once, complete, after the draft.
    if chat_id is not None and chat_id > 0:
        await _stream_private_draft(
            self,
            original,
            chat_id=chat_id,
            frames=frames,
            request_timeout=request_timeout,
        )
        return await original(self, method, request_timeout=request_timeout)

    # Groups receive one real message/card with a partial target segment, then
    # bounded edits of that same publication. No extra messages are created.
    initial = _copy_method(method, field, frames[0])
    sent = await original(self, initial, request_timeout=request_timeout)
    await _edit_sent_message(
        self,
        original,
        sent=sent,
        field=field,
        frames=frames,
        request_timeout=request_timeout,
    )
    return sent


def install_progressive_music_text() -> None:
    if getattr(Bot, _INSTALLED_ATTR, False):
        return
    original_call: Callable[..., Awaitable[Any]] = Bot.__call__
    setattr(Bot, _ORIGINAL_CALL_ATTR, original_call)
    Bot.__call__ = _guard_bot_call  # type: ignore[method-assign]
    setattr(Bot, _INSTALLED_ATTR, True)
    logger.info("PROGRESSIVE_MUSIC_TEXT_INSTALLED")
