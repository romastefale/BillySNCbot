from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from aiogram.enums import ChatMemberStatus
from aiogram.methods import SendMediaGroup, SendMessage, SendPhoto
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    MessageEntity,
)

from app.bot import group_admin
from app.bot.group_link_safety import (
    method_contains_clickable_content,
    protect_outbound_method,
    sanitize_inline_keyboard,
    strip_clickable_content,
)


class _FakeBot:
    id = 777

    def __init__(self, status: object = ChatMemberStatus.MEMBER, *, error: Exception | None = None) -> None:
        self.status = status
        self.error = error
        self.member_calls: list[tuple[object, int]] = []

    async def get_chat_member(self, chat_id, user_id):
        self.member_calls.append((chat_id, user_id))
        if self.error is not None:
            raise self.error
        return SimpleNamespace(status=self.status)


@pytest.fixture(autouse=True)
def _clear_admin_cache():
    group_admin._admin_cache.clear()
    yield
    group_admin._admin_cache.clear()


def _mixed_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Escolher", callback_data="rfm:token:0"),
                InlineKeyboardButton(text="Abrir Spotify", url="https://open.spotify.com/track/abc"),
            ],
            [InlineKeyboardButton(text="Site", url="https://example.com")],
        ]
    )


def test_strip_clickable_content_preserves_labels_and_formatting() -> None:
    source = (
        '<b><a href="tg://user?id=123">Maria</a></b>\n'
        '<a href="https://open.spotify.com/track/abc">Faixa</a> — <i>Artista</i>\n'
        "Veja [detalhes](https://example.com/a) em t.me/canal ou @canalteste."
    )

    cleaned = strip_clickable_content(source)

    assert "Maria" in cleaned
    assert "Faixa" in cleaned
    assert "Artista" in cleaned
    assert "detalhes" in cleaned
    assert "canalteste" in cleaned
    assert "href=" not in cleaned
    assert "https://" not in cleaned
    assert "tg://" not in cleaned
    assert "t.me" not in cleaned
    assert "@canalteste" not in cleaned


def test_inline_keyboard_keeps_only_callback_buttons() -> None:
    cleaned = sanitize_inline_keyboard(_mixed_keyboard())

    assert cleaned is not None
    assert len(cleaned.inline_keyboard) == 1
    assert len(cleaned.inline_keyboard[0]) == 1
    button = cleaned.inline_keyboard[0][0]
    assert button.callback_data == "rfm:token:0"
    assert button.url is None


def test_radiofm_callback_only_prompt_needs_no_admin_lookup() -> None:
    bot = _FakeBot(error=AssertionError("plain callback output must not query Telegram"))
    method = SendMessage(
        chat_id=-100123,
        text="Escolha a faixa:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Faixa - Artista", callback_data="rfm:abc:0")]
            ]
        ),
    )

    protected = asyncio.run(protect_outbound_method(bot, method))

    assert protected is method
    assert bot.member_calls == []


def test_non_admin_group_message_loses_all_links_but_keeps_callback() -> None:
    bot = _FakeBot(ChatMemberStatus.MEMBER)
    method = SendMessage(
        chat_id=-100123,
        text=(
            '<b><a href="tg://user?id=123">Maria</a></b>\n'
            '<a href="https://open.spotify.com/track/abc">Faixa</a> — Artista'
        ),
        parse_mode="HTML",
        reply_markup=_mixed_keyboard(),
    )

    protected = asyncio.run(protect_outbound_method(bot, method))

    assert protected is not method
    assert "Maria" in protected.text
    assert "Faixa" in protected.text
    assert "href=" not in protected.text
    assert "https://" not in protected.text
    assert "tg://" not in protected.text
    assert protected.reply_markup is not None
    assert protected.reply_markup.inline_keyboard[0][0].callback_data == "rfm:token:0"
    assert bot.member_calls == [(-100123, 777)]


def test_admin_group_keeps_original_links_after_fresh_confirmation() -> None:
    bot = _FakeBot(ChatMemberStatus.ADMINISTRATOR)
    method = SendMessage(
        chat_id=-100123,
        text='<a href="https://example.com">Abrir</a>',
        parse_mode="HTML",
        reply_markup=_mixed_keyboard(),
    )

    protected = asyncio.run(protect_outbound_method(bot, method))

    assert protected is method
    assert "href=" in protected.text
    assert len(protected.reply_markup.inline_keyboard) == 2
    assert bot.member_calls == [(-100123, 777)]


def test_positive_private_chat_is_never_sanitized_or_queried() -> None:
    bot = _FakeBot(error=AssertionError("private output must not query Telegram"))
    method = SendMessage(chat_id=123, text="https://example.com")

    protected = asyncio.run(protect_outbound_method(bot, method))

    assert protected is method
    assert protected.text == "https://example.com"
    assert bot.member_calls == []


def test_admin_lookup_failure_is_fail_closed() -> None:
    bot = _FakeBot(error=RuntimeError("Telegram unavailable"))
    method = SendMessage(chat_id=-100123, text="Ouça em https://example.com agora")

    protected = asyncio.run(protect_outbound_method(bot, method))

    assert "https://" not in protected.text
    assert "Ouça em" in protected.text
    assert bot.member_calls == [(-100123, 777)]
    assert group_admin.bot_is_admin_in(-100123) is False


def test_fresh_confirmation_overrides_stale_positive_cache() -> None:
    group_admin.set_bot_admin_status(-100123, True)
    bot = _FakeBot(ChatMemberStatus.MEMBER)
    method = SendMessage(chat_id=-100123, text="https://example.com")

    protected = asyncio.run(protect_outbound_method(bot, method))

    assert protected.text == "Conteúdo sem link."
    assert bot.member_calls == [(-100123, 777)]
    assert group_admin.bot_is_admin_in(-100123) is False


def test_explicit_text_link_entity_is_detected_and_removed() -> None:
    bot = _FakeBot(ChatMemberStatus.MEMBER)
    method = SendMessage(
        chat_id=-100123,
        text="Faixa",
        entities=[
            MessageEntity(
                type="text_link",
                offset=0,
                length=5,
                url="https://example.com",
            )
        ],
    )

    assert method_contains_clickable_content(method) is True
    protected = asyncio.run(protect_outbound_method(bot, method))

    assert protected.text == "Faixa"
    assert protected.entities is None


def test_photo_caption_is_sanitized_without_removing_photo() -> None:
    bot = _FakeBot(ChatMemberStatus.RESTRICTED)
    method = SendPhoto(
        chat_id=-100123,
        photo="AgAC-file-id",
        caption='<a href="https://example.com">Foto musical</a>',
        parse_mode="HTML",
    )

    protected = asyncio.run(protect_outbound_method(bot, method))

    assert protected.photo == "AgAC-file-id"
    assert protected.caption == "Foto musical"
    assert "href=" not in protected.caption


def test_media_group_captions_are_sanitized() -> None:
    bot = _FakeBot(ChatMemberStatus.MEMBER)
    method = SendMediaGroup(
        chat_id=-100123,
        media=[
            InputMediaPhoto(
                media="AgAC-first",
                caption='<a href="https://example.com">Primeira</a>',
                parse_mode="HTML",
            ),
            InputMediaPhoto(media="AgAC-second", caption="Segunda"),
        ],
    )

    protected = asyncio.run(protect_outbound_method(bot, method))

    assert protected.media[0].media == "AgAC-first"
    assert protected.media[0].caption == "Primeira"
    assert protected.media[1].caption == "Segunda"


def test_unknown_member_status_is_fail_closed() -> None:
    bot = _FakeBot("unexpected-status")
    method = SendMessage(chat_id=-100123, text="t.me/canal")

    protected = asyncio.run(protect_outbound_method(bot, method))

    assert protected.text == "Conteúdo sem link."
    assert group_admin.bot_is_admin_in(-100123) is False
