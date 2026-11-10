# loop-bgm

<!-- last-reviewed: 2026-11-09 -->

AIと会話しながら、動画・ゲーム・TRPG向けのループBGMを作るツールです（開発中）。

AIは曲そのものではなく、テンポ・調・コード進行・パートを書いた「設計図」（`songs/<曲ID>/song.json`）を書きます。プログラムがCC0の楽器音源と合成音で鳴らし、継ぎ目のないループとして書き出します。設計図を直せば、直したパートだけを作り直せます。

- 仕様: [docs/spec.md](docs/spec.md)
- 開発の手順（AI向け、英語）: [AGENTS.md](AGENTS.md)

## 使い方（現時点）

```powershell
./setup.ps1
.venv/Scripts/python -m bgm fetch                  # 音源の取得（約1.2GB）
.venv/Scripts/python -m bgm render proto_test --no-mp3
.venv/Scripts/python -m bgm listen proto_test    # ローカルの試聴画面
# 音源取得なしで試す度数の見本
.venv/Scripts/python -m bgm render phase1_degrees --no-mp3
.venv/Scripts/python -m bgm listen phase1_degrees
# 音源取得なしで伴奏生成も試す見本
.venv/Scripts/python -m bgm render phase1_accompaniment --no-mp3
```

試聴画面ではループ再生・停止・WAV保存ができます。別の曲は `proto_test` を曲IDに置き換えてください。

`render` と `listen` は、どちらも読み込み時に設計図を検査します。不正な値は日本語で設定名と、該当するパート・小節を表示します。
現行の記法では、音符パートの `bars` は `["C4:4", "r:4"]` のような文字列の配列、ドラムの `bars` は `[{"kick":"x..."}]` のような辞書の配列です。
ドラムの個別音量・定位は `"voices":{"kick":{"volume":0.8,"pan":0}}` と書けます。
`tempo`・`beats_per_bar`・`swing_unit` は正の有限数、曲全体の `bars` は正の整数にしてください。数値の代わりに文字列や真偽値は使えません。
パートの `bars` の省略・`null`・空配列・空文字列は従来どおり無音になり、音符の小節 `""`・`"-"` は1小節の休符になります。

## 調と構成で書く見本

[`songs/phase1_degrees/song.json`](songs/phase1_degrees/song.json) は合成音だけの6小節（A/B/A、各2小節）の曲です。
`key` を `C major` から `C minor` に変えて再度 `render` すると、度数メロディの第3音がミからミ♭へ変わります。
絶対音で書いた `absolute` パートの C3 は変わりません。変更前のWAVは曲フォルダーの `history/` に残ります。

構造付きの曲には `key`・`meter`・`form`・`sections` がすべて必要です。
曲全体の小節数は `form` に並べた `sections` の小節数の合計になります。従来の曲全体の `bars`・`beats_per_bar` は省略してください（構成と異なる値はエラー）。
1拍は四分音符で、4/4は4拍、3/4と6/8は3拍です。`tempo` も四分音符の毎分拍数です。
`form` の `A'` は A の素材を使います。変奏はまだ生成しません。別の A' 定義が A と競合するとエラーです。

度数パートは `bars` の代わりに `grid` と `phrases` を指定します。`grid: "1/4"` の4/4なら、各小節にちょうど4トークンが必要です。
`phrases: {"A":"1 3 5 3 | 4 3 2 1", "B":"6 5 3 1 | 2 5 7 5"}` のように素材ごとに書き、小節を `|` で区切ります。
省略された音符の補完やフレーズの繰り返しはしません。

- `1`〜`7` は長音階または自然短音階の度数。`#4`・`b7` は半音変化、`,` は1オクターブ下、`'` は上です。
- 全楽器共通で基準は主音のオクターブ4（C majorの1=C4、A minorの1=A4）。`octave` は整数の相対移動、`transpose` は整数の半音移動です。
- `.` は休符、`-` は直前の音を延長します。休符の直後やセクションをまたぐ延長はできません。
- `[1 3 5]` は1トークンの和音、`>`・`<` は強弱（例 `5>`、`[1 3 5]<`）。`velocity` は1〜127、既定値90です。
- 度数パートの `sections: ["A"]` は出現名を選びます。A' も鳴らすなら `"A'"` を追加してください。
- 絶対音の `bars` と度数の `phrases` は別パートで併用できます。同じパート内で混ぜることはできません。

`sections` の `chords` は小節数どおりに `"I | IV V"` のように書きます。小節内の複数コードには拍数を等分します。
コードからベース・和音の伴奏を生成できます。使える型は次節を参照してください。
通常役割 `I ii iii IV V vi vii°` は短調でも使用でき、その調の和音へ変わります（I→i、IV→iv、Vは長和音のまま）。短調の明示 `v` は短和音です。
長調の `iv` は借用、先頭 `b`・`#` の根音は同主長調を基準にします（C major/minorの `bVII` はどちらもB♭）。
接尾辞は単独の `7`・`maj7`・`sus4`・`add9`、転回は `/3`（第三音を最低音にする）です。`sus4/3` と完全減七和音は未対応です。

## 伴奏の型で書く見本

[`songs/phase1_accompaniment/song.json`](songs/phase1_accompaniment/song.json) は合成音だけの A/B/A、全6小節です。
度数メロディ、生成ベース・和音・リズムに、比較用の絶対音と直接記述ドラムを重ねています。
2・6小節目の途中で IV→V に変わります。`key` だけを `C minor` にすると度数と伴奏の音高が変わり、絶対音・打楽器の音は同じです。

```json
{"name":"bass","role":"bass","instrument":"bass","style":"root_fifth"}
{"name":"chords","role":"chords","instrument":"pad","style":"pad"}
{"name":"rhythm","role":"rhythm","groove":"8beat"}
```

各行は `parts` 配列に入れる1パートの例です。`style` / `groove` と同じパートの `bars` / `phrases` / `grid` は、空でも併用できません。
`style` と `groove` の併用もエラーです。生成には構造付きの曲が必要です。

| パート | 対応する型 | 拍子 |
| --- | --- | --- |
| `role: bass`、`style` | `root_whole`、`root_quarter`、`root_fifth` | 4/4、3/4、6/8 |
| `role: chords`、`style` | `pad`、`block`、`offbeat` | 4/4、3/4、6/8 |
| `role: rhythm`、`groove` | `8beat` | 4/4 |
| 同上 | `march` | 4/4、6/8 |
| 同上 | `waltz` | 3/4 |
| 同上 | `ambient_none`（無音） | 4/4、3/4、6/8 |

生成リズムは `type: drums` を省略できます。既存の `type: drums` に `groove` を加える場合は `role` を省略できます。
既定の打楽器は合成 kick・snare・hat です。`kit` は既存打楽器名の配列で、型が使う音をすべて含めます。音名の置換ではありません。
`voices` は従来どおり個別の音量・定位です。`sections` は度数パートと同じ出現名による選択です。

ベースはコード根音の1オクターブ下が基準で、転回の最低音には追従しません。和音は転回・拡張音の間隔を保って全体を移動します。
`octave` / `transpose` の後で楽器の音域へオクターブ補正します。補正不能ならエラーです。
生成音の gate・strum・swing・humanize は和音や選択区間の終端を越えて持続音を延ばしません（音源のリリース・残響は残ります）。

仕様3.6の残りは、ベース `octave_8th`・`walking`・`arpeggio`、和音 `arpeggio_up`・`broken`・`strum`・`waltz`、
リズム `16beat`・`shuffle`・`bossa`・`swing_ride`・`bongo_8beat`、arrange 全種（`phrase_start`・`offbeat_tick`・`counter`）です。
次に周回変化、曲の型3種類、フェーズ1の試聴確認へ進みます。フェーズ1と仕様3.6全体はまだ完了していません。

## 音源とライセンス

楽器の音は [VSCO 2 Community Edition](https://github.com/sgossner/VSCO-2-CE)（CC0）を使います。音源はリポジトリに含めず、初回に取得します。作った曲はクレジット表記なしで自由に使えます。
