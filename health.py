import os
import json
import base64
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

LAGRANGE_DIR = Path("/app/lagrange")
QR_FILE = LAGRANGE_DIR / "qr.png"
CONFIG_FILE = LAGRANGE_DIR / "config.json"


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

        login_status = ""
        qr_html = ""

        if QR_FILE.exists():
            with open(QR_FILE, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            qr_html = f'''
            <div style="text-align:center;">
                <h3 style="color:#e67e22;">⏳ 等待扫码登录</h3>
                <img src="data:image/png;base64,{b64}"
                     style="max-width:280px;border:2px solid #ddd;border-radius:8px;"/>
                <p style="color:#888;">请用手机 QQ 扫描上方二维码</p>
            </div>
            '''

        if CONFIG_FILE.exists():
            try:
                cfg = json.loads(CONFIG_FILE.read_text())
                uin = cfg.get("Account", {}).get("Uin", 0)
                if uin and uin != 0:
                    login_status = f'<p style="color:#27ae60;">✅ 已登录 QQ 账号: {uin}</p>'
            except Exception:
                pass

        if not qr_html and not login_status:
            status_msg = '<p style="color:#888;">⏳ 机器人启动中，请稍候……</p>'
        elif login_status:
            status_msg = login_status + '<p>🤖 机器人正常运行中，在群内发送 <code>/jm &lt;本子ID&gt;</code> 即可使用</p>'
        else:
            status_msg = qr_html

        html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>JMComic QQ Bot</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  body {{ font-family: sans-serif; max-width:600px; margin:50px auto; padding:0 20px; text-align:center; }}
  h1 {{ color:#2c3e50; }}
  .card {{ background:#f9f9f9; border-radius:12px; padding:30px; box-shadow:0 2px 8px rgba(0,0,0,0.1); }}
  code {{ background:#eee; padding:2px 6px; border-radius:4px; }}
</style>
</head><body>
<div class="card">
<h1>JMComic QQ Bot</h1>
{status_msg}
<hr style="margin:20px 0;border:none;border-top:1px solid #eee;">
<p style="color:#aaa;font-size:14px;">
  部署于 Hugging Face Spaces
  <br>项目: <a href="https://github.com/hect0x7/JMComic-Crawler-Python">hect0x7/JMComic-Crawler-Python</a>
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
