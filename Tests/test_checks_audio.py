"""音のチェック（bgm/checks/audio.py）。#75 では check_loop を移した seam_click / seam_level。"""

import numpy as np
import pytest

from bgm import render
from bgm.checks import CheckContext, Issue, audio_check, registered, run_checks
from bgm.paths import SR
from bgm.profiles import PROFILES
from bgm.report import build_report, measure


def sine(seconds=2.0, freq=220.0, amp=0.5):
    t = np.arange(int(seconds * SR)) / SR
    x = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return np.stack([x, x], axis=1)


def context(master, *, loop=True, bars=4):
    song = {"id": "seam", "usage": "video", "loop": loop, "bars": bars}
    return CheckContext(song=song, profile=PROFILES["video"], notes={}, stems={}, master=master, sr=SR)


def seamless():
    # 220 Hz は 2 秒でちょうど 440 周期なので、終わりから始まりへ滑らかにつながる。
    return sine()


def test_registered_order_is_fixed():
    assert registered()[:2] == ["seam_click", "seam_level"]


def test_seamless_loop_has_no_issues():
    ctx = context(seamless())
    assert run_checks(ctx) == []
    report = build_report(ctx.song, measure(ctx.master, ctx.song), run_checks(ctx))
    assert report["passed"] is True and report["issues"] == []


def test_jump_at_seam_is_a_seam_click_error_in_the_report():
    master = seamless()
    master[-200:] = 0.9  # 終わりを高い値で止め、始まり（0）へ跳ばせる
    ctx = context(master)
    issues = run_checks(ctx)
    assert [i.check for i in issues] == ["seam_click"]
    report = build_report(ctx.song, measure(master, ctx.song), issues)
    assert report["passed"] is False
    (issue,) = report["issues"]
    assert issue["level"] == "error" and issue["part"] is None and issue["bars"] == [1, 4]
    assert "つなぎ目で波形が跳んでいます" in issue["message"] and issue["hint"]


def test_level_step_at_seam_is_a_seam_level_warning():
    master = seamless()
    master[-int(0.25 * SR):] *= np.float32(0.05)  # 終わりを約 26 dB 下げる（境目は 0 付近で切る）
    issues = run_checks(context(master))
    assert [(i.check, i.level) for i in issues] == [("seam_level", "warning")]
    assert "dB" in issues[0].message


@pytest.mark.parametrize("ctx", [context(np.zeros((SR // 2, 2), np.float32)), context(sine() * 0 + 0.9, loop=False)])
def test_seam_checks_skip_short_or_one_shot_songs(ctx):
    assert run_checks(ctx) == []


def test_check_loop_wrapper_keeps_messages():
    ok, message = render.check_loop(seamless())
    assert ok and message.startswith("つなぎ目 OK")
    master = seamless()
    master[-200:] = 0.9
    ok, message = render.check_loop(master)
    assert not ok and "跳んで" in message


def test_duplicate_check_id_is_rejected():
    with pytest.raises(ValueError):
        audio_check("seam_click")(lambda ctx: [])


def test_unknown_level_is_rejected(monkeypatch):
    from bgm import checks

    monkeypatch.setattr(checks, "_AUDIO_CHECKS", [("bad", lambda ctx: [Issue("info", "bad", None, (), "x", None)])])
    with pytest.raises(ValueError):
        run_checks(context(seamless()))
