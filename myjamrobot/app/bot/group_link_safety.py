from __future__ import annotations

import html
import logging
import re
from typing import Any, Awaitable, Callable, Iterable

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup

logger = logging.getLogger(__name__)

_ORIGINAL_CALL_ATTR = "_myjam_group_link_safety_original_call"
_INSTALLED_ATTR = "_myjam_group_link_safety_installed"

_HTML_ANCHOR_RE = re.compile(
    r'<a\b(?P<attrs>[^>]*)>(?P<label>.*?)</a\s*>', re.IGNORECASE | re.DOTALL
)
_HREF_RE = re.compile(r'href\s*=\s*(["\'])(?P<href>.*?)\1', re.IGNORECASE | re.DOTALL)
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]\n]+)\]\((?:\\.|[^)\n])+\)")
_MARKDOWN_AUTOLINK_RE = re.compile(
    r"<(?:https?://|tg://(?!user\?id=)|mailto:|ftp://)[^>\s]+>", re.IGNORECASE
)
_EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.IGNORECASE)
_SCHEME_URL_RE = re.compile(
    r"(?i)(?<![\w])(?:https?://|tg://(?!user\?id=)|mailto:|ftp://)[^\s<>\"']+"
)
_BARE_DOMAIN_RE = re.compile(
    r"(?i)(?<![@\w])(?:www\.)?"
    r"(?:[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?\.)+"
    r"[a-z]{2,63}(?::\d{2,5})?(?:/[^\s<>\"']*)?"
)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_INTERNAL_USER_LINK_RE = re.compile(r"^tg://user\?id=\d+$", re.IGNORECASE)

_VISIBLE_TEXT_FIELDS = ("text", "caption", "question", "explanation")
_ENTITY_FIELDS = ("entities", "caption_entities", "question_entities", "explanation_entities")
_EXTERNAL_ENTITY_TYPES = {"url", "text_link", "email", "phone_number"}


def _clean_spacing(value: str) -> str:
    value = re.sub(r"[ \t]+([,.;:!?])", r"\1", value)
    value = re.sub(r"[ \t]{2,}", " ", value)
    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n[ \t]+", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _has_visible_text(value: str) -> bool:
    return bool(html.unescape(_HTML_TAG_RE.sub("", value)).strip())


def _anchor_href(attrs: str) -> str:
    match = _HREF_RE.search(attrs or "")
    return html.unescape(match.group("href")).strip() if match else ""


def _is_internal_user_href(href: str) -> bool:
    return bool(_INTERNAL_USER_LINK_RE.fullmatch(href or ""))


def _anchor_is_external(match: re.Match[str]) -> bool:
    return not _is_internal_user_href(_anchor_href(match.group("attrs")))


def _strip_anchor(match: re.Match[str]) -> str:
    if _is_internal_user_href(_anchor_href(match.group("attrs"))):
        return match.group(0)
    return match.group("label")


def _string_contains_clickable(value: str | None) -> bool:
    text = str(value or "")
    if any(_anchor_is_external(match) for match in _HTML_ANCHOR_RE.finditer(text)):
        return True
    return any(
        pattern.search(text) is not None
        for pattern in (
            _MARKDOWN_LINK_RE,
            _MARKDOWN_AUTOLINK_RE,
            _EMAIL_RE,
            _SCHEME_URL_RE,
            _BARE_DOMAIN_RE,
        )
    )


def strip_clickable_content(value: str | None, *, fallback: str = "") -> str:
    """Remove external destinations and preserve Telegram user references."""
    text = str(value or "")
    previous = None
    while previous != text:
        previous = text
        text = _HTML_ANCHOR_RE.sub(_strip_anchor, text)
    text = _MARKDOWN_LINK_RE.sub(r"\1", text)
    text = _MARKDOWN_AUTOLINK_RE.sub("", text)
    text = _EMAIL_RE.sub("", text)
    text = _SCHEME_URL_RE.sub("", text)
    text = _BARE_DOMAIN_RE.sub("", text)
    text = _clean_spacing(text)
    if text and _has_visible_text(text):
        return text
    return fallback


def _button_is_callback_only(button: Any) -> bool:
    return bool(getattr(button, "callback_data", None))


def _keyboard_contains_destination(markup: Any) -> bool:
    if not isinstance(markup, InlineKeyboardMarkup):
        return False
    return any(not _button_is_callback_only(button) for row in markup.inline_keyboard for button in row)


def sanitize_inline_keyboard(markup: Any) -> Any:
    if not isinstance(markup, InlineKeyboardMarkup):
        return markup
    rows = []
    for row in markup.inline_keyboard:
        callbacks = [button for button in row if _button_is_callback_only(button)]
        if callbacks:
            rows.append(callbacks)
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def _copy_model(value: Any, updates: dict[str, Any]) -> Any:
    if not updates:
        return value
    copier = getattr(value, "model_copy", None)
    if callable(copier):
        return copier(update=updates)
    legacy = getattr(value, "copy", None)
    if callable(legacy):
        return legacy(update=updates)
    return value


def _iter_nested(value: Any) -> Iterable[Any]:
    if value is None:
        return ()
    return value if isinstance(value, (list, tuple)) else (value,)


def _entity_type(entity: Any) -> str:
    raw = getattr(entity, "type", "")
    return str(getattr(raw, "value", raw)).lower()


def _entities_contain_external(entities: Any) -> bool:
    return bool(entities) and any(_entity_type(entity) in _EXTERNAL_ENTITY_TYPES for entity in entities)


def _filter_internal_entities(entities: Any) -> Any:
    if not entities:
        return entities
    kept = [entity for entity in entities if _entity_type(entity) not in _EXTERNAL_ENTITY_TYPES]
    return kept or None


def _nested_contains_clickable(value: Any) -> bool:
    for item in _iter_nested(value):
        if _string_contains_clickable(getattr(item, "caption", None)):
            return True
        if _string_contains_clickable(getattr(item, "text", None)):
            return True
        if _entities_contain_external(getattr(item, "caption_entities", None)):
            return True
        if _entities_contain_external(getattr(item, "text_entities", None)):
            return True
    return False


def method_contains_clickable_content(method: Any) -> bool:
    for field in _VISIBLE_TEXT_FIELDS:
        if _string_contains_clickable(getattr(method, field, None)):
            return True
    for field in _ENTITY_FIELDS:
        if _entities_contain_external(getattr(method, field, None)):
            return True
    if _keyboard_contains_destination(getattr(method, "reply_markup", None)):
        return True
    return _nested_contains_clickable(getattr(method, "media", None)) or _nested_contains_clickable(
        getattr(method, "options", None)
    )


def _sanitize_nested_visible_model(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        cleaned = [_sanitize_nested_visible_model(item) for item in value]
        return tuple(cleaned) if isinstance(value, tuple) else cleaned

    updates: dict[str, Any] = {}
    caption = getattr(value, "caption", None)
    if caption is not None:
        cleaned = strip_clickable_content(caption)
        updates["caption"] = cleaned or None
        if hasattr(value, "caption_entities"):
            updates["caption_entities"] = _filter_internal_entities(
                getattr(value, "caption_entities", None)
            )
    text = getattr(value, "text", None)
    if text is not None and not isinstance(value, str):
        updates["text"] = strip_clickable_content(text, fallback="Conteúdo sem link.")
        if hasattr(value, "text_entities"):
            updates["text_entities"] = _filter_internal_entities(getattr(value, "text_entities", None))
    return _copy_model(value, updates)


def sanitize_outbound_method(method: Any) -> Any:
    updates: dict[str, Any] = {}
    for field in _VISIBLE_TEXT_FIELDS:
        value = getattr(method, field, None)
        if value is None:
            continue
        fallback = "" if field == "caption" else "Conteúdo sem link."
        cleaned = strip_clickable_content(value, fallback=fallback)
        updates[field] = (cleaned or None) if field == "caption" else cleaned

    for field in _ENTITY_FIELDS:
        entities = getattr(method, field, None)
        if entities is not None:
            updates[field] = _filter_internal_entities(entities)

    markup = getattr(method, "reply_markup", None)
    if markup is not None:
        updates["reply_markup"] = sanitize_inline_keyboard(markup)
    media = getattr(method, "media", None)
    if media is not None:
        updates["media"] = _sanitize_nested_visible_model(media)
    options = getattr(method, "options", None)
    if options is not None:
        updates["options"] = _sanitize_nested_visible_model(options)
    if hasattr(method, "disable_web_page_preview"):
        updates["disable_web_page_preview"] = True
    return _copy_model(method, updates)


def _private_numeric_chat(chat_id: Any) -> bool:
    try:
        return int(chat_id) > 0
    except (TypeError, ValueError):
        return False


async def protect_outbound_method(bot: Bot, method: Any) -> Any:
    if not method_contains_clickable_content(method):
        return method
    chat_id = getattr(method, "chat_id", None)
    if chat_id is None or _private_numeric_chat(chat_id):
        return method

    from app.bot.group_admin import resolve_bot_is_admin

    if await resolve_bot_is_admin(bot, chat_id, require_fresh=True):
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
    if getattr(Bot, _INSTALLED_ATTR, False):
        return
    original_call: Callable[..., Awaitable[Any]] = Bot.__call__
    setattr(Bot, _ORIGINAL_CALL_ATTR, original_call)
    Bot.__call__ = _guard_bot_call  # type: ignore[method-assign]
    setattr(Bot, _INSTALLED_ATTR, True)
    logger.info("GROUP_NO_ADMIN_LINK_SAFETY_INSTALLED")
