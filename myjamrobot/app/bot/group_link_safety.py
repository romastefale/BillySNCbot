from __future__ import annotations

import html
import logging
import re
from typing import Any, Awaitable, Callable

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup

logger = logging.getLogger(__name__)

_ORIGINAL_CALL_ATTR = "_myjam_group_link_safety_original_call"
_INSTALLED_ATTR = "_myjam_group_link_safety_installed"

# Telegram renders all of these as clickable destinations. The sanitizer keeps
# human-readable labels but removes the destination itself.
_HTML_ANCHOR_RE = re.compile(r"<a\b[^>]*>(.*?)</a\s*>", re.IGNORECASE | re.DOTALL)
_HTML_ORPHAN_ANCHOR_RE = re.compile(r"</?a\b[^>]*>", re.IGNORECASE | re.DOTALL)
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]\n]+)\]\((?:\\.|[^)\n])+\)")
_MARKDOWN_AUTOLINK_RE = re.compile(
    r"<(?:https?://|tg://|mailto:|ftp://)[^>\s]+>", re.IGNORECASE
)
_EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.IGNORECASE)
_SCHEME_URL_RE = re.compile(
    r"(?i)(?<![\w])(?:https?://|tg://|mailto:|ftp://)[^\s<>\"']+"
)
_BARE_DOMAIN_RE = re.compile(
    r"(?i)(?<![@\w])(?:www\.)?"
    r"(?:[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?\.)+"
    r"[a-z]{2,63}(?::\d{2,5})?(?:/[^\s<>\"']*)?"
)
_PLAIN_MENTION_RE = re.compile(r"(?<![\w/])@([A-Za-z0-9_]{5,32})")
_HTML_TAG_RE = re.compile(r"<[^>]+>")

_VISIBLE_TEXT_FIELDS = (
    "text",
    "caption",
    "question",
    "explanation",
)
_ENTITY_FIELDS = (
    "entities",
    "caption_entities",
    "question_entities",
    "explanation_entities",
)


def _clean_spacing(value: str) -> str:
    value = re.sub(r"[ \t]+([,.;:!?])", r"\1", value)
    value = re.sub(r"[ \t]{2,}", " ", value)
    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n[ \t]+", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _has_visible_text(value: str) -> bool:
    plain = html.unescape(_HTML_TAG_RE.sub("", value)).strip()
    return bool(plain)


def strip_clickable_content(value: str | None, *, fallback: str = "") -> str:
    """Remove destinations while retaining readable labels and formatting.

    The function is deliberately broader than the repository's existing
    per-command regexes: it removes HTML/Markdown links, URL schemes, bare
    domains, e-mail addresses and plain Telegram @mentions. Bot commands such
    as /help remain untouched.
    """
    text = str(value or "")
    previous = None
    while previous != text:
        previous = text
        text = _HTML_ANCHOR_RE.sub(r"\1", text)
    text = _HTML_ORPHAN_ANCHOR_RE.sub("", text)
    text = _MARKDOWN_LINK_RE.sub(r"\1", text)
    text = _MARKDOWN_AUTOLINK_RE.sub("", text)
    text = _EMAIL_RE.sub("", text)
    text = _SCHEME_URL_RE.sub("", text)
    text = _BARE_DOMAIN_RE.sub("", text)
    text = _PLAIN_MENTION_RE.sub(r"\1", text)
    text = _clean_spacing(text)
    if text and _has_visible_text(text):
        return text
    return fallback


def sanitize_inline_keyboard(markup: Any) -> Any:
    """Keep only callback buttons; remove every destination-opening button."""
    if not isinstance(markup, InlineKeyboardMarkup):
        return markup

    rows = []
    for row in markup.inline_keyboard:
        callbacks = [button for button in row if getattr(button, "callback_data", None)]
        if callbacks:
            rows.append(callbacks)
    if not rows:
        return None
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _copy_model(value: Any, updates: dict[str, Any]) -> Any:
    if not updates:
        return value
    model_copy = getattr(value, "model_copy", None)
    if callable(model_copy):
        return model_copy(update=updates)
    legacy_copy = getattr(value, "copy", None)
    if callable(legacy_copy):
        return legacy_copy(update=updates)
    for key, item in updates.items():
        try:
            setattr(value, key, item)
        except Exception:
            logger.debug("GROUP_LINK_SAFETY_FIELD_UPDATE_FAILED field=%s", key, exc_info=True)
    return value


def _sanitize_nested_visible_model(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        sanitized = [_sanitize_nested_visible_model(item) for item in value]
        return type(value)(sanitized) if isinstance(value, tuple) else sanitized

    updates: dict[str, Any] = {}
    caption = getattr(value, "caption", None)
    if caption is not None:
        clean_caption = strip_clickable_content(caption)
        updates["caption"] = clean_caption or None
        if hasattr(value, "caption_entities"):
            updates["caption_entities"] = None

    text = getattr(value, "text", None)
    if text is not None and not isinstance(value, str):
        updates["text"] = strip_clickable_content(text, fallback="Conteúdo sem link.")
        if hasattr(value, "text_entities"):
            updates["text_entities"] = None

    return _copy_model(value, updates)


def sanitize_outbound_method(method: Any) -> Any:
    """Return a copy of an aiogram method with all clickable output removed."""
    updates: dict[str, Any] = {}

    for field in _VISIBLE_TEXT_FIELDS:
        value = getattr(method, field, None)
        if value is None:
            continue
        fallback = "" if field == "caption" else "Conteúdo sem link."
        cleaned = strip_clickable_content(value, fallback=fallback)
        updates[field] = cleaned or None if field == "caption" else cleaned

    # Entity offsets become invalid when URLs are removed. Clearing the entity
    # lists also removes text_link/text_mention destinations while preserving
    # the visible string.
    for field in _ENTITY_FIELDS:
        if getattr(method, field, None) is not None:
            updates[field] = None

    reply_markup = getattr(method, "reply_markup", None)
    if reply_markup is not None:
        updates["reply_markup"] = sanitize_inline_keyboard(reply_markup)

    media = getattr(method, "media", None)
    if media is not None:
        updates["media"] = _sanitize_nested_visible_model(media)

    options = getattr(method, "options", None)
    if options is not None:
        updates["options"] = _sanitize_nested_visible_model(options)

    if hasattr(method, "disable_web_page_preview"):
        updates["disable_web_page_preview"] = True

    return _copy_model(method, updates)


def _has_visible_payload(method: Any) -> bool:
    if any(getattr(method, field, None) is not None for field in _VISIBLE_TEXT_FIELDS):
        return True
    if getattr(method, "reply_markup", None) is not None:
        return True
    media = getattr(method, "media", None)
    if media is not None:
        if isinstance(media, (list, tuple)):
            return any(getattr(item, "caption", None) is not None for item in media)
        return getattr(media, "caption", None) is not None or getattr(method, "reply_markup", None) is not None
    return False


def _private_numeric_chat(chat_id: Any) -> bool:
    try:
        return int(chat_id) > 0
    except (TypeError, ValueError):
        return False


async def protect_outbound_method(bot: Bot, method: Any) -> Any:
    """Sanitize an outbound method only for groups without confirmed admin."""
    if not _has_visible_payload(method):
        return method

    chat_id = getattr(method, "chat_id", None)
    if chat_id is None or _private_numeric_chat(chat_id):
        return method

    from app.bot.group_admin import resolve_bot_is_admin

    if await resolve_bot_is_admin(bot, chat_id):
        return method

    sanitized = sanitize_outbound_method(method)
    logger.info(
        "GROUP_LINK_OUTPUT_SANITIZED method=%s chat_id=%s",
        getattr(method, "__api_method__", type(method).__name__),
        chat_id,
    )
    return sanitized


async def _guard_bot_call(self: Bot, method: Any, request_timeout: int | None = None) -> Any:
    protected = await protect_outbound_method(self, method)
    original = getattr(Bot, _ORIGINAL_CALL_ATTR)
    return await original(self, protected, request_timeout=request_timeout)


def install_group_link_safety() -> None:
    """Install process-wide link protection for outbound group messages."""
    if getattr(Bot, _INSTALLED_ATTR, False):
        return

    original_call: Callable[..., Awaitable[Any]] = Bot.__call__
    setattr(Bot, _ORIGINAL_CALL_ATTR, original_call)
    Bot.__call__ = _guard_bot_call  # type: ignore[method-assign]
    setattr(Bot, _INSTALLED_ATTR, True)
    logger.info("GROUP_NO_ADMIN_LINK_SAFETY_INSTALLED")
