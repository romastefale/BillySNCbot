from __future__ import annotations

import asyncio
from types import SimpleNamespace

from aiogram.enums import ChatMemberStatus
from aiogram.methods import SendMessage
from aiogram.types import MessageEntity

from app.bot.group_link_safety import protect_outbound_method, strip_clickable_content
from app.bot.progressive_music_text import build_progressive_frames


class _FakeBot:
    id = 777

    def __init__(self, status=ChatMemberStatus.MEMBER):
        self.status = status
        self.calls = []

    async def get_chat_member(self, chat_id, user_id):
        self.calls.append((chat_id, user_id))
        return SimpleNamespace(status=self.status)


def test_music_frames_change_only_track_and_artist_line() -> None:
    final = (
        '<b><a href="tg://user?id=123">Maria</a></b>\n'
        '♫ <code>4</code> · <a href="https://open.spotify.com/track/x">Song</a> — <i>Artist</i>\n'
        '♥ <code>2</code>'
    )

    frames = build_progressive_frames(final)

    assert len(frames) >= 2
    assert frames[-1] == final
    for frame in frames[:-1]:
        assert '<a href="tg://user?id=123">Maria</a>' in frame
        assert '♥ <code>2</code>' in frame
    assert 'Song — Artist' not in frames[0]


def test_tly_frames_change_only_blockquote_body() -> None:
    final = (
        '<b><a href="tg://user?id=123">Maria</a></b>\n'
        '♫ <code>4</code> · Song — <i>Artist</i>\n'
        '<blockquote expandable>First line\nSecond line</blockquote>'
    )

    frames = build_progressive_frames(final)

    assert len(frames) >= 2
    assert frames[-1] == final
    for frame in frames:
        assert '<a href="tg://user?id=123">Maria</a>' in frame
        assert '♫ <code>4</code> · Song — <i>Artist</i>' in frame


def test_internal_tg_user_anchor_survives_external_link_removal() -> None:
    source = (
        '<b><a href="tg://user?id=123">Maria</a></b>\n'
        '<a href="https://open.spotify.com/track/x">Song</a> — Artist'
    )

    cleaned = strip_clickable_content(source)

    assert '<a href="tg://user?id=123">Maria</a>' in cleaned
    assert 'https://open.spotify.com' not in cleaned
    assert '>Song<' not in cleaned
    assert 'Song — Artist' in cleaned


def test_plain_username_does_not_trigger_group_sanitizing() -> None:
    bot = _FakeBot()
    method = SendMessage(chat_id=-100123, text='@maria123 ouviu Song')

    protected = asyncio.run(protect_outbound_method(bot, method))

    assert protected is method
    assert protected.text == '@maria123 ouviu Song'
    assert bot.calls == []


def test_text_mention_entity_survives_without_external_destination() -> None:
    bot = _FakeBot()
    method = SendMessage(
        chat_id=-100123,
        text='Maria ouviu Song',
        entities=[
            MessageEntity(
                type='text_mention',
                offset=0,
                length=5,
                user={'id': 123, 'is_bot': False, 'first_name': 'Maria'},
            )
        ],
    )

    protected = asyncio.run(protect_outbound_method(bot, method))

    assert protected is method
    assert protected.entities is not None
    assert protected.entities[0].type == 'text_mention'
    assert bot.calls == []


def test_external_link_still_requires_admin_and_is_removed() -> None:
    bot = _FakeBot(ChatMemberStatus.MEMBER)
    method = SendMessage(
        chat_id=-100123,
        text=(
            '<a href="tg://user?id=123">Maria</a> '
            '<a href="https://example.com">abriu</a>'
        ),
        parse_mode='HTML',
    )

    protected = asyncio.run(protect_outbound_method(bot, method))

    assert '<a href="tg://user?id=123">Maria</a>' in protected.text
    assert 'https://example.com' not in protected.text
    assert 'abriu' in protected.text
    assert bot.calls == [(-100123, 777)]
