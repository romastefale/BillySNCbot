from __future__ import annotations

from app.bot.progressive_music_text import build_progressive_frames


def test_music_line_progresses_only_title_and_artist() -> None:
    final = (
        '<b><a href="tg://user?id=123">Maria</a></b>\n'
        '♫ <code>12</code> · <a href="https://open.spotify.com/track/x">Nome da música</a> — '
        '<i>Artista</i>\n'
        '♥ <code>4</code>'
    )

    frames = build_progressive_frames(final)

    assert 2 <= len(frames) <= 8
    assert frames[-1] == final
    for frame in frames[:-1]:
        assert '<a href="tg://user?id=123">Maria</a>' in frame
        assert '♫ <code>12</code> · ' in frame
        assert '♥ <code>4</code>' in frame
    assert "Nome da música — Artista" not in frames[0]


def test_tly_quote_progresses_only_lyric_body() -> None:
    final = (
        '<b><a href="tg://user?id=123">Maria</a></b>\n'
        '♫ <code>2</code> · Música — <i>Artista</i>\n'
        '<blockquote expandable>Primeira linha da letra\nSegunda linha</blockquote>'
    )

    frames = build_progressive_frames(final)

    assert 2 <= len(frames) <= 8
    assert frames[-1] == final
    for frame in frames[:-1]:
        assert '<a href="tg://user?id=123">Maria</a>' in frame
        assert '♫ <code>2</code> · Música — <i>Artista</i>' in frame
        assert '<blockquote expandable>' in frame
    assert "Segunda linha" not in frames[0]


def test_non_music_text_is_not_animated() -> None:
    assert build_progressive_frames("Use /help para ver os comandos.") == []


def test_statistics_without_track_line_are_not_animated() -> None:
    assert build_progressive_frames("♫ 12 reproduções\n♥ 4 curtidas") == []


def test_short_music_line_still_finishes_exactly() -> None:
    final = "♫ A — B"
    frames = build_progressive_frames(final)
    assert frames[-1] == final
    assert len(frames) >= 2
