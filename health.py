import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
import json

NAPCAT_WEBUI_PORT = 7860
NAPCAT_CONFIG = Path("/app/napcat/config")
QQ_DATA = Path("/app/.config/QQ")


def has_login_session() -> bool:
    if not QQ_DATA.exists():
        return False
    for child in QQ_DATA.iterdir():
        if (child / "nt_qq.db").exists():
            return True
    return False


def get_webui_token() -> str:
    path = NAPCAT_CONFIG / "webui.json"
    if path.exists():
        try:
            return json.loads(path.read_text()).get("token", "jmcomic")
        except Exception:
            pass
    return "jmcomic"


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

        if has_login_session():
            status_msg = '<p style="color:#27ae60;">✅ QQ 已登录</p><p>🤖 机器人正常运行中，在群内发送 <code>/jm &lt;本子ID&gt;</code> 即可使用</p>'
        else:
            token = get_webui_token()
            status_msg = f'''
            <div style="text-align:center;">
                <h3 style="color:#e67e22;">⏳ 等待扫码登录</h3>
                <p>访问下方 WebUI → 点击 <strong>QRCode</strong> → 手机 QQ 扫码</p>
                <p style="font-size:12px;color:#999;">WebUI Token: <code style="background:#eee;padding:2px 6px;border-radius:4px;">{token}</code></p>
            </div>
            '''

        html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>JMComic QQ Bot</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  body {{ font-family: sans-serif; max-width:600px; margin:50px auto; padding:0 20px; text-align:center; }}
  h1 {{ color:#2c3e50; }}
  .card {{ background:#f9f9f9; border-radius:12px; padding:30px; box-shadow:0 2px 8px rgba(0,0,0,0.1); }}
  code {{ background:#eee; padding:2px 6px; border-radius:4px; }}
  .btn {{ display:inline-block; background:#3498db; color:#fff; padding:10px 24px; border-radius:8px; text-decoration:none; margin:10px 0; }}
</style>
</head><body>
<div class="card">
<h1>JMComic QQ Bot</h1>
{status_msg}
<hr style="margin:20px 0;border:none;border-top:1px solid #eee;">
<p style="font-size:14px;">
  基于 NapCatQQ · 部署于 Hugging Face Spaces
</p>
</div></body></html>'''
        self.wfile.write(html.encode("utf-8"))

    def log_message(self, format, *args):
        pass


def serve(port: int = 7860):
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"[health] Status page at http://0.0.0.0:{port}")
    server.serve_forever()


if __name__ == "__main__":
    serve()
