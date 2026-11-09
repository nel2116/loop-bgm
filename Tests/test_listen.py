"""試聴画面の配信範囲を確認する。"""

import json
from threading import Thread
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from bgm.listen import make_server


def test_listen_serves_only_page_and_selected_audio(tmp_path):
    audio = tmp_path / "test.wav"
    audio.write_bytes(b"RIFF-test-audio")
    (tmp_path / "private.txt").write_text("private", encoding="utf-8")
    with make_server(audio, port=0) as server:
        thread = Thread(target=server.serve_forever)
        thread.start()
        try:
            assert server.server_address[0] == "127.0.0.1"
            base = f"http://127.0.0.1:{server.server_port}"
            with urlopen(base) as response:
                page = response.read().decode("utf-8")
                assert "source.loop=true" in page
                assert "issues/3" not in page
                assert "フェーズ0" not in page
                assert "test.wav" in page
            with urlopen(base + "/audio.wav") as response:
                assert response.headers["Content-Type"] == "audio/wav"
                assert response.read() == audio.read_bytes()
            for path in ("/private.txt", "/../private.txt", "/%2e%2e/private.txt", "/song.json", "/.git/config"):
                with pytest.raises(HTTPError) as error:
                    urlopen(base + path)
                assert error.value.code == 404
        finally:
            server.shutdown()
            thread.join()


def test_listen_missing_or_directory(tmp_path):
    with pytest.raises(FileNotFoundError):
        make_server(tmp_path / 'missing.wav', port=0)
    with pytest.raises(ValueError):
        make_server(tmp_path, port=0)


def test_listen_escapes_filename(tmp_path):
    audio = tmp_path / 'a&b.wav'
    audio.write_bytes(b'audio')
    with make_server(audio, port=0) as server:
        thread = Thread(target=server.serve_forever)
        thread.start()
        try:
            with urlopen(f'http://127.0.0.1:{server.server_port}') as response:
                assert 'a&amp;b.wav' in response.read().decode('utf-8')
            audio.unlink()
            with pytest.raises(HTTPError) as error:
                urlopen(f'http://127.0.0.1:{server.server_port}/audio.wav')
            assert error.value.code == 404
        finally:
            server.shutdown()
            thread.join()


@pytest.mark.parametrize('reference', ['song', 'folder', 'json'])
@pytest.mark.parametrize('song_id', [None, 'alternate'])
def test_listen_cli_selects_rendered_audio(tmp_path, monkeypatch, reference, song_id):
    from bgm import __main__, listen, paths

    folder = tmp_path / 'example'
    folder.mkdir()
    song = {'tempo': 120, 'bars': 1, 'parts': []}
    if song_id is not None:
        song['id'] = song_id
    (folder / 'song.json').write_text(json.dumps(song), encoding='utf-8')
    (folder / 'example.wav').write_bytes(b'old audio')
    audio = folder / f'{song_id or folder.name}.wav'
    audio.write_bytes(b'audio')
    monkeypatch.setattr(paths, 'SONGS', tmp_path)
    monkeypatch.setattr('bgm.render.SONGS', tmp_path)
    calls = []
    monkeypatch.setattr(listen, 'serve', lambda audio, port: calls.append((audio, port)))
    ref = {'song': 'example', 'folder': str(folder), 'json': str(folder / 'song.json')}[reference]
    assert __main__.main(['listen', ref, '--port', '9876']) == 0
    assert calls == [(audio, 9876)]


def test_listen_cli_errors(tmp_path, monkeypatch, capsys):
    from bgm import __main__, listen

    monkeypatch.setattr('bgm.render.SONGS', tmp_path)
    assert __main__.main(['listen']) == 1
    assert '曲ファイルがありません' in capsys.readouterr().err
    folder = tmp_path / 'proto_test'
    folder.mkdir()
    design = folder / 'song.json'
    design.write_text('{', encoding='utf-8')
    assert __main__.main(['listen']) == 1
    assert '書式エラー' in capsys.readouterr().err
    design.write_text(json.dumps({'tempo': 120, 'bars': 1, 'parts': []}), encoding='utf-8')
    assert __main__.main(['listen']) == 1
    assert '試聴音源がありません' in capsys.readouterr().err
    (folder / 'proto_test.wav').write_bytes(b'audio')

    def fail(*args):
        raise OSError('port occupied')

    monkeypatch.setattr(listen, 'serve', fail)
    assert __main__.main(['listen']) == 1
    assert '試聴画面を起動できません' in capsys.readouterr().err
    for port in ('0', '65536', '-1'):
        with pytest.raises(SystemExit) as error:
            __main__.main(['listen', '--port', port])
        assert error.value.code == 2
