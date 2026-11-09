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
```

試聴画面ではループ再生・停止・WAV保存ができます。別の曲は `proto_test` を曲IDに置き換えてください。

`render` と `listen` は、どちらも読み込み時に設計図を検査します。不正な値は日本語で設定名と、該当するパート・小節を表示します。
現行の記法では、音符パートの `bars` は `["C4:4", "r:4"]` のような文字列の配列、ドラムの `bars` は `[{"kick":"x..."}]` のような辞書の配列です。
ドラムの個別音量・定位は `"voices":{"kick":{"volume":0.8,"pan":0}}` と書けます。
`tempo`・`beats_per_bar`・`swing_unit` は正の有限数、曲全体の `bars` は正の整数にしてください。数値の代わりに文字列や真偽値は使えません。
パートの `bars` の省略・`null`・空配列・空文字列は従来どおり無音になり、音符の小節 `""`・`"-"` は1小節の休符になります。

## 音源とライセンス

楽器の音は [VSCO 2 Community Edition](https://github.com/sgossner/VSCO-2-CE)（CC0）を使います。音源はリポジトリに含めず、初回に取得します。作った曲はクレジット表記なしで自由に使えます。
