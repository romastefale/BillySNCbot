from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_INSTALLED = False


def _external_anchor_pattern() -> re.Pattern[str]:
    return re.compile(
        r'<a\b(?![^>]*\bhref\s*=\s*(["\'])tg://user\?id=\d+\1)[^>]*>(.*?)</a\s*>',
        re.IGNORECASE | re.DOTALL,
    )


def _external_scheme_pattern() -> re.Pattern[str]:
    return re.compile(
        r'(?i)(?<![\w])(?:https?://|mailto:|ftp://|tg://(?!user\?id=\d+))[^\s<>"\']+'
    )


def _external_markdown_autolink_pattern() -> re.Pattern[str]:
    return re.compile(
        r'<(?:https?://|mailto:|ftp://|tg://(?!user\?id=\d+))[^>\s]+>',
        re.IGNORECASE,
    )


def install_internal_user_mention_allowance() -> None:
    """Keep Telegram-local user references while external links stay blocked.

    The group link guard remains authoritative for external destinations. This
    narrow compatibility layer changes only its classification of Telegram
    user mentions:

    - HTML ``tg://user?id=...`` anchors are preserved;
    - plain ``@username`` mentions are preserved;
    - ``mention`` and ``text_mention`` entities no longer trigger sanitizing.

    Generic ``tg://`` links, ``t.me`` links, invite links, websites, e-mail
    addresses and URL buttons remain protected by the original guard.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    from app.bot import group_link_safety as safety

    safety._HTML_ANCHOR_RE = _external_anchor_pattern()
    safety._SCHEME_URL_RE = _external_scheme_pattern()
    safety._MARKDOWN_AUTOLINK_RE = _external_markdown_autolink_pattern()
    safety._PLAIN_MENTION_RE = re.compile(r'(?!x)x')
    safety._CLICKABLE_ENTITY_TYPES.discard('mention')
    safety._CLICKABLE_ENTITY_TYPES.discard('text_mention')

    original_sanitize = safety.sanitize_outbound_method

    def _sanitize_preserving_internal_entities(method: Any) -> Any:
        original_fields: dict[str, Any] = {
            field: getattr(method, field, None)
            for field in safety._ENTITY_FIELDS
        }
        original_texts: dict[str, Any] = {
            field: getattr(method, field, None)
            for field in safety._VISIBLE_TEXT_FIELDS
        }
        sanitized = original_sanitize(method)

        updates: dict[str, Any] = {}
        pairs = (
            ('entities', 'text'),
            ('caption_entities', 'caption'),
            ('question_entities', 'question'),
            ('explanation_entities', 'explanation'),
        )
        for entity_field, text_field in pairs:
            entities = original_fields.get(entity_field)
            if not entities:
                continue
            before = original_texts.get(text_field)
            after = getattr(sanitized, text_field, None)
            if before != after:
                continue
            internal = [
                entity
                for entity in entities
                if safety._entity_type(entity) in {'mention', 'text_mention'}
            ]
            if internal:
                updates[entity_field] = internal

        return safety._copy_model(sanitized, updates)

    safety.sanitize_outbound_method = _sanitize_preserving_internal_entities
    _INSTALLED = True
    logger.info('TELEGRAM_INTERNAL_USER_MENTIONS_ALLOWED')
