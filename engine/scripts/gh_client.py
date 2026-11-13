# -*- coding: utf-8 -*-
"""GitHub 数据抓取层（ai-git-radar）。

两条通路，自动降级：
  1. 有 token  → REST API（search/repositories、repo 详情、readme）
  2. 无 token  → github.com 网页 + raw.githubusercontent.com，零额度

数据源：
  A. github.com/trending          官方涨星口径（今日/本周各涨多少星）
  B. Search API                   按类目 topic / 关键词、created 时间捞候选
  C. 仓库详情 + README            供 detectors 做静态信号分析

只依赖 requests + 标准库；所有网络结果落 data/cache，调试不重复请求。
"""
import base64
import json
import os
import pathlib
import re
import time

import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data" / "cache"
CONFIG = ROOT / "config.json"

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
UA = "ai-git-radar/0.1 (+https://github.com/local)"
PAGE_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# 缓存有效期（秒）。trending 变化快给短 TTL，仓库元数据/README 给长 TTL。
TTL = {"trending": 3 * 3600, "search": 6 * 3600, "repo": 24 * 3600,
       "readme": 24 * 3600}


class RateLimited(Exception):
    """API 额度用完，上层应降级到网页/raw 通路。"""


# core(repo/readme) 额度耗尽后的进程级降级开关：一旦置位，后续 repo/readme
# 请求直接走网页/raw，不再把时间浪费在注定 403 的 API 重试上。
_core_exhausted = False


def _quota_remaining():
    """查 /rate_limit 的 core 剩余额度。失败返回 None（不阻断主流程）。"""
    try:
        r = requests.get(f"{API}/rate_limit", headers=_headers(get_token()), timeout=10)
        if r.status_code == 200:
            return r.json()["resources"]["core"]["remaining"]
    except Exception:
        pass
    return None


def preflight(min_remaining=30):
    """深度分析前调用：core 额度不足时提前切网页通路。返回剩余额度（未知为 None）。"""
    global _core_exhausted
    if get_token():
        return _quota_remaining()          # 有 token 额度充裕，不干预
    rem = _quota_remaining()
    if rem is not None and rem < min_remaining:
        _core_exhausted = True
    return rem


def core_exhausted():
    return _core_exhausted


def _mark_core_exhausted():
    global _core_exhausted
    if not get_token():          # token 用户额度按小时滚动，不做进程级置位
        _core_exhausted = True


# --------------------------------------------------------------- token

_token_cache = [""]
_token_source = [""]


def get_token():
    """四级发现：环境变量 → config.json → gh CLI 配置文件。找不到返回 ''（匿名通路）。"""
    if _token_cache[0] != "" or _token_source[0] == "checked":
        return _token_cache[0]
    for k in ("GH_TOKEN", "GITHUB_TOKEN", "GITHUB_PAT"):
        v = (os.environ.get(k) or "").strip()
        if v:
            _token_cache[0], _token_source[0] = v, f"环境变量 {k}"
            return v
    try:
        if CONFIG.exists():
            cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
            v = (cfg.get("gh_token") or "").strip()
            if v:
                _token_cache[0], _token_source[0] = v, "config.json"
                return v
    except Exception:
        pass
    # gh CLI 配置文件（只读文件，不执行 `gh auth token`——没登录时该命令会挂起）
    hosts = pathlib.Path.home() / ".config" / "gh" / "hosts.yml"
    try:
        if hosts.exists():
            m = re.search(r"oauth_token:\s*(\S+)", hosts.read_text(encoding="utf-8", errors="ignore"))
            if m and m.group(1).startswith(("gho_", "ghp_", "github_pat_")):
                _token_cache[0], _token_source[0] = m.group(1), "gh CLI 配置"
                return m.group(1)
    except Exception:
        pass
    _token_source[0] = "checked"
    return ""


def token_source():
    get_token()
    # "checked" 只是"已查找过且没找到"的内部哨兵，不展示给报告
    return _token_source[0] if _token_source[0] not in ("", "checked") else "匿名（网页/raw 通路）"


# --------------------------------------------------------------- 缓存

def _cache_path(kind, key):
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", key)[:120]
    d = CACHE_DIR / kind
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{safe}.json"


def cache_get(kind, key):
    p = _cache_path(kind, key)
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        if time.time() - d["_ts"] > TTL[kind]:
            return None
        return d["data"]
    except Exception:
        return None


def cache_put(kind, key, data):
    try:
        _cache_path(kind, key).write_text(
            json.dumps({"_ts": time.time(), "data": data}, ensure_ascii=False),
            encoding="utf-8")
    except Exception:
        pass


# --------------------------------------------------------------- HTTP

def _headers(token=None):
    h = {"Accept": "application/vnd.github+json", "User-Agent": UA,
         "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _get(url, token=None, params=None, timeout=20, retries=2):
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, headers=_headers(token), params=params, timeout=timeout)
            if r.status_code in (403, 429) and "rate limit" in r.text.lower():
                # 重试也不会恢复额度，立即抛出让上层降级（旧实现 sleep 重试 3 次，
                # 匿名 60 次/小时耗尽后每个请求白等十几秒）
                raise RateLimited(url)
            if r.status_code in (404, 451):
                return None
            r.raise_for_status()
            return r
        except RateLimited:
            raise
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"GET {url} 失败: {last}")


# --------------------------------------------------------------- A. trending

_NUM = re.compile(r"[\d,]+")


def _num(s):
    m = _NUM.search(s or "")
    return int(m.group(0).replace(",", "")) if m else 0


def fetch_trending(since="daily", use_cache=True):
    """解析 github.com/trending  HTML。零额度。

    已知改版坑：repo 链接在 h2 内、且 href 可能被 data-hydro-click 包裹，
    所以按 article.Box-row 切块后只在 h2 里取 owner/name。
    返回 0 条通常意味着 GitHub 改版，需检查页面结构（见 references/数据源与已知坑.md）。
    """
    ck = f"trending-{since}"
    if use_cache:
        hit = cache_get("trending", ck)
        if hit is not None:
            return hit
    r = requests.get(f"https://github.com/trending?since={since}",
                     headers={"User-Agent": PAGE_UA, "Accept": "text/html"}, timeout=45)
    r.raise_for_status()
    html = r.text
    out = []
    for art in re.findall(r'<article class="Box-row">(.*?)</article>', html, re.S):
        h2 = re.search(r"<h2[^>]*>(.*?)</h2>", art, re.S)
        if not h2:
            continue
        hm = re.search(r'href="/([^"/]+)/([^"/]+)"', h2.group(1))
        if not hm or hm.group(1) in ("sponsors", "login", "orgs", "topics"):
            continue
        owner, name = hm.group(1), hm.group(2)
        dm = re.search(r'<p class="col-9[^"]*">\s*(.*?)\s*</p>', art, re.S)
        desc = re.sub(r"<[^>]+>", "", dm.group(1)).strip() if dm else ""
        lm = re.search(r'itemprop="programmingLanguage">([^<]+)<', art)

        def count_of(kind):
            m = re.search(rf'/{kind}"[^>]*>(.*?)</a>', art, re.S)
            return _num(re.sub(r"<[^>]+>", "", m.group(1))) if m else 0

        gm = re.search(r"([\d,]+)\s+stars\s+(today|this week|this month)", art)
        out.append({
            "full_name": f"{owner}/{name}", "owner": owner, "name": name,
            "desc": desc, "lang": lm.group(1).strip() if lm else "",
            "stars": count_of("stargazers"), "forks": count_of("forks"),
            "gained": _num(gm.group(1)) if gm else 0,
            "since": since, "source": "trending",
        })
    cache_put("trending", ck, out)
    return out


# --------------------------------------------------------------- B. search

def _map_item(it, source):
    return {
        "full_name": it["full_name"], "owner": it["owner"]["login"],
        "name": it["name"], "desc": it.get("description") or "",
        "lang": it.get("language") or "",
        "stars": it.get("stargazers_count", 0), "forks": it.get("forks_count", 0),
        "gained": 0, "source": source,
        "created_at": it.get("created_at"), "pushed_at": it.get("pushed_at"),
        "topics": it.get("topics") or [], "archived": it.get("archived", False),
        "license": ((it.get("license") or {}).get("spdx_id") or ""),
        "open_issues": it.get("open_issues_count"), "size_kb": it.get("size"),
        "homepage": it.get("homepage") or "", "fork": it.get("fork", False),
    }


def search(q, per_page=20, use_cache=True):
    """通用 Search API。匿名额度 10 次/分钟，调用方需控制类目查询总数。"""
    key = f"q={q}|n={per_page}"
    if use_cache:
        hit = cache_get("search", key)
        if hit is not None:
            return hit
    token = get_token()
    r = _get(f"{API}/search/repositories", token,
             params={"q": q, "sort": "stars", "order": "desc", "per_page": per_page})
    if r is None:
        return []
    items = [_map_item(it, "search") for it in r.json().get("items", [])]
    cache_put("search", key, items)
    return items


# --------------------------------------------------------------- 详情 + README

def repo_detail(full_name, use_cache=True):
    """补评分/过滤字段。API 优先，失败降级网页抓取。"""
    if use_cache:
        hit = cache_get("repo", full_name)
        if hit is not None:
            return hit
    token = get_token()
    out = None
    if not _core_exhausted:
        try:
            r = _get(f"{API}/repos/{full_name}", token)
            if r is not None:
                d = r.json()
                out = {
                    "full_name": d["full_name"], "owner": d["owner"]["login"],
                    "name": d["name"], "desc": d.get("description") or "",
                    "lang": d.get("language") or "",
                    "stars": d.get("stargazers_count", 0), "forks": d.get("forks_count", 0),
                    "open_issues": d.get("open_issues_count", 0),
                    "license": ((d.get("license") or {}).get("spdx_id") or ""),
                    "topics": d.get("topics") or [],
                    "created_at": d.get("created_at"), "pushed_at": d.get("pushed_at"),
                    "size_kb": d.get("size", 0), "archived": d.get("archived", False),
                    "fork": d.get("fork", False), "homepage": d.get("homepage") or "",
                    "default_branch": d.get("default_branch", "main"),
                }
        except RateLimited:
            _mark_core_exhausted()
    if out is None:
        out = _scrape_repo_page(full_name)
    if out is None:
        out = _scrape_repo_page(full_name)
    if out:
        cache_put("repo", full_name, out)
    return out


def readme(full_name, max_chars=6000, use_cache=True):
    """README 前段，供 detectors 静态分析。API → raw → 网页，三级兜底。"""
    if use_cache:
        hit = cache_get("readme", full_name)
        if hit is not None:
            return hit[:max_chars]
    txt = ""
    token = get_token()
    if not _core_exhausted:
        try:
            r = _get(f"{API}/repos/{full_name}/readme", token)
            if r is not None:
                txt = base64.b64decode(r.json().get("content", "")).decode("utf-8", "ignore")
        except RateLimited:
            _mark_core_exhausted()
            txt = ""
    if not txt.strip():
        txt = raw_readme(full_name)
    if not txt.strip():
        page = _scrape_repo_page(full_name)
        txt = (page or {}).get("readme", "")
    txt = txt[:max_chars]
    if txt.strip():
        cache_put("readme", full_name, txt)
    return txt


def raw_readme(full_name, max_chars=6000):
    # 只试 4 个常见文件名，每个 10s 封顶；罕见命名交给网页兜底，避免单仓等满 6×25s
    for fn in ("README.md", "readme.md", "README.rst", "Readme.md"):
        try:
            r = requests.get(f"{RAW}/{full_name}/HEAD/{fn}",
                             headers={"User-Agent": UA}, timeout=10)
            if r.status_code == 200 and r.text.strip():
                return r.text[:max_chars]
        except Exception:
            continue
    return ""


# --------------------------------------------------------------- 网页兜底

_LIC_PATTERNS = [
    (r"\bAGPL[- ]?3", "AGPL-3.0"), (r"\bLGPL[- ]?3", "LGPL-3.0"),
    (r"\bGPL[- ]?3", "GPL-3.0"), (r"\bGPL[- ]?2", "GPL-2.0"),
    (r"Apache[- ]?(License)?[, ]*2", "Apache-2.0"), (r"\bMPL[- ]?2", "MPL-2.0"),
    (r"\bBSD[- ]?3", "BSD-3-Clause"), (r"\bBSD[- ]?2", "BSD-2-Clause"),
    (r"\bISC\b", "ISC"), (r"\bUnlicense\b", "Unlicense"), (r"\bMIT\b", "MIT"),
]


def _norm_license(text):
    for pat, spdx in _LIC_PATTERNS:
        if re.search(pat, text or "", re.I):
            return spdx
    return ""


_scrape_memo = {}


def _scrape_repo_page(full_name):
    """零额度兜底：抓 github.com/<owner>/<repo> 页面，解析 license + README + 星数。

    进程内记忆：repo_detail 与 readme 兜底对同一仓库只抓一次页面。
    """
    if full_name in _scrape_memo:
        return _scrape_memo[full_name]
    try:
        r = requests.get(f"https://github.com/{full_name}",
                         headers={"User-Agent": PAGE_UA, "Accept": "text/html"}, timeout=20)
        if r.status_code != 200:
            _scrape_memo[full_name] = None
            return None
        html = r.text
    except Exception:
        _scrape_memo[full_name] = None
        return None
    out = {"full_name": full_name, "topics": [], "size_kb": 0,
           "archived": "This repository has been archived" in html, "fork": False}
    m = re.search(r">\s*([A-Za-z0-9.\-+]{2,30})\s+license\s*<", html, re.I)
    out["license"] = _norm_license(m.group(1)) if m else ""
    out["stars"] = _scrape_stars(html)
    a = re.search(r'<article[^>]*class="[^"]*markdown-body[^"]*"[^>]*>(.*?)</article>',
                  html, re.S)
    if a:
        t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", a.group(1), flags=re.S | re.I)
        t = re.sub(r"<[^>]+>", " ", t)
        for a_, b_ in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">")):
            t = t.replace(a_, b_)
        out["readme"] = re.sub(r"[ \t]+", " ", t).strip()[:6000]
    else:
        out["readme"] = ""
    _scrape_memo[full_name] = out
    return out


def _parse_human_num(s):
    s = (s or "").strip().lower().replace(",", "")
    if not s:
        return 0
    mul = 1000 if s.endswith("k") else 1_000_000 if s.endswith("m") else 1
    try:
        return int(float(s.rstrip("km")) * mul)
    except ValueError:
        return 0


# 星数锚点按 GitHub 历代页面结构排列，命中任一即停；页面改版导致全失配时返回 0，
# 由 radar.py 的合并逻辑保证不会用 0 覆盖 search/trending 的真值。
_STAR_PATTERNS = [
    # 现代版：<span id="repo-stars-counter-star" title="210,237">210k</span>
    r'id="repo-stars-counter-star"[^>]*title="([\d,]+)"',
    r'id="repo-stars-counter-star"[^>]*>\s*([\d.,]+[kKmM]?)\s*<',
    # 次新：aria-label="210237 users starred this repository"
    r'aria-label="([\d,]+)\s+users? starred',
    # 旧版兜底：stargazers 链接内的数字（原实现，结构再变也可能仍有效）
    r'href="/[^"]+/stargazers"[^>]*>(.*?)</a>',
]


def _scrape_stars(html):
    for pat in _STAR_PATTERNS[:3]:
        m = re.search(pat, html, re.I | re.S)
        if m:
            n = _parse_human_num(m.group(1))
            if n:
                return n
    m = re.search(_STAR_PATTERNS[3], html, re.I | re.S)
    if m:
        n = _parse_human_num(re.sub(r"<[^>]+>", "", m.group(1)))
        if n:
            return n
    return 0
