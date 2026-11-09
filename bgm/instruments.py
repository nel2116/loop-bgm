"""Instrument definitions.

Sampled instruments come from VSCO 2 Community Edition (CC0).
Each entry says which folder to read and how to get the note and the
velocity layer from each file name.

Fields
  src      folder inside the VSCO 2 CE repository
  rx       regex for the file name; groups: note | idx, vel, rr
  idx_map  for idx files: "chart" (read MappingChart.txt) or (base, step)
  oct      octave correction for the note names in the file names
  mode     "ring": the note rings out after note-off (pizzicato, mallets)
           "gate": the sample is faded out at note-off (sustained sounds)
  release  fade-out length in seconds at note-off (gate) or max ring (ring)
  gain     level trim so instruments sit at a similar loudness
  ja       Japanese name for listings
  range    playable MIDI range (inclusive)
"""

N = r"(?P<note>[A-G]#?-?\d)"

SAMPLED = {
    # ---- keys ----
    "piano": dict(src="Keys/Upright Piano", rx=r"^Player_dyn(?P<vel>\d)_rr1_(?P<idx>\d{3})\.wav$",
                  idx_map="chart", mode="gate", release=0.45, gain=1.0, ja="アップライトピアノ", range=(21, 108)),
    "piano_old": dict(src="Keys/Upright Nr1", rx=rf"^UR1_{N}_(?P<vel>pp|mf|f)_RR(?P<rr>\d)\.wav$",
                      mode="gate", release=0.45, gain=1.0, ja="古いピアノ", range=(24, 103)),
    "organ": dict(src="Keys/Organ/Loud", rx=r"^Rode_Man3Open_(?P<idx>\d+)\.wav$",
                  idx_map=(35, 1), mode="gate", release=0.25, gain=0.6, ja="パイプオルガン", range=(36, 96)),
    # ---- mallets ----
    "glockenspiel": dict(src="Percussion/Glock", rx=rf"^glock_medium_{N}\.wav$",
                         mode="ring", release=3.0, gain=0.7, ja="グロッケン", range=(67, 108)),
    "xylophone": dict(src="Percussion/Xylo", rx=rf"^Xylo_Medium_{N}_ff_01_far\.wav$",
                      mode="ring", release=1.5, gain=0.7, ja="シロフォン", range=(53, 108)),
    "marimba": dict(src="Percussion/Marimba", rx=rf"^Marimba_hit_Outrigger_{N}_loud_01\.wav$",
                    mode="ring", release=2.0, gain=0.9, ja="マリンバ", range=(36, 96)),
    # ---- strings ----
    "harp": dict(src="Strings/Harp", rx=rf"^KSHarp_{N}_(?P<vel>mf|f|p)\.wav$",
                 mode="ring", release=4.0, gain=0.9, ja="ハープ", range=(24, 103)),
    "violins_pizz": dict(src="Strings/Violin Section/Pizz", rx=rf"^VlnEns_Pizz_{N}_v(?P<vel>\d)_rr(?P<rr>\d)\.wav$",
                         mode="ring", release=1.5, gain=0.9, ja="バイオリン（ピチカート）", range=(55, 100)),
    "violins": dict(src="Strings/Violin Section/susVib", rx=rf"^VlnEns_susVib_{N}_v(?P<vel>\d)\.wav$",
                    mode="gate", release=0.35, gain=0.8, ja="バイオリン合奏（ロング）", range=(55, 100)),
    "violins_spic": dict(src="Strings/Violin Section/Spic", rx=rf"^VlnEns_Spic_{N}_v(?P<vel>\d)_rr(?P<rr>\d)\.wav$",
                         mode="ring", release=0.6, gain=0.9, ja="バイオリン合奏（短く弾む）", range=(55, 100)),
    "violas": dict(src="Strings/Viola Section/susvib", rx=rf"^ViolaEns_susvib_{N}_v(?P<vel>\d)_\d\.wav$",
                   mode="gate", release=0.35, gain=0.8, ja="ビオラ合奏（ロング）", range=(48, 88)),
    "cellos": dict(src="Strings/Cello Section/susvib", rx=rf"^susvib_{N}_v(?P<vel>\d)_\d\.wav$",
                   mode="gate", release=0.4, gain=0.8, ja="チェロ合奏（ロング）", range=(36, 76)),
    "cellos_pizz": dict(src="Strings/Cello Section/pizzT", rx=rf"^pizzT_{N}_v(?P<vel>\d)_RR(?P<rr>\d)\.wav$",
                        mode="ring", release=1.5, gain=0.9, ja="チェロ（ピチカート）", range=(36, 76)),
    "contrabass_pizz": dict(src="Strings/Solo Contrabass/Pizz", rx=rf"^BKCtbss_Pizz_{N}_v(?P<vel>\d)_rr(?P<rr>\d)\.wav$",
                            mode="ring", release=1.5, gain=1.0, ja="コントラバス（ピチカート）", range=(28, 67)),
    "solo_violin": dict(src="Strings/Solo Violin/Arco Vib", rx=rf"^LLVln_ArcoVib_{N}_(?P<vel>p|f)\.wav$",
                        mode="gate", release=0.3, gain=0.8, ja="ソロバイオリン", range=(55, 100)),
    # ---- woodwinds ----
    "flute": dict(src="Woodwinds/Flute/susNV", rx=rf"^LDFlute_susNV_{N}_v(?P<vel>\d)_\d\.wav$",
                  mode="gate", release=0.2, gain=0.8, ja="フルート（ロング）", range=(60, 96)),
    "flute_stac": dict(src="Woodwinds/Flute/stac", rx=rf"^LDFlute_stac_{N}_v(?P<vel>\d)_rr(?P<rr>\d)\.wav$",
                       mode="ring", release=0.5, gain=0.8, ja="フルート（短く）", range=(60, 96)),
    "clarinet": dict(src="Woodwinds/Clarinet/susLong", rx=rf"^DCClar_susLong_{N}_v(?P<vel>\d)_rr(?P<rr>\d)_sum\.wav$",
                     mode="gate", release=0.2, gain=0.8, ja="クラリネット（ロング）", range=(50, 91)),
    "clarinet_stac": dict(src="Woodwinds/Clarinet/stac", rx=rf"^DCClar_stac_{N}_v(?P<vel>\d)_rr(?P<rr>\d)_sum\.wav$",
                          mode="ring", release=0.5, gain=0.8, ja="クラリネット（短く）", range=(50, 91)),
    "oboe": dict(src="Woodwinds/Oboe/Sus", rx=rf"^Oboe_Sus_{N}_v(?P<vel>\d)_Main\.wav$",
                 mode="gate", release=0.2, gain=0.8, ja="オーボエ（ロング）", range=(58, 91)),
    "oboe_stac": dict(src="Woodwinds/Oboe/Stacc", rx=rf"^Oboe_Stacc_{N}_v(?P<vel>\d)_rr(?P<rr>\d)_Main\.wav$",
                      mode="ring", release=0.5, gain=0.8, ja="オーボエ（短く）", range=(58, 91)),
    "bassoon": dict(src="Woodwinds/Bassoon/sus", rx=rf"^PSBassoon_{N}_v(?P<vel>\d)_\d\.wav$",
                    mode="gate", release=0.2, gain=0.9, ja="ファゴット（ロング）", range=(34, 75)),
    "bassoon_stac": dict(src="Woodwinds/Bassoon/stac", rx=rf"^PSBassoon_{N}_v(?P<vel>\d)_rr(?P<rr>\d)\.wav$",
                         mode="ring", release=0.5, gain=0.9, ja="ファゴット（短く）", range=(34, 75)),
    # ---- brass ----
    "trumpet": dict(src="Brass/Trumpet/sus", rx=rf"^Sum_SHTrumpet_sus_{N}_v(?P<vel>\d)_rr(?P<rr>\d)\.wav$",
                    mode="gate", release=0.2, gain=0.7, ja="トランペット（ロング）", range=(54, 84)),
    "trumpet_stac": dict(src="Brass/Trumpet/stac", rx=rf"^Sum_SHTrumpet_stac_{N}_v(?P<vel>\d)_rr(?P<rr>\d)\.wav$",
                         mode="ring", release=0.5, gain=0.7, ja="トランペット（短く）", range=(54, 84)),
    "horn": dict(src="Brass/F Horn/sus", rx=rf"^MOHorn_sus_{N}_v(?P<vel>\d)_\d\.wav$",
                 mode="gate", release=0.3, gain=0.8, ja="ホルン", range=(34, 77)),
    "trombone_stac": dict(src="Brass/Tenor Trombone/stac", rx=rf"^tenortbn_stac_{N}_v(?P<vel>\d)_rr(?P<rr>\d)\.wav$",
                          mode="ring", release=0.5, gain=0.7, ja="トロンボーン（短く）", range=(40, 72)),
    "tuba_stac": dict(src="Brass/Tuba/stac", rx=rf"^Tuba3_stac_{N}_v(?P<vel>\d)_rr(?P<rr>\d)_Sum\.wav$",
                      mode="ring", release=0.5, gain=0.8, ja="チューバ（短く）", range=(28, 65)),
}

# Unpitched percussion used in "drums" parts.
# Each voice lists files (regex over full repo paths) and how to read the velocity layer.
_P = "Percussion/"
_V1 = "VSCO 1 Percussion/"
PERCUSSION = {
    "orch_bd": dict(rx=_P + r"BDrumNewhit_v(?P<vel>\d)_rr(?P<rr>\d)_Sum\.wav", ja="大太鼓", gain=1.0),
    "orch_snare": dict(rx=_P + r"Snare2-HitSN_v(?P<vel>\d)_rr(?P<rr>\d)_Sum\.wav", ja="スネア（生）", gain=0.8),
    "crash": dict(rx=_P + r"cymbal-crash1_(?P<vel>pp|mp|mf|ff)_rr(?P<rr>\d)\.wav", ja="クラッシュシンバル", gain=0.6),
    "ride": dict(rx=_P + r"susCymb1-hitstick_(?P<vel>pp|mp|f|fff)_rr(?P<rr>\d)\.wav", ja="吊りシンバル（スティック）", gain=0.5),
    "tambourine": dict(rx=_P + r"Tamb1-Hit_v(?P<vel>\d)_rr(?P<rr>\d)_Sum\.wav", ja="タンバリン", gain=0.6),
    "tamb_shake": dict(rx=_P + r"Tamb1-Shake_v(?P<vel>\d)_rr(?P<rr>\d)_Sum\.wav", ja="タンバリン（振る）", gain=0.5),
    "triangle": dict(rx=_P + r"Triangle3-Hit_v(?P<vel>\d)_rr(?P<rr>\d)_Sum\.wav", ja="トライアングル", gain=0.5),
    "claves": dict(rx=_P + r"Claves1_Hit_v(?P<vel>\d)_rr(?P<rr>\d)_Sum\.wav", ja="クラベス", gain=0.6),
    "cowbell": dict(rx=_P + r"Cowbell1_Hit_v(?P<vel>\d)_rr(?P<rr>\d)_Sum\.wav", ja="カウベル", gain=0.5),
    "conga": dict(rx=_P + r"Conga-HitN_v(?P<vel>\d)_rr(?P<rr>\d)_Sum\.wav", ja="コンガ", gain=0.8),
    "conga_hi": dict(rx=_P + r"Quinto-HitN_v(?P<vel>\d)_rr(?P<rr>\d)_Sum\.wav", ja="コンガ（高）", gain=0.8),
    "conga_lo": dict(rx=_P + r"Tumba-HitN_v(?P<vel>\d)_rr(?P<rr>\d)_Sum\.wav", ja="コンガ（低）", gain=0.8),
    "bongo_hi": dict(rx=_V1 + r"drums/other/Bongos/HighBongo(?P<rr>\d)\.wav", ja="ボンゴ（高）", gain=0.8),
    "bongo_lo": dict(rx=_V1 + r"drums/other/Bongos/LowBongo(?P<rr>\d)\.wav", ja="ボンゴ（低）", gain=0.8),
    "woodblock": dict(rx=_P + r"LogDrumHi_MedM_v(?P<vel>\d)_rr(?P<rr>\d)_Sum\.wav", ja="ログドラム（高）", gain=0.7),
    "woodblock_lo": dict(rx=_P + r"LogDrumLo_MedM_v(?P<vel>\d)_rr(?P<rr>\d)_Sum\.wav", ja="ログドラム（低）", gain=0.7),
    "shaker": dict(rx=_V1 + r"varWood/Camo's Shaker/shake(?P<rr>\d)\.wav", ja="シェイカー", gain=0.5),
    "cabasa": dict(rx=_V1 + r"varMetal/various/cabasa_(?P<rr>\d)\.wav", ja="カバサ", gain=0.5),
    "sleighbells": dict(rx=_P + r"Sleighbells_Hit_v1_rr(?P<rr>\d)_Mid\.wav", ja="スレイベル", gain=0.5),
    "agogo": dict(rx=_V1 + r"varMetal/various/agogoBell3_(?P<vel>f|ff)_(?P<rr>\d)\.wav", ja="アゴゴ", gain=0.5),
    "timpani": dict(rx=_P + r"Timpani/Timpani1_Hit_v(?P<vel>\d)_rr(?P<rr>\d)_Sum\.wav", ja="ティンパニ", gain=0.9),
    "guiro": dict(rx=_P + r"Guiro-Hit_v1_rr(?P<rr>\d)_Sum\.wav", ja="ギロ", gain=0.6),
}

# Synthesized sounds (no download needed). Implemented in synth.py.
SYNTH_PITCHED = {
    "e_piano": "エレピ（FM）",
    "bass": "ベース（合成）",
    "nylon_guitar": "ナイロンギター（合成）",
    "kalimba": "カリンバ（合成）",
    "music_box": "オルゴール（合成）",
    "pad": "シンセパッド",
    "square": "矩形波（チップ音）",
    "pulse": "細い矩形波（チップ音）",
    "triangle_wave": "三角波（チップ音）",
    "saw": "ノコギリ波",
}
SYNTH_DRUMS = {
    "kick": "キック（合成）",
    "snare": "スネア（合成）",
    "hat": "ハイハット（合成）",
    "open_hat": "オープンハイハット（合成）",
    "clap": "クラップ（合成）",
    "rim": "リムショット（合成）",
    "noise_hit": "ノイズ（チップ音）",
}

DYN_ORDER = ["ppp", "pp", "p", "mp", "mf", "f", "ff", "fff", "loud"]


def vel_rank(token):
    """Turn a velocity-layer token into a sortable number (soft -> loud)."""
    if token is None:
        return 0
    if token.isdigit():
        return int(token)
    return DYN_ORDER.index(token) if token in DYN_ORDER else 0


def needed_paths(tree_paths, names=None):
    """Repository paths needed for the given instruments (all when names is None)."""
    import re

    want = set()
    for name, spec in SAMPLED.items():
        if names and name not in names:
            continue
        rx = re.compile(spec["rx"])
        prefix = spec["src"] + "/"
        for p in tree_paths:
            if p.startswith(prefix) and "/" not in p[len(prefix):] and rx.match(p[len(prefix):]):
                want.add(p)
        if spec.get("idx_map") == "chart":
            want.add(prefix + "MappingChart.txt")
    for name, spec in PERCUSSION.items():
        if names and name not in names:
            continue
        rx = re.compile("^" + spec["rx"] + "$")
        want.update(p for p in tree_paths if rx.match(p))
    return sorted(want)
