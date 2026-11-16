# -*- coding: utf-8 -*-
"""用 lightpanda 无头浏览器把 HTML 报告截成全页 PNG（零 JS 依赖、轻量）。

用法：
    python3 tools/screenshot.py                      # 截 data/ 下最新 report-*.html
    python3 tools/screenshot.py data/report-xxx.html # 指定文件
    python3 tools/screenshot.py --port 8790          # 指定临时服务端口

前置：tools/lightpanda 可执行（从 lightpanda-io/browser release 下载的单二进制）。
截图为 1920 宽全页长图，输出到 HTML 同目录、同名 .png。
"""
import base64
import http.server
import json
import socketserver
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIGHTPANDA = ROOT / "tools" / "lightpanda"


def _latest_html() -> Path:
    files = sorted((ROOT / "data").glob("report-*.html"))
    if not files:
        sys.exit("data/ 下没有 report-*.html，先跑一次 radar.py run")
    return files[-1]


def _serve(directory: Path, port: int):
    handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(
        *a, directory=str(directory), **kw)
    httpd = socketserver.TCPServer(("127.0.0.1", port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def shoot(html_path: Path, port: int = 8777) -> Path:
    if not LIGHTPANDA.exists():
        sys.exit(f"找不到 lightpanda：{LIGHTPANDA}\n"
                 "下载 https://github.com/lightpanda-io/browser 的 linux 二进制放到该路径。")
    httpd = _serve(html_path.parent, port)
    url = f"http://127.0.0.1:{port}/{html_path.name}"
    try:
        out = subprocess.run(
            [str(LIGHTPANDA), "fetch", url, "--dump", "png", "--json",
             "--wait-ms", "2500"],
            capture_output=True, text=True, timeout=120,
        )
        if out.returncode != 0:
            sys.exit(f"lightpanda 失败（{out.returncode}）：{out.stderr[:300]}")
        payload = json.loads(out.stdout)
        if payload.get("error"):
            sys.exit(f"页面错误：{payload['error']}")
        img_b64 = payload.get("content")
        if not img_b64:
            sys.exit("lightpanda 未返回图像内容")
        png_path = html_path.with_suffix(".png")
        png_path.write_bytes(base64.b64decode(img_b64))
        return png_path
    finally:
        httpd.shutdown()


def main():
    args = [a for a in sys.argv[1:]]
    port = 8777
    if "--port" in args:
        i = args.index("--port")
        port = int(args[i + 1])
        del args[i:i + 2]
    html_path = Path(args[0]).resolve() if args else _latest_html()
    if not html_path.exists():
        sys.exit(f"文件不存在：{html_path}")
    png = shoot(html_path, port)
    print(f"截图完成 → {png}（{png.stat().st_size / 1024:.0f} KB）")


if __name__ == "__main__":
    main()
