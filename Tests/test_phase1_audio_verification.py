"""意図したbass差分だけを許可し、回帰スクリプトの後半も必ず検証する。"""

import io
import json
import zipfile

import numpy as np
import pytest
import soundfile as sf

from bgm.paths import SR
from Tests import verify_phase1_render as verification


def legacy_pair(tmp_path):
    fixture = {"id": "legacy_synth", "master": {"gain_db": -2}, "parts": [
        {"name": "bass", "instrument": "bass", "volume": 0.7, "pan": -0.2},
        {"name": "pad", "instrument": "pad", "volume": 0.3},
        {"name": "lead", "instrument": "square", "pan": 0.4},
        {"name": "drums", "type": "drums"},
    ]}
    old, new = tmp_path / "legacy-before", tmp_path / "legacy-after"
    for i, folder in enumerate((old, new)):
        (folder / "stems").mkdir(parents=True)
        mix = np.zeros((32, 2), np.float32)
        for k, part in enumerate(fixture["parts"]):
            x = np.linspace(-0.4, 0.6, 32, dtype=np.float32)[:, None] * np.ones((1, 2), np.float32) / (k + 1)
            if i and part["name"] == "bass":
                x = x[::-1].copy() * np.float32(0.8)
            sf.write(folder / "stems" / f"{part['name']}.wav", x, SR, subtype="FLOAT")
            pan = part.get("pan", 0)
            angle = (pan + 1) * np.pi / 4
            gains = np.array([np.cos(angle), np.sin(angle)], np.float32) * np.float32(part.get("volume", 0.8))
            mix += x * gains
        target = 10 ** (-1 / 20) * 10 ** (-2 / 20)
        mix *= np.float32(target / np.abs(mix).max())
        # 旧コードは曲フォルダーに、#75 以降は out/ に master を書く。
        (folder / "out").mkdir()
        sf.write((folder / "out" if i else folder) / "legacy_synth.wav", mix, SR, subtype="PCM_16")
    return fixture, old, new


def test_verification_accepts_explained_bass_change_and_finishes_modes(tmp_path, monkeypatch):
    fixture, _, _ = legacy_pair(tmp_path)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w"):
        pass
    monkeypatch.setattr(verification.subprocess, "check_output", lambda cmd, **_: (
        f"SYNTH_SONG = {fixture!r}".encode() if cmd[1] == "show" else archive.getvalue()))
    monkeypatch.setattr(verification.subprocess, "run", lambda *_, **__: None)
    verification.verify(tmp_path, "historical-test-baseline")
    report = json.loads((tmp_path / "verification.json").read_text(encoding="utf-8"))
    assert report["baseline"] == "historical-test-baseline"
    assert report["regression"]["bass"]["intentional_change"]
    assert report["regression"]["mix"]["explained_by_bass_and_normalization"]
    assert all(report["regression"][name]["equal"] for name in ("pad", "lead", "drums"))
    assert all(report["modes"][mode]["force_equal"] for mode in ("major", "minor"))


@pytest.mark.parametrize("damage", ["pad", "lead", "drums", "unchanged_bass", "mix", "sample_rate"])
def test_legacy_comparison_rejects_unexplained_changes(tmp_path, damage):
    fixture, old, new = legacy_pair(tmp_path)
    path = new / "out/legacy_synth.wav" if damage == "mix" else new / "stems" / f"{damage}.wav"
    if damage == "unchanged_bass":
        path = new / "stems/bass.wav"
        path.write_bytes((old / "stems/bass.wav").read_bytes())
    elif damage == "sample_rate":
        path = new / "stems/bass.wav"
        audio = sf.read(path, dtype="float32")[0]
        sf.write(path, audio, SR // 2, subtype="FLOAT")
    else:
        audio = sf.read(path, dtype="float32")[0]
        audio[0] += 0.1
        sf.write(path, audio, SR, subtype="PCM_16" if damage == "mix" else "FLOAT")
    with pytest.raises(AssertionError):
        verification.compare_legacy(old, new, fixture)
