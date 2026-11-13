"""Command line: python -m bgm <command> ...

  python -m bgm render <song> [--force] [--no-mp3]   render songs/<song>/song.json (or a path)
  python -m bgm fetch [instrument ...] [--verify]    download the samples the kit uses
  python -m bgm listen [song] [--port 8765]           open a local listening page
  python -m bgm status [instrument ...]              how many sample files are missing
  python -m bgm new <song> --style <type>             create songs/<song>/song.json from templates/<type>.json
"""

import argparse
import sys


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="python -m bgm", description="ループBGMの書き出し")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("render", help="曲を書き出す")
    p.add_argument("song")
    p.add_argument("--force", action="store_true", help="キャッシュを使わず全パートを作り直す")
    p.add_argument("--no-mp3", action="store_true", help="MP3 を書き出さない(ffmpeg が要らない)")
    p = sub.add_parser("fetch", help="音源をダウンロードする")
    p.add_argument("instruments", nargs="*")
    p.add_argument("--verify", action="store_true", help="取得済みのファイルもハッシュを確かめる")
    p = sub.add_parser("status", help="足りない音源を数える")
    p.add_argument("instruments", nargs="*")
    p = sub.add_parser("listen", help="ローカルの試聴画面を起動する")
    p.add_argument("song", nargs="?", default="proto_test", help="曲ID、曲フォルダー、または song.json")
    p.add_argument("--port", type=int, default=8765, choices=range(1, 65536), metavar="1-65535")
    p = sub.add_parser("new", help="曲の型から設計図の雛形を作る")
    p.add_argument("song", help="曲ID（英小文字・数字・_）")
    p.add_argument("--style", required=True, help="曲の型（templates/<型>.json）")
    args = parser.parse_args(argv)

    if args.command == "new":
        from .templates import NewSongError, new_song

        try:
            new_song(args.song, args.style)
        except NewSongError as e:
            print(e, file=sys.stderr)
            return 1
        print(f"作成しました: songs/{args.song}/song.json（型: {args.style}）")
        return 0

    if args.command == "listen":
        from .listen import serve
        from .render import SongError, load_song

        try:
            folder, song = load_song(args.song)
        except (SongError, OSError, ValueError) as e:
            print(f"試聴する曲を読み込めません: {e}", file=sys.stderr)
            return 1
        audio = folder / f"{song['id']}.wav"
        if not audio.is_file():
            print(f"試聴音源がありません: {audio}。先に bgm render で曲を書き出してください。", file=sys.stderr)
            return 1
        try:
            serve(audio, args.port)
        except (OSError, ValueError) as e:
            print(f"試聴画面を起動できません: {e}", file=sys.stderr)
            return 1
        return 0

    if args.command == "render":
        from .render import SongError, render_song

        try:
            render_song(args.song, force=args.force, mp3=not args.no_mp3)
        except (SongError, OSError) as e:
            print(f"エラー: {e}", file=sys.stderr)
            return 1
        return 0
    from . import fetch

    if args.command == "fetch":
        return 0 if fetch.fetch(args.instruments or None, verify=args.verify) else 1
    missing, files = fetch.status(args.instruments or None)
    print(f"音源: {len(files) - len(missing)}/{len(files)} ファイル取得済み"
          f"(残り {sum(f['size'] for f in missing) / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
