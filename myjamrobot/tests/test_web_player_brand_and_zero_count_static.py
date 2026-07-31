from pathlib import Path


PLAYER = Path("app/web_music/player.html").read_text(encoding="utf-8")


def test_player_uses_myjamrobot_brand_without_old_name():
    assert "myJAMrobot" in PLAYER
    assert ("myJAMrobot" + "bot") not in PLAYER


def test_player_hides_zero_play_count_in_now_line():
    assert 'id="nowLine">Você · ♫</p>' in PLAYER
    assert ('id="plays">' + '0</span>') not in PLAYER
    assert "playsValue>0?" in PLAYER
    assert '<span id="plays">' in PLAYER
