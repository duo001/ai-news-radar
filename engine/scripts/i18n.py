# -*- coding: utf-8 -*-
"""中文翻译库（本地持久化，离线可用，已翻译内容永不覆盖）。

为什么这样设计：脚本本身不调翻译 API（v0.1 只做静态分析、不要额外密钥），
翻译由 Agent/人完成。流程见 radar.py translate 子命令：

  1. run 跑完 → `translate --todo` 把英文简介抽成待译清单 data/todo_translate.json
  2. Agent 逐条填 zh 字段（可只填部分）
  3. `translate --apply` 合并进 data/translations.json，已有的翻译不被覆盖
  4. 重新 render，报告里英文简介自动变成「中文（英文原文）」

key 用 full_name 小写（owner/repo），同一项目跨天复用，翻译库越用越全。
"""
import json
import pathlib
import re

DATA = pathlib.Path(__file__).resolve().parent.parent / "data"
STORE = DATA / "translations.json"
TODO = DATA / "todo_translate.json"

# 资讯条目按文章 link 建 key（不是仓库名），用独立文件，与 GitHub 仓库翻译互不干扰。
NEWS_STORE = DATA / "news_translations.json"
NEWS_TODO = DATA / "todo_news_translate.json"

_CJK_RE = re.compile(r"[一-鿿]")


def has_cjk(text):
    """文本里是否已含中文字符（含中文的简介直接当已翻译，不进待译清单）。"""
    return bool(text and _CJK_RE.search(text))


def load_store():
    """读翻译库，结构 {full_name_lower: {"zh": "...", "source": "..."}}。"""
    if not STORE.exists():
        return {}
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_store(store):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(store, ensure_ascii=False, indent=2, sort_keys=True),
                     encoding="utf-8")


def lookup(full_name):
    """返回该项目的中文简介，没有则 None。"""
    item = load_store().get((full_name or "").lower())
    return item.get("zh") if item else None


def build_todo(results):
    """从 run 结果抽出待译条目：英文简介且翻译库里没有的。

    已是中文的简介、空简介跳过。返回可直接编辑的结构：
    {"items": [{"key","repo","source","zh":""}], "updated_at": ...}
    """
    from datetime import datetime
    store = load_store()
    items = []
    seen = set()
    for r in results:
        repo = r["repo"]
        key = repo["full_name"].lower()
        if key in seen or key in store:
            continue
        seen.add(key)
        source = (repo.get("desc") or "").strip()
        if not source or has_cjk(source):
            continue
        items.append({"key": key, "repo": repo["full_name"],
                      "source": source, "zh": ""})
    return {"updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "items": items}


def write_todo(todo):
    TODO.parent.mkdir(parents=True, exist_ok=True)
    TODO.write_text(json.dumps(todo, ensure_ascii=False, indent=2), encoding="utf-8")
    return TODO


def apply_todo(path=None):
    """把填好 zh 的待译清单合并进翻译库。

    - zh 为空的条目跳过（没翻就保留英文，不阻塞）
    - 库里已有的 key 不覆盖（精译优先，防止 --apply 冲掉人工润色）
    返回 (新增条数, 跳过条数)。
    """
    p = pathlib.Path(path) if path else TODO
    if not p.exists():
        raise FileNotFoundError(f"待译清单不存在：{p}（先跑 translate --todo）")
    todo = json.loads(p.read_text(encoding="utf-8"))
    store = load_store()
    added, skipped = 0, 0
    for it in todo.get("items", []):
        key, zh = it.get("key", "").lower(), (it.get("zh") or "").strip()
        if not key or not zh:
            skipped += 1
            continue
        if key in store:
            skipped += 1
            continue
        store[key] = {"zh": zh, "source": it.get("source", "")}
        added += 1
    save_store(store)
    return added, skipped


def coverage(results):
    """统计当前结果里英文简介的翻译覆盖率，返回 (已译, 待译, 已是中文)。"""
    store = load_store()
    done, pending, native = 0, 0, 0
    for r in results:
        key = r["repo"]["full_name"].lower()
        desc = (r["repo"].get("desc") or "").strip()
        if has_cjk(desc):
            native += 1
        elif key in store:
            done += 1
        elif desc:
            pending += 1
    return done, pending, native


# ============================================================
# 资讯翻译（RSS/Atom 条目，按文章 link 建 key，独立存储）
# ============================================================

def load_news_store():
    """读资讯翻译库，结构 {link: {"zh_title","zh_summary","source_title",...}}。"""
    if not NEWS_STORE.exists():
        return {}
    try:
        return json.loads(NEWS_STORE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_news_store(store):
    NEWS_STORE.parent.mkdir(parents=True, exist_ok=True)
    NEWS_STORE.write_text(json.dumps(store, ensure_ascii=False, indent=2, sort_keys=True),
                          encoding="utf-8")


def news_lookup(link):
    """返回该资讯条目的翻译 dict（zh_title/zh_summary），没有则 None。"""
    return load_news_store().get(link)


def build_news_todo(entries):
    """从资讯条目抽待译清单：标题为英文且翻译库里没有的。

    标题是必译字段；摘要（summary）作为可选字段一并放进清单。
    标题已含中文（少数中文源）或翻译库已有的跳过。返回与仓库待译同构的结构。
    """
    from datetime import datetime
    store = load_news_store()
    items, seen = [], set()
    for e in entries:
        link = e.get("link", "")
        title = (e.get("title") or "").strip()
        if not link or link in seen:
            continue
        seen.add(link)
        summary = (e.get("summary") or "").strip()
        existing = store.get(link)
        if existing:
            # 已有译文：只有「标题译了、摘要没译」才补一条摘要补译任务，
            # 否则会出现标题全译但摘要长期空缺（曾漏掉 30 条）。
            if not (existing.get("zh_title") and not existing.get("zh_summary") and summary):
                continue
            items.append({
                "key": link, "link": link,
                "source_title": existing.get("zh_title") or title,
                "source_summary": summary[:400],
                "source_name": e.get("source_name", ""),
                "zh_title": existing.get("zh_title", ""),
                "zh_summary": "",
                "only_summary": True,
            })
            continue
        if not title or has_cjk(title):
            continue
        items.append({
            "key": link,
            "link": link,
            "source_title": title,
            "source_summary": (e.get("summary") or "")[:400],
            "source_name": e.get("source_name", ""),
            "zh_title": "",
            "zh_summary": "",
        })
    return {"updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "items": items}


def write_news_todo(todo):
    NEWS_TODO.parent.mkdir(parents=True, exist_ok=True)
    NEWS_TODO.write_text(json.dumps(todo, ensure_ascii=False, indent=2), encoding="utf-8")
    return NEWS_TODO


def apply_news_todo(path=None):
    """把填好的资讯待译合并进资讯翻译库。

    - zh_title 为空跳过（标题必译，没翻不入库）；zh_summary 可空
    - 已存在的 link 不覆盖（精译优先）
    返回 (新增条数, 跳过条数)。
    """
    p = pathlib.Path(path) if path else NEWS_TODO
    if not p.exists():
        raise FileNotFoundError(f"资讯待译清单不存在：{p}（先跑 translate --news --todo）")
    todo = json.loads(p.read_text(encoding="utf-8"))
    store = load_news_store()
    added, skipped = 0, 0
    for it in todo.get("items", []):
        link = it.get("key", "") or it.get("link", "")
        zh_title = (it.get("zh_title") or "").strip()
        if not link or not zh_title:
            skipped += 1
            continue
        if link in store:
            skipped += 1
            continue
        store[link] = {
            "zh_title": zh_title,
            "zh_summary": (it.get("zh_summary") or "").strip(),
            "source_title": it.get("source_title", ""),
            "source_summary": it.get("source_summary", ""),
        }
        added += 1
    save_news_store(store)
    return added, skipped


def news_coverage(entries):
    """统计资讯标题翻译覆盖率，返回 (已译, 待译, 原文即中文)。"""
    store = load_news_store()
    done, pending, native = 0, 0, 0
    for e in entries:
        link = e.get("link", "")
        title = (e.get("title") or "").strip()
        if not title:
            continue
        if has_cjk(title):
            native += 1
        elif link in store and store[link].get("zh_title"):
            done += 1
        else:
            pending += 1
    return done, pending, native


# ============================================================
# 资讯自动机翻（免费通道，见 mt.py）
# ============================================================

def auto_translate_news(entries, log=None, limit=None, provider=None):
    """把待译的英文资讯标题+摘要走免费机翻写入资讯翻译库。

    参数
    ----
    entries : 资讯条目列表（含 link/title/summary）
    limit   : 本次最多处理多少条（None = 全部）
    provider: 指定翻译通道（None = 自动降级链）

    返回统计 dict：{considered, translated, failed, skipped, provider}
    """
    import mt as mt_mod
    import glossary

    store = load_news_store()
    todo = build_news_todo(entries)["items"]
    if limit:
        todo = todo[:limit]

    stat = {"considered": len(todo), "translated": 0, "failed": 0,
            "skipped": 0, "provider": "none"}
    if not todo:
        return stat

    # 收集待译文本：每条先标题、再摘要（摘要截断，省额度）
    texts, slots = [], []
    for it in todo:
        title = (it.get("source_title") or "").strip()
        summary = (it.get("source_summary") or "").strip()[:300]
        if it.get("only_summary"):
            if not summary:
                stat["skipped"] += 1
                continue
            slots.append({"link": it["link"], "title_idx": None,
                          "summary_idx": len(texts), "title": title,
                          "summary_src": summary, "only_summary": True})
            texts.append(summary)
            continue
        if not title:
            stat["skipped"] += 1
            continue
        slots.append({"link": it["link"], "title_idx": len(texts),
                      "summary_idx": None, "title": title,
                      "summary_src": summary})
        texts.append(title)
        if summary:
            slots[-1]["summary_idx"] = len(texts)
            texts.append(summary)

    if not texts:
        return stat

    if log:
        log(f"机翻 {len(slots)} 条（{len(texts)} 段文本）……")
    out, used = mt_mod.translate_batch(texts, log=log, provider=provider)
    stat["provider"] = used

    for slot in slots:
        if slot.get("only_summary"):
            zh_summary = out[slot["summary_idx"]] if slot["summary_idx"] is not None else ""
            if not zh_summary:
                stat["failed"] += 1
                continue
            # 术语归一化（护栏：只看本条原文语境）
            zh_summary, _ = glossary.normalize_text(zh_summary, slot["summary_src"])
            prev = store.get(slot["link"]) or {}
            store[slot["link"]] = {**prev,
                "zh_summary": zh_summary,
                "source_summary": slot["summary_src"],
                "summary_source": f"auto:{used}",
                "summary_translated_at": __import__("datetime").datetime.now()
                                          .astimezone().isoformat(timespec="seconds"),
            }
            stat["translated"] += 1
            continue
        zh_title = out[slot["title_idx"]]
        if not zh_title:
            stat["failed"] += 1
            continue
        zh_summary = ""
        if slot["summary_idx"] is not None:
            zh_summary = out[slot["summary_idx"]] or ""
        # 术语归一化（原文语境 = 标题 + 摘要）
        ctx_blob = f"{slot['title']} {slot['summary_src']}"
        zh_title, _ = glossary.normalize_text(zh_title, ctx_blob)
        if zh_summary:
            zh_summary, _ = glossary.normalize_text(zh_summary, ctx_blob)
        store[slot["link"]] = {
            "zh_title": zh_title,
            "zh_summary": zh_summary,
            "source_title": slot["title"],
            "source_summary": slot["summary_src"],
            "source": f"auto:{used}",
            "translated_at": __import__("datetime").datetime.now()
                              .astimezone().isoformat(timespec="seconds"),
        }
        stat["translated"] += 1

    save_news_store(store)
    return stat
