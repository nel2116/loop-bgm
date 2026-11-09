"""Command line: python -m bgm <command> ...

  python -m bgm render <song> [--force] [--no-mp3]   render songs/<song>/song.json (or a path)
  python -m bgm fetch [instrument ...] [--verify]    download the samples the kit uses
  python -m bgm status [instrument ...]              how many sample files are missing
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
    args = parser.parse_args(argv)

    if args.command == "render":
        from .render import SongError, render_song

        try:
            render_song(args.song, force=args.force, mp3=not args.no_mp3)
        except SongError as e:
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
