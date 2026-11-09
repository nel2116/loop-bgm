# 引き継ぎ（Claude Code → Codex）

<!-- last-reviewed: 2026-11-09 -->

2026-11-09 作成。Claude Code の週間上限に備えて、ここまでの状況をまとめる。作業を始める前に、この文書と `docs/spec.md` を読むこと。

## 目的

AIにテキストの「設計図」（song.json）を書かせ、プログラムがCC0音源で鳴らして、継ぎ目のないループBGMを書き出すツールを作る。参考にしたのは「しゃりなのループBGM制作キット」（https://note.com/chronoit/n/n0d5413445091 ）。有料部分のコードは参照せず、独自に実装する。

## 決まったこと（ユーザーと合意済み）

仕様の詳細は `docs/spec.md` にある（原本は Claude Docs: https://claude.ai/artifact/WGt1Y2SALB1a4Nsmxs64w4 ）。主な決定事項は次のとおり。

- 用途：動画、ゲーム、TRPG（`usage` プロファイルで切り替える。spec 5.4）
- 設計図：メロディは調の中の度数、和音はコードの役割（ローマ数字）で書き、`key` を変えるだけで長調と短調を切り替えられるようにする。伴奏は「型」を選ぶとプログラムが音を作る（spec 3章）
- 試聴UI：再生と比較に加えて、修正もUIから選べる形にする（値の変更はUIがその場で行い、考える必要がある修正はAIへの依頼ファイルにする。spec 8章）
- 追加機能：効果音の切り出し、チップチューン風、鼻歌からメロディ。MIDIの書き出しは対象外（spec 9章）
- 対応環境：Windows のみ
- 開発の進め方：DXForgeEX（`F:\HAL\Self\DXForgeEX`）のハーネスを流用する（spec 11章）
  - GitHub `nel2116/loop-bgm` を**公開**で作り、`develop`＋`main` の運用にする
  - 試聴確認は「節目だけ」：PRごとには止めず、各フェーズの終わりに見本曲をまとめて書き出し、ユーザーが聴く

## 現在の状態

- git リポジトリはあるが、コミットはまだない。リモートもない。
- `bgm/` に試作コードがある（約1,100行。前のセッションが書いた）。曲を実際に書き出せるかは**まだ確かめていない**。
  - `fetch.py`：VSCO 2 CE の音源を、`data/vsco2-lock.json` のハッシュ値と照合しながら取得する
  - `render.py`：song.json の読み込み、パートごとのキャッシュ（`part_hash`）、ループ処理（`fold_loop`）、継ぎ目の確認（`check_loop`）
  - `sampler.py`、`synth.py`、`theory.py`、`instruments.py`、`paths.py`
  - 試作の設計図は音を絶対音名（`C4:1`）で書く。度数の記法は未実装
- `samples/vsco2/` に音源の一部（約51MB）を取得済み。`tmp/tree.json` は lock ファイルを作るときに使った GitHub の tree 一覧。
- `.venv/`（Python 3.13、numpy、soundfile）がある。
- `songs/` フォルダはまだない（`paths.py` は `songs/` を参照している）。

## 次にやること（フェーズ0。spec 11.8）

1. **公開リポジトリ `nel2116/loop-bgm` の作成は、ユーザーの確認を取ってから行う**（外部に公開する操作のため。まだ了承を得ていない）。
2. `.gitignore` を作る（`.venv/`、`samples/`、`songs/*/out/`、`build/`、`tmp/`、`__pycache__/`、音声ファイル）。
3. DXForgeEX から `AGENTS.md`、`CLAUDE.md`、`docs/dev/`、`.claude/skills/writing-docs` などを移し、loop-bgm 向けに書き換える（Primal、C++、FBX、DXC など DXForgeEX 固有の内容は持ち込まない）。
4. `Tests/` のフックと、Python 向けに作り直した `check_conventions.py` を移し、`.claude/settings.json` に登録する。
5. `CodexReview.ps1`、`CleanupMerged.ps1`、`StartWorker.ps1`、`WorkerStatus.ps1` と、それぞれのテストを移す。`PrePr.ps1` は Python 向けに作り直す。
6. CI（GitHub Actions、windows-latest）と `pr-automation.yml` を置き、`develop` のブランチ保護を設定する。
7. 試作コードを初回コミットし、曲を書き出せることを確かめる。
8. 小さなPRを1本、Issue から自動マージまで通して、仕組みが動くことを確かめる。

その後はフェーズ1（設計図の度数記法、伴奏の型、周回の変化。spec 10.1）に進む。

## 注意

- `python3` は使わず `python` を使う（このPCの `python3` は Windows Store のスタブで、何もしない）。
- ユーザーへの報告は日本語で行う。コミットメッセージ、PR、Issue、コードコメントも日本語（DXForgeEX と同じ慣習）。
- 未決事項は spec 10.2 にある（音量の目標値、初版の楽器、UIからの依頼の処理方法、TRPG用長尺版の変化、曲の型の増やし方、コードのライセンス、開発用スキルを利用者に見せるかどうか）。決める必要が出たら、ユーザーに聞く。
- この引き継ぎ文書は、フェーズ0で `AGENTS.md` と `docs/dev/` を整えたら削除してよい。

## 進捗（2026-11-09 追記、Claude Code）

フェーズ0の手順 2〜5 と 7 を済ませた。上の「現在の状態」より、こちらが新しい。

- 試作コードは動く：`songs/proto_test/song.json`（動画の例と同じ編成：ボンゴ、タンバリン、コントラバス、バイオリンのピチカート、木琴）を 2.1 秒で書き出し、継ぎ目のチェックも OK。2 回目はパートのキャッシュが効く。使った楽器の音源だけ取得済み（`python -m bgm status` で 152/1164 ファイル）。
- CLI を追加した：`python -m bgm render|fetch|status`（`bgm/__main__.py`）。
- ハーネスを移した：`AGENTS.md`、`CLAUDE.md`、`docs/dev/`（BuildAndTest、Architecture は新規、WorkerRules と ReviewAndMerge は DXForgeEX から写して手直し）、`docs/ListeningCheck.md`、`README.md`、`.claude/settings.json`（フック）、`.claude/skills/`（create-issue、next-task、orchestration-prompt、ship-pr、writing-docs）、`Tests/` のフックとテスト、`CodexReview.ps1`、`CleanupMerged.ps1`、`StartWorker.ps1`、`WorkerStatus.ps1`、`PrePr.ps1`（Python 向けに新規）、`setup.ps1`、CI（`.github/workflows/ci.yml`）、`pr-automation.yml`。
- 確認した結果：`python Tests/check_conventions.py` 違反なし、`ruff check .` OK、`pytest -q` 73 件成功、PowerShell の 3 つのテスト（CodexReview、WorkerTools、CleanupMerged）成功。
- テストは `Tests/` に 1 つにまとめた（Windows では `tests/` と `Tests/` が同じフォルダになるため）。

残り:

1. GitHub `nel2116/loop-bgm`（公開）の作成と push、`develop` の作成、ブランチ保護（CI の 2 ジョブ、`No hold label`、`codex-review` を必須に）。ユーザーは「進められるところまで進める」と了承済み。
2. `PrePr.ps1` にはまだテストがない（DXForgeEX の `PrePr.Tests.ps1` は C++ 向けで移していない）。
3. 小さな PR を 1 本、Issue から自動マージまで通す（手順 8）。
4. その後フェーズ1（spec 10.1）。
