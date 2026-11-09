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
```

## 音源とライセンス

楽器の音は [VSCO 2 Community Edition](https://github.com/sgossner/VSCO-2-CE)（CC0）を使います。音源はリポジトリに含めず、初回に取得します。作った曲はクレジット表記なしで自由に使えます。
