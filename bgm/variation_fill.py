"""全曲通算の節目を固定フィルに置換する、描画未統合の純粋API。"""

import math
from collections.abc import Mapping

from .rhythm import compile_rhythm

_SYNTH_VOICES = frozenset(("kick", "snare", "hat", "open_hat", "clap", "rim", "noise_hit"))
_METERS = {"4/4": 4, "3/4": 3, "6/8": 3}


def _finite(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def compile_fill(part, song, occurrences, source_events, *, every, available_voices=None):
    """既存3タプル、元入力index（新規はNone）、適用小節番号を返す。

    events/origins/fill_barsは独立した新しいリスト。変更時のみ安定な拍順にする。
    originsはDが元metadata・humanize draw位置を保持するための情報であり、
    このAPI自身はrest、DSP、音源取得、キャッシュを扱わない。
    everyは全曲1始まり小節番号の倍数を選び、part.sectionsと厳密に交差する。
    対象小節の全onsetを置換し、曲末の不完全な群には追加しない。
    有効な空選択・短曲も設定と元イベントを検証した後に無変更で返す。
    available_voicesは実在voice名の集合で、省略時は既存合成打楽器のみ。
    kitは利用可能voiceの制限であり、音源の別名変換や代用は行わない。
    """
    name = part.get("name", "drums") if isinstance(part, dict) else "drums"

    def error(message, bar=1):
        return ValueError(f"[{name}] {bar}番目の小節: {message}")

    if not isinstance(part, dict) or not isinstance(song, dict):
        raise error("part/songはオブジェクトで指定してください")
    if (part.get("type", "drums" if "groove" in part else None) != "drums"
            or part.get("role", "rhythm") != "rhythm"):
        raise error("fill_last_barは直接drumsまたはrhythmのgrooveに指定してください")
    if any(k in part for k in ("instrument", "phrases", "grid", "style", "accent", "copy", "source")):
        raise error("fill_last_barとinstrument/phrases/grid/style/accent/copy/sourceは併用できません")
    if "groove" in part and "bars" in part:
        raise error("grooveとbarsは併用できません（空の指定も含む）")
    meter = song.get("meter")
    if not isinstance(meter, str) or meter not in _METERS:
        raise error("meterは4/4、3/4、6/8から指定してください")
    beats = _METERS[meter]
    if type(every) is not int or every <= 0:
        raise error("everyは正の整数で指定してください")
    if not isinstance(occurrences, list) or not occurrences:
        raise error("occurrencesは空でないリストで指定してください")
    end, next_bar = 0, 1
    for index, occ in enumerate(occurrences):
        if (not isinstance(occ, dict)
                or any(not isinstance(occ.get(k), str) or not occ[k] for k in ("name", "source"))
                or type(occ.get("occurrence")) is not int or occ["occurrence"] != index
                or type(occ.get("start_bar")) is not int or occ["start_bar"] != next_bar
                or type(occ.get("bars")) is not int or occ["bars"] <= 0
                or not _finite(occ.get("start_beat")) or occ["start_beat"] != end
                or not _finite(end + occ["bars"] * beats)):
            raise error("occurrencesの名前・素材・通番・小節・開始位置が不正です", next_bar)
        end += occ["bars"] * beats
        next_bar += occ["bars"]
    selected = part.get("sections")
    names = {o["name"] for o in occurrences}
    if "sections" in part and (not isinstance(selected, list)
                              or any(not isinstance(s, str) or s not in names for s in selected)):
        raise error("sectionsは展開されたセクション名のリストで指定してください")
    chosen = [o for o in occurrences if selected is None or o["name"] in selected]
    first_bar = next((o["start_bar"] + (-o["start_bar"] % every) for o in chosen
                      if o["start_bar"] + (-o["start_bar"] % every) < o["start_bar"] + o["bars"]),
                     chosen[0]["start_bar"] if chosen else 1)
    velocity = part.get("velocity", 95)
    if not _finite(velocity) or not 1 <= velocity <= 127:
        raise error("velocityは1〜127の有限数で指定してください", first_bar)
    if available_voices is None:
        available = _SYNTH_VOICES
    else:
        if (not isinstance(available_voices, (Mapping, list, tuple, set, frozenset))
                or any(not isinstance(v, str) or not v for v in available_voices)):
            raise error("available_voicesは打楽器名の集合で指定してください", first_bar)
        available = set(available_voices)
    kit = part.get("kit")
    if "kit" in part and (not isinstance(kit, list) or any(not isinstance(v, str) or v not in available for v in kit)):
        raise error("kitは使用可能な打楽器名の配列で指定してください", first_bar)
    bongo = (part.get("groove") == "bongo_8beat"
             or kit is not None and {"bongo_lo", "bongo_hi"} <= set(kit) and not {"kick", "snare"} & set(kit))
    low, high = ("bongo_lo", "bongo_hi") if bongo else ("kick", "snare")
    if not {low, high} <= available or kit is not None and not {low, high} <= set(kit):
        raise error("fill_last_barに必要な打楽器名がavailable_voices/kitにありません", first_bar)
    voices = part.get("voices", {})
    if not isinstance(voices, dict):
        raise error("voicesは打楽器名と設定のオブジェクトで指定してください", first_bar)
    for voice, config in voices.items():
        if not isinstance(voice, str) or voice not in available:
            raise error(f"voicesの打楽器名{voice!r}はありません", first_bar)
        if config is None:
            continue
        if not isinstance(config, dict):
            raise error(f"voices.{voice}は設定のオブジェクトまたはnullで指定してください", first_bar)
        for field in ("pan", "volume"):
            if field in config and (not _finite(config[field]) or abs(config[field]) > 3.4028234663852886e38):
                raise error(f"voices.{voice}.{field}は有限数で指定してください", first_bar)
    if "groove" in part:
        # 既存grooveの拍子・kit・固定2:1条件も、無変更の場合を含め検証する。
        compile_rhythm(part, song, occurrences, available_voices=available)
    elif "bars" in part:
        bars = part["bars"]
        if not isinstance(bars, list):
            raise error("barsは打楽器小節の配列で指定してください", first_bar)
        for index, bar in enumerate(bars):
            if not isinstance(bar, dict):
                raise error("barsの各小節は打楽器名と文字列のオブジェクトで指定してください", index + 1)
            for voice, pattern in bar.items():
                if not isinstance(voice, str) or voice not in available or not isinstance(pattern, str):
                    raise error("barsの打楽器名またはパターン文字列が不正です", index + 1)
                if any(ch not in "xXo.-_ |" for ch in pattern):
                    raise error("barsはx/X/o/休符で指定してください", index + 1)
    swing, unit = song.get("swing", 0), song.get("swing_unit", .5)
    if not _finite(swing) or not _finite(unit) or unit <= 0:
        raise error("song.swingは有限数、song.swing_unitは正の有限数で指定してください", first_bar)
    fixed = part.get("groove") in ("shuffle", "swing_ride")
    if fixed and swing != 0:
        raise error("shuffle/swing_rideとsong.swing非0は併用できません", first_bar)
    low_offsets = (0, 2) if meter == "4/4" else (0,) if meter == "3/4" else (0, 1.5)
    high_offsets = ((2, 2 + 2/3, 3, 3 + 2/3) if fixed else (2, 2.5, 3, 3.5)) if meter == "4/4" else (
        (1, 1.5, 2, 2.5) if meter == "3/4" else (1.5, 2, 2.5))
    deltas = (-10, 0, 10) if meter == "6/8" else (-20, -10, 0, 10)
    pattern = sorted([(t, low, 15) for t in low_offsets]
                     + [(t, high, delta) for t, delta in zip(high_offsets, deltas, strict=True)], key=lambda e: e[0])
    if not isinstance(source_events, list):
        raise error("source_eventsは打楽器イベントのリストで指定してください")
    for event in source_events:
        if not isinstance(event, tuple) or len(event) != 3:
            raise error("source_eventsは(beat,voice,velocity)の3タプルで指定してください")
        beat, voice, vel = event
        if not _finite(beat) or not 0 <= beat < end:
            raise error("source_eventsのbeatは曲内の有限数で指定してください")
        bar = math.floor(beat / beats) + 1
        if not isinstance(voice, str) or voice not in available:
            raise error("source_eventsの打楽器名はavailable_voicesから指定してください", bar)
        if not _finite(vel) or not 1 <= vel <= 127:
            raise error("source_eventsのvelocityは1〜127の有限数で指定してください", bar)
    fill_bars = []
    additions = []
    for occ in occurrences:
        selected_occurrence = selected is None or occ["name"] in selected
        # 候補は全曲通算の倍数のみ。選択の隙間や出現境界ではリセットしない。
        first = occ["start_bar"] + (-occ["start_bar"] % every)
        for bar in range(first, occ["start_bar"] + occ["bars"], every):
            start = (bar - 1) * beats
            if selected_occurrence:
                fill_bars.append(bar)
            for offset, voice, delta in pattern:
                beat = start + offset
                try:
                    moved = beat
                    if swing:
                        q = beat / unit
                        if abs(q - round(q)) < 1e-6 and int(round(q)) % 2 == 1:
                            moved += swing * unit / 3
                    valid = _finite(moved) and start <= moved < start + beats
                except (OverflowError, ValueError):
                    valid = False
                if not valid:
                    raise error("song.swing / song.swing_unitによる打点が元の小節外または非有限になります", bar)
                if selected_occurrence:
                    additions.append(((beat, voice, max(1, min(127, round(velocity + delta)))), None))
    if not fill_bars:
        return {"events": list(source_events), "origins": list(range(len(source_events))), "fill_bars": []}
    replaced = set(fill_bars)
    kept = [(event, index) for index, event in enumerate(source_events) if math.floor(event[0] / beats) + 1 not in replaced]
    combined = sorted(kept + additions, key=lambda item: item[0][0])
    return {"events": [event for event, _ in combined], "origins": [origin for _, origin in combined], "fill_bars": fill_bars}
