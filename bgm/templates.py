"""曲の型 (templates/<型>.json) の読み込み・検査と、`bgm new` による設計図の雛形作成。

形式と動作は docs/design/phase1-templates.md の記録どおり。
"""

import json
import re
import tempfile
from pathlib import Path

from .paths import ROOT, SONGS
from .profiles import PROFILES

TEMPLATES = ROOT / "templates"
TEMPLATE_KEYS = ("name", "ja", "tempo_range", "song")
SONG_FORBIDDEN_KEYS = ("id", "style", "usage", "title", "scene")
SONG_ID_RE = re.compile(r"[a-z0-9_]+")


class TemplateError(Exception):
    """テンプレートファイルが記録の形式に合わない。"""


class NewSongError(Exception):
    """`bgm new` が何も書かずに断った。メッセージはそのまま標準エラーに出す。"""


def list_styles(templates_dir=None):
    """使える型の名前（templates/*.json のファイル名の語幹）を並べ替えて返す。"""
    d = Path(templates_dir) if templates_dir is not None else TEMPLATES
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.json") if p.is_file())


def _kind(value):
    if isinstance(value, bool):
        return "真偽値"
    if isinstance(value, (int, float)):
        return "数値"
    if isinstance(value, str):
        return "文字列"
    if isinstance(value, list):
        return "配列"
    if isinstance(value, dict):
        return "オブジェクト"
    if value is None:
        return "null"
    return type(value).__name__


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_template(data, stem):
    """読み込んだテンプレートを検査する。違反は日本語の TemplateError。"""
    if not isinstance(data, dict):
        raise TemplateError(f"中身は {{\"name\": ..., \"ja\": ..., \"tempo_range\": ..., \"song\": ...}} の形の"
                            f"オブジェクトにしてください（いまは{_kind(data)}です）")
    unknown = [k for k in data if k not in TEMPLATE_KEYS]
    if unknown:
        raise TemplateError(f"知らないキーがあります: {', '.join(unknown)}（使えるキー: {' / '.join(TEMPLATE_KEYS)}）")
    missing = [k for k in TEMPLATE_KEYS if k not in data]
    if missing:
        raise TemplateError(f"{', '.join(missing)} がありません")
    if data["name"] != stem:
        actual = json.dumps(data["name"], ensure_ascii=False)
        raise TemplateError(f"name はファイル名と同じ \"{stem}\" にしてください（いまは {actual} です）")
    ja = data["ja"]
    if not isinstance(ja, str) or not ja.strip():
        raise TemplateError(f"ja は空でない文字列にしてください（いまは{_kind(ja)}です）")
    tr = data["tempo_range"]
    if not (isinstance(tr, list) and len(tr) == 2 and all(_is_int(v) for v in tr)):
        raise TemplateError(f"tempo_range は整数2つの [最小, 最大] にしてください（いまは {json.dumps(tr, ensure_ascii=False)} です）")
    if tr[0] > tr[1]:
        raise TemplateError(f"tempo_range の最小 {tr[0]} が最大 {tr[1]} より大きくなっています")
    song = data["song"]
    if not isinstance(song, dict):
        raise TemplateError(f"song はオブジェクトにしてください（いまは{_kind(song)}です）")
    forbidden = [k for k in SONG_FORBIDDEN_KEYS if k in song]
    if forbidden:
        raise TemplateError(f"song に {', '.join(forbidden)} を書かないでください（id と style は bgm new が加えます）")
    tempo = song.get("tempo")
    if not _is_number(tempo):
        raise TemplateError(f"song.tempo は数値にしてください（いまは{_kind(tempo)}です）")
    if not tr[0] <= tempo <= tr[1]:
        raise TemplateError(f"song.tempo {tempo} が tempo_range {tr[0]}–{tr[1]} の外にあります")


def load_template(style, templates_dir=None):
    """templates/<style>.json を読み、検査した内容を返す。"""
    d = Path(templates_dir) if templates_dir is not None else TEMPLATES
    path = d / f"{style}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise TemplateError(f"JSON の書式エラー: {e}") from e
    except UnicodeDecodeError as e:
        raise TemplateError(f"UTF-8 として読めません: {e}") from e
    validate_template(data, style)
    return data


def song_text(song_id, style, template, usage):
    """`bgm new` が書く song.json の中身（id, style, usage, テンプレートの song の順）。"""
    song = {"id": song_id, "style": style, "usage": usage, **template["song"]}
    return json.dumps(song, ensure_ascii=False, indent=2) + "\n"


def _check_song(text):
    """書き出す前に、一時フォルダーに置いた雛形を load_song で検査する。"""
    from .render import SongError, load_song

    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "song.json"
        f.write_bytes(text.encode("utf-8"))
        try:
            load_song(str(f))
        except (SongError, ValueError) as e:
            raise TemplateError(f"雛形が設計図として読めません: {e}") from e


def new_song(song_id, style, usage, *, templates_dir=None, songs_dir=None):
    """songs/<song_id>/song.json を曲の型から作り、そのパスを返す。断るときは何も書かず NewSongError。"""
    songs = Path(songs_dir) if songs_dir is not None else SONGS
    if not SONG_ID_RE.fullmatch(song_id):
        raise NewSongError(f"曲IDは英小文字・数字・_ だけで書いてください: {song_id}")
    folder = songs / song_id
    if folder.exists() or folder.is_symlink():
        raise NewSongError(f"曲フォルダ songs/{song_id} はすでにあります。別の曲IDにしてください")
    if usage not in PROFILES:
        raise NewSongError(f"用途は video / game / trpg のどれかにしてください: {usage}")
    styles = list_styles(templates_dir)
    if style not in styles:
        raise NewSongError(f"曲の型 {style} はありません（使える型: {' / '.join(styles)}）")
    try:
        template = load_template(style, templates_dir)
        text = song_text(song_id, style, template, usage)
        _check_song(text)
    except TemplateError as e:
        raise NewSongError(f"曲の型 {style} のファイルが壊れています: {e}") from e
    try:
        folder.mkdir(parents=True, exist_ok=False)
    except FileExistsError as e:
        raise NewSongError(f"曲フォルダ songs/{song_id} はすでにあります。別の曲IDにしてください") from e
    path = folder / "song.json"
    try:
        path.write_bytes(text.encode("utf-8"))
    except OSError:
        path.unlink(missing_ok=True)
        folder.rmdir()
        raise
    return path
