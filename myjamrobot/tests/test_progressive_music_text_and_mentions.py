from __future__ import annotations

import importlib

from aiogram.methods import SendMessage
from aiogram.types import MessageEntity

from app.bot import group_link_safety
from app.bot.internal_user_mentions import install_internal_user_mention_allowance
from app.bot.progressive_music_text import build_progressive_frames


def test_music_line_progresses_only_title_and_artist() -> None:
    final = (
        '<b><a href="tg://user?id=7">Maria</a></b>\n'
        '♫ <code>4</code> · <a href="https://open.spotify.com/track/x">Coração Pequeno</a> — <i>Artista</i>\n'
        '♥ <code>2</code>'
    )

    frames = build_progressive_frames(final)

    assert 2 <= len(frames) <= 8
    assert frames[-1] == final
    assert '<b><a href="tg://user?id=7">Maria</a></b>' in frames[0]
    assert '♫ <code>4</code> · ' in frames[0]
    assert '♥ <code>2</code>' in frames[0]
    assert 'Coração Pequeno' not in frames[0]


def test_tly_progresses_only_blockquote() -> None:
    final = (
        '<b><a href="tg://user?id=7">Maria</a></b>\n'
        '♫ Faixa — <i>Artista</i>\n'
        '<blockquote expandable>primeira linha da letra\nsegunda linha</blockquote>'
    )

    frames = build_progressive_frames(final)

    assert 2 <= len(frames) <= 8
    assert frames[-1] == final
    assert '<b><a href="tg://user?id=7">Maria</a></b>' in frames[0]
    assert '♫ Faixa — <i>Artista</i>' in frames[0]
    assert 'segunda linha' not in frames[0]


def test_plain_non_music_message_is_not_animated() -> None:
    assert build_progressive_frames('Instruções normais sem faixa.') == []


def test_internal_user_anchor_is_preserved_while_external_anchor_is_removed() -> None:
    install_internal_user_mention_allowance()
    source = (
        '<b><a href="tg://user?id=7">Maria</a></b>\n'
        '<a href="https://open.spotify.com/track/x">Faixa</a> — Artista'
    )

    cleaned = group_link_safety.strip_clickable_content(source)

    assert 'href="tg://user?id=7"' in cleaned
    assert 'Maria' in cleaned
    assert 'open.spotify.com' not in cleaned
    assert '>Faixa<' not in cleaned or 'Faixa' in cleaned


def test_plain_username_no_longer_triggers_external_link_guard() -> None:
    install_internal_user_mention_allowance()
    method = SendMessage(chat_id=-100, text='Maria @maria123')
    assert group_link_safety.method_contains_clickable_content(method) is False


def test_text_mention_entity_no_longer_triggers_external_link_guard() -> None:
    install_internal_user_mention_allowance()
    method = SendMessage(
        chat_id=-100,
        text='Maria',
        entities=[MessageEntity(type='text_mention', offset=0, length=5, user={'id': 7, 'is_bot': False, 'first_name': 'Maria'})],
    )
    assert group_link_safety.method_contains_clickable_content(method) is False


def test_startup_installs_progressive_and_internal_policies() -> None:
    bot_package = importlib.import_module('app.bot')
    assert bot_package is not None
    from aiogram import Bot

    assert getattr(Bot, '_myjam_progressive_music_installed', False) is True
