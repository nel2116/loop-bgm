# loop-bgm

<!-- last-reviewed: 2026-11-11 -->

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
# 追加の伴奏型（walking・strum・shuffle）
.venv/Scripts/python -m bgm render phase1_patterns --no-mp3
.venv/Scripts/python -m bgm listen phase1_patterns
# コピー・句頭装飾・裏拍・合いの手・直接書いた独立対旋律
.venv/Scripts/python -m bgm render phase1_arrangements --no-mp3
# 周回ごとの変化（オクターブ・楽器・休み・フィル・周期の違うアルペジオ）
.venv/Scripts/python -m bgm render phase1_variations --no-mp3
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
`form` の `A'` は A の素材を使います。変奏は自動では付かず、`variation` で指定します（後述）。別の A' 定義が A と競合するとエラーです。

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
| `role: bass`、`style` | `root_whole`、`root_quarter`、`root_fifth`、`octave_8th`、`walking`、`arpeggio` | 4/4、3/4、6/8 |
| `role: chords`、`style` | `pad`、`block`、`offbeat`、`arpeggio_up`、`broken`、`strum` | 4/4、3/4、6/8 |
| 同上 | `waltz` | 3/4 |
| `role: rhythm`、`groove` | `8beat` | 4/4 |
| 同上 | `16beat`、`shuffle`、`bossa`、`swing_ride`、`bongo_8beat` | 4/4 |
| 同上 | `march` | 4/4、6/8 |
| 同上 | `waltz` | 3/4 |
| 同上 | `ambient_none`（無音） | 4/4、3/4、6/8 |

生成リズムは `type: drums` を省略できます。既存の `type: drums` に `groove` を加える場合は `role` を省略できます。
既定の打楽器は合成 kick・snare・hat です。`kit` は既存打楽器名の配列で、型が使う音をすべて含めます。音名の置換ではありません。
`voices` は従来どおり個別の音量・定位です。`sections` は度数パートと同じ出現名による選択です。

ベースはコード根音の1オクターブ下が基準です。`arpeggio` だけは転回後の全構成音を1オクターブ下げて順番に鳴らします。
`walking` は根音・第三音・第五音を巡り、次の選択区間の和音へ半音下から近づきます。非選択区間は飛び越しません。
和音は転回・拡張音の間隔を保って全体を移動します。
`octave` / `transpose` の後で楽器の音域へオクターブ補正します。補正不能ならエラーです。
生成音の gate・strum・swing・humanize は和音や選択区間の終端を越えて持続音を延ばしません（音源のリリース・残響は残ります）。

[`songs/phase1_patterns/song.json`](songs/phase1_patterns/song.json) は A/B/A/A' の4小節です。
1・3小節目は小節内で3回和音が切り替わり、4小節目の A' はベース・和音を休みます。
`strum` は音を順に0.02秒ずつ遅らせます。`strum` 数値を明示すれば0や負数もそのまま使います。
`shuffle` と `swing_ride` は固定の2:1なので、曲の `swing` は省略か0にしてください。
`swing_ride`・`bongo_8beat` は実サンプルが必要です。`kit` には使う全音名を含めてください。合成音への置換はしません。
詳しい打点・音順と境界方針は[設計記録](docs/design/phase1-patterns.md)にあります。

## コピー・装飾と独立した対旋律

[`songs/phase1_arrangements/song.json`](songs/phase1_arrangements/song.json) は A/B/A/A' の4小節です。
1・3小節目は分数拍で和音が切り替わり、メロディは伸ばす音と休符を含みます。
2小節目のメロディは全休符で、`counter` が合いの手を入れます。4小節目はメロディとそのコピー・合いの手を休み、直接書いた対旋律と句頭装飾は鳴ります。

```json
{"name":"melody_hi","role":"arrange","copy":"melody","octave":1}
{"name":"sparkle","role":"arrange","instrument":"kalimba","accent":"phrase_start"}
{"name":"tick","role":"arrange","accent":"offbeat_tick","kit":["hat"]}
{"name":"response","role":"arrange","instrument":"kalimba","accent":"counter","source":"melody"}
{"name":"countermelody","role":"arrange","instrument":"triangle_wave","bars":["G4:4"]}
```

`copy` は名前で参照し、後に書いたパートやコピーの連鎖も使えます。有音程のメロディ・ベース・和音・アレンジと、role省略の従来音符が対象です。
楽器の省略時は元の実効楽器だけを継承します。明示すれば変更でき、`null` はエラーです。音高・記譜長・強さをコピーし、コピー先の `octave` / `transpose` と音域補正を行います。
元の音量・定位・mute・gateなどは継承しません。コピー先の `velocity` 指定はエラーです。打楽器のコピーと循環参照はできません。
`sections` は A と A' を区別します。コピーは元の選択とコピー先の選択を満たす開始音だけを使い、選択区間前から伸びる音を再発音しません。

`phrase_start` は選択した出現の頭に、実際の和音の最高音より1オクターブ上を最大0.5拍鳴らします。各小節には追加しません。
`offbeat_tick` は実在の hat を使い、4/4は0.5・1.5・2.5・3.5拍、3/4は0.5・1.5・2.5拍、6/8は0.75・2.25拍に置きます。
`counter` の `source` は直接書いた `role: melody` が必須です。gate前の記譜長を占有とし、選択した休みの中で和音・小節ごとに根音の1オクターブ上を半拍ごとに短く鳴らします。
gateで短くした隙間を休符扱いしません。元が非選択の区間は合いの手の対象外ですが、選択した全休符は対象です。
生成指定と直接記譜・style・grooveの併用、counter以外の `source` は空/nullでもエラーです。

独立した対旋律は別の `role: arrange` に `phrases` / `grid` または絶対音の `bars` で直接書き、メロディと重ねられます。
`counter` は固定根音の合いの手で、独立した旋律を作曲する機能ではありません。これらは最小の初期規則であり、音楽的自然さは未確認です。
詳しい選択・音域・境界・限界は[設計記録](docs/design/phase1-arrangements.md)を参照してください。

仕様3.6に掲載された型、コピー、直接記述の独立対旋律を実装しました。

## 周回ごとの変化

[`songs/phase1_variations/song.json`](songs/phase1_variations/song.json) は A/B/A/A' の8小節です（合成音だけ）。
曲の最上位に `variation` 配列を書くと、1つのループの中で変化を付けます。書いた順番は結果に影響しません。

```json
{"section":"A'","part":"melody","do":"octave_up"}
{"section":"A'","part":"melody","do":"instrument","instrument":"bass"}
{"section":"B","part":"held","do":"rest"}
{"part":"drums","do":"fill_last_bar","every":8}
{"part":"arp","do":"period","beats":3}
```

- `octave_up`・`instrument`・`rest` は `section` の出現名（A と A' は別）のすべての出現に効きます。楽器変更は音の出だしで決まり、伸びている前の音は切りません。
- `rest` はその区間の音を消し、前から伸びている音は区間の頭で切ります。`copy` は変化後の元パートの音を使い、`counter` は変化後の休みに合いの手を入れます。
- `fill_last_bar` は曲頭から数えて `every` 小節ごとの最後の小節を、その拍子のフィルに置き換えます。
- `period` は `arpeggio_up` の和音を曲頭から `beats` 拍周期で鳴らし、小節とずれて重なります。
- 不正な指定は音源を読む前に日本語でエラーになります。該当する区間がない指定は何も変えません。
- 細かな強さ・タイミングのゆらぎは従来の `humanize`（パート名から決まる固定シード）のままです。

詳しい表・適用順・未実装項目は[設計記録](docs/design/phase1-variations.md)を参照してください。

次は曲の型3種類とフェーズ1の試聴確認です。
フェーズ1全体はまだ完了していません。実サンプルの swing_ride / bongo_8beat WAV と主観試聴は未検証です。

## 音源とライセンス

楽器の音は [VSCO 2 Community Edition](https://github.com/sgossner/VSCO-2-CE)（CC0）を使います。音源はリポジトリに含めず、初回に取得します。作った曲はクレジット表記なしで自由に使えます。
