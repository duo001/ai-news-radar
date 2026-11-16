# tools/

## lightpanda（不入库）

轻量无头浏览器单二进制，`screenshot.py` 用它把 HTML 报告截成全页 PNG。

下载（约 74MB，linux-x64）：

```bash
# GitHub 直连慢时用 ghfast.top 镜像断点续传
curl -L -C - -o lightpanda \
  https://ghfast.top/https://github.com/lightpanda-io/browser/releases/download/v1.0.3/lightpanda-x86_64-unknown-linux-gnu
chmod +x lightpanda
./lightpanda version   # 验证：1.0.3
```

校验：官方 release 同名字节数 77,403,464。

## screenshot.py

```bash
python3 tools/screenshot.py                      # 截 data/ 下最新 report-*.html
python3 tools/screenshot.py data/sample-report.html
python3 tools/screenshot.py --port 8790          # 临时端口被占用时
```

输出 1920 宽全页 PNG 到 HTML 同目录、同名 `.png`。纯文本交付不需要本工具。
