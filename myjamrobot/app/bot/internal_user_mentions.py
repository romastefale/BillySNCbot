from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_INSTALLED = False
_INTERNAL_ANCHOR_RE = re.compile(
    r'<a\b[^>]*\bhref\s*=\s*(["\'])tg://user\?id=\d+\1[^>]*>.*?</a\s*>',
    re.IGNORECASE | re.DOTALL,
)


def install_internal_user_mention_allowance() -> None:
    """Protect Telegram-local user anchors while external links are stripped."""
    global _INSTALLED
    if _INSTALLED:
        return

    from app.bot import group_link_safety as safety

    original = safety.strip_clickable_content

    def _strip_preserving_internal(value: str | None, *, fallback: str = "") -> str:
        text = str(value or "")
        protected: dict[str, str] = {}

        def _stash(match: re.Match[str]) -> str:
            token = f"MYJAMINTERNALUSER{len(protected)}TOKEN"
            protected[token] = match.group(0)
            return token

        text = _INTERNAL_ANCHOR_RE.sub(_stash, text)
        cleaned = original(text, fallback=fallback)
        for token, anchor in protected.items():
            cleaned = cleaned.replace(token, anchor)
        return cleaned

    safety.strip_clickable_content = _strip_preserving_internal
    _INSTALLED = True
    logger.info("TELEGRAM_INTERNAL_USER_ANCHORS_PRESERVED")
