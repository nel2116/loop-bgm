"""試聴確認用の読み取り専用サーバー。"""

from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PAGE = """<!doctype html>
<html lang="ja"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>BGMの試聴 — loop-bgm</title>
<style>
body{font:18px/1.7 system-ui,sans-serif;background:#f4f6fa;color:#172033;margin:0;padding:24px}
main{max-width:640px;margin:auto}button,a{touch-action:manipulation}
button{font:inherit;padding:14px 22px;margin:6px;border:0;border-radius:12px;background:#234bbb;color:white}
button:disabled{opacity:.5}section{background:white;padding:20px;border-radius:16px;margin:20px 0}
a{color:#234bbb}h1{font-size:26px}#status{min-height:2em}
</style>
<main><h1>BGMの試聴</h1><p>音源: __AUDIO_NAME__</p>
<section><button id="play">ループ再生</button><button id="stop" disabled>停止</button>
<p id="status" role="status" aria-live="polite">再生を押すと音源を読み込みます。</p>
<p>画面を開いたまま、数周聴いてください。音は端末の音量で調整できます。</p></section>
<section><h2>確認すること</h2><ul>
<li>最後から最初に戻るときに、プツッという音や途切れがないか</li>
<li>メロディと伴奏の音量が自然か</li>
<li>耳につく音や違和感がないか</li></ul>
</section>
<p><a href="/audio.wav" download="__AUDIO_NAME__">WAVを保存</a></p>
</main><script>
let context, buffer, source;
const play=document.querySelector('#play'),stop=document.querySelector('#stop'),status=document.querySelector('#status');
play.onclick=async()=>{
  play.disabled=true;
  try{
    context ??= new (window.AudioContext || window.webkitAudioContext)();
    await context.resume();
    if(!buffer){
      status.textContent='音源を読み込んでいます…';
      const response=await fetch('/audio.wav',{cache:'no-store'});
      if(!response.ok) throw new Error();
      buffer=await context.decodeAudioData(await response.arrayBuffer());
    }
    source=context.createBufferSource(); source.buffer=buffer; source.loop=true;
    source.connect(context.destination); source.start();
    stop.disabled=false; status.textContent='ループ再生中';
  }catch{
    play.disabled=false;
    status.textContent='再生できませんでした。音源と接続を確認してください。再書き出し後は画面を再読み込みしてください。';
  }
};
stop.onclick=()=>{source?.stop();source?.disconnect();source=null;stop.disabled=true;play.disabled=false;
  status.textContent='停止しました。';};
</script></html>"""


def make_server(audio: Path, port=8765):
    """公開するパスを画面と指定音源だけに限定する。"""
    audio = audio.resolve(strict=True)
    if not audio.is_file():
        raise ValueError("試聴音源のファイルを指定してください")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/":
                body = PAGE.replace("__AUDIO_NAME__", escape(audio.name, quote=True)).encode("utf-8")
                mime = "text/html; charset=utf-8"
            elif self.path == "/audio.wav":
                try:
                    body = audio.read_bytes()
                except OSError:
                    self.send_error(404)
                    return
                mime = "audio/wav"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def serve(audio, port=8765):
    with make_server(Path(audio), port) as server:
        print(f"試聴画面: http://127.0.0.1:{server.server_port}（停止: Ctrl+C）", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
