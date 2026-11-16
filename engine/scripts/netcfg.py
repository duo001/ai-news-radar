"""网络出口配置：代理支持（v0.17）。

面板填入代理地址后，全部外网请求（RSS 采集、结构化采集器、信源发现、机翻）
统一走该代理。配置文件 data/sources/proxy.json：

    {"enabled": true, "url": "http://127.0.0.1:7890", "no_proxy": ""}

设计取舍：
1. 只支持 http/https 代理。socks5 需要 PySocks，标准库不支持，环境也不保证装了，
   所以在保存时明确拒绝 socks:// 并给出提示，避免用户以为生效了其实走直连。
2. 优先级：本文件 enabled=true 时用文件里的 url；否则回退标准环境变量
   HTTP_PROXY/HTTPS_PROXY（urllib 默认行为），这样既尊重用户的系统配置，
   又能让面板开关直接生效。
3. 只改出口，不改任何采集逻辑：所有模块用 `opener()` 拿同一个 opener。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROXY_CONF = ROOT / "data" / "sources" / "proxy.json"

DEFAULT = {"enabled": False, "url": "", "no_proxy": ""}

_cached_key = None
_cached_opener = None


def load_proxy() -> dict:
    """读代理配置；文件缺失或损坏时返回默认（直连），不抛错。"""
    try:
        data = json.loads(PROXY_CONF.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(DEFAULT)
    if not isinstance(data, dict):
        return dict(DEFAULT)
    out = dict(DEFAULT)
    out["enabled"] = bool(data.get("enabled"))
    out["url"] = str(data.get("url") or "").strip()
    out["no_proxy"] = str(data.get("no_proxy") or "").strip()
    return out


def validate_url(url: str) -> str:
    """校验代理地址，返回规范化后的 URL；不合法抛 ValueError。"""
    url = (url or "").strip()
    if not url:
        raise ValueError("代理地址不能为空")
    if url.lower().startswith("socks"):
        raise ValueError("暂不支持 socks 代理（标准库无 socks 支持），请用 http:// 或 https:// 代理地址，"
                         "如 http://127.0.0.1:7890")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"代理地址需要以 http:// 或 https:// 开头（当前：{url[:40]}）")
    if not parsed.hostname:
        raise ValueError("代理地址缺少主机名，形如 http://127.0.0.1:7890")
    return url


def save_proxy(enabled: bool, url: str = "", no_proxy: str = "") -> dict:
    """保存代理配置（原子写）。enabled=True 时校验地址，enabled=False 允许留空。"""
    conf = {"enabled": bool(enabled), "url": "", "no_proxy": (no_proxy or "").strip()}
    if conf["enabled"]:
        conf["url"] = validate_url(url)
    elif url:
        # 关着也允许存地址，下次开启不用重填
        conf["url"] = str(url).strip()
    PROXY_CONF.parent.mkdir(parents=True, exist_ok=True)
    tmp = PROXY_CONF.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(conf, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(PROXY_CONF)
    global _cached_key, _cached_opener
    _cached_key = _cached_opener = None
    return conf


def opener() -> urllib.request.OpenerDirector | None:
    """返回带代理的 opener；直连时返回 None（调用方仍用 urlopen 默认行为）。

    结果按配置缓存，配置变更后 save_proxy 会清缓存。
    """
    global _cached_key, _cached_opener
    conf = load_proxy()
    key = (conf["enabled"], conf["url"])
    if key == _cached_key:
        return _cached_opener
    _cached_key = key
    if not (conf["enabled"] and conf["url"]):
        _cached_opener = None
        return None
    _cached_opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": conf["url"], "https": conf["url"]}))
    return _cached_opener


def _bypassed(url: str) -> bool:
    """no_proxy 命中的主机走直连（* 表示全部直连）。"""
    hosts = [h.strip().lower() for h in load_proxy()["no_proxy"].split(",") if h.strip()]
    if not hosts:
        return False
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    for h in hosts:
        if h == "*" or host == h or host.endswith("." + h.lstrip(".")):
            return True
    return False


def open_url(req, timeout=25):
    """统一出口：有代理走代理，无代理或命中 no_proxy 走默认。返回 response（用 with 关闭）。"""
    op = opener()
    if op is not None and not _bypassed(req.full_url):
        return op.open(req, timeout=timeout)
    return urllib.request.urlopen(req, timeout=timeout)


def describe() -> str:
    """一句话描述当前出口，用于 doctor 与面板展示。"""
    conf = load_proxy()
    if conf["enabled"] and conf["url"]:
        extra = f"（no_proxy: {conf['no_proxy']}）" if conf["no_proxy"] else ""
        return f"代理 {conf['url']}{extra}"
    return "直连（未启用代理）"


def test_proxy(url: str, test_url: str = "https://api.github.com/zen", timeout: int = 15) -> dict:
    """用给定代理试拉一个小请求，返回 {ok, via, elapsed_ms, error, sample}。

    不落盘、不影响当前配置，供面板「测试」按钮使用。
    """
    import time as _time
    try:
        target = validate_url(url)
    except ValueError as e:
        return {"ok": False, "via": "", "elapsed_ms": 0, "error": str(e), "sample": ""}
    t0 = _time.time()
    try:
        op = urllib.request.build_opener(urllib.request.ProxyHandler({"http": target, "https": target}))
        req = urllib.request.Request(test_url, headers={"User-Agent": "ai-news-radar/proxy-test"})
        with op.open(req, timeout=timeout) as resp:
            body = resp.read(200).decode("utf-8", errors="replace").strip()
        return {"ok": True, "via": target,
                "elapsed_ms": int((_time.time() - t0) * 1000),
                "error": "", "sample": body[:120]}
    except Exception as e:  # 代理测试要吞掉所有异常直接回报
        return {"ok": False, "via": target,
                "elapsed_ms": int((_time.time() - t0) * 1000),
                "error": f"{type(e).__name__}: {e}"[:300], "sample": ""}
