import math

import numpy as np
import pytest

from bgm.loudness import _biquads, integrated_lufs, k_weight, sample_peak_db


def sine(db, seconds=20.0, freq=1000.0, sr=44100, channels=2):
    t = np.arange(int(seconds * sr)) / sr
    mono = 10 ** (db / 20) * np.sin(2 * np.pi * freq * t)
    return np.repeat(mono[:, None], channels, axis=1)


def test_ebu_tech_3341_case_1_stereo_sine_at_minus_23_dbfs():
    assert integrated_lufs(sine(-23.0)) == pytest.approx(-23.0, abs=0.1)


def test_ebu_tech_3341_case_2_stereo_sine_at_minus_33_dbfs():
    assert integrated_lufs(sine(-33.0)) == pytest.approx(-33.0, abs=0.1)


def test_48k_coefficients_match_bs1770():
    shelf, highpass = _biquads(48000)
    assert np.allclose(shelf[0], [1.53512485958697, -2.69169618940638, 1.19839281085285], atol=1e-8)
    assert np.allclose(shelf[1], [1.0, -1.69065929318241, 0.73248077421585], atol=1e-8)
    assert np.allclose(highpass[1], [1.0, -1.99004745483398, 0.99007225036621], atol=1e-8)


def test_48k_sine_and_mono_input():
    assert integrated_lufs(sine(-23.0, sr=48000), sr=48000) == pytest.approx(-23.0, abs=0.1)
    # モノラルは1チャンネル分なのでステレオより約3dB小さい。
    assert integrated_lufs(sine(-23.0, channels=1)[:, 0]) == pytest.approx(-26.0, abs=0.1)


def test_silence_and_short_input_are_not_measurable():
    assert integrated_lufs(np.zeros((44100 * 5, 2))) == float("-inf")
    assert integrated_lufs(sine(-23.0, seconds=0.3)) == float("-inf")
    assert integrated_lufs(np.zeros((0, 2))) == float("-inf")


def test_short_input_just_over_one_block_is_measured_without_wraparound():
    # 0.5秒の信号でも巡回畳み込みにならず、長い信号と同じ値になる。
    assert integrated_lufs(sine(-23.0, seconds=0.5)) == pytest.approx(-23.0, abs=0.1)


def test_k_weight_has_no_circular_wraparound():
    x = np.zeros(44100)
    x[-1] = 1.0  # 最後の1サンプルの余韻が先頭に回り込まない
    y = k_weight(x)
    assert np.abs(y[:-1]).max() < 1e-12


def test_quiet_part_is_removed_by_relative_gate():
    loud, quiet = sine(-20.0, seconds=10), sine(-50.0, seconds=10)
    assert integrated_lufs(np.concatenate([loud, quiet])) == pytest.approx(-20.0, abs=0.1)


def test_sample_peak_db():
    assert sample_peak_db(np.array([[0.5, -0.25], [0.0, 0.1]])) == pytest.approx(20 * math.log10(0.5))
    assert sample_peak_db(np.zeros((10, 2))) == float("-inf")
    assert sample_peak_db(np.zeros((0, 2))) == float("-inf")
