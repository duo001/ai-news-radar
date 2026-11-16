# -*- coding: utf-8 -*-
"""ai-git-radar 单入口 CLI。

主力（v0.6 起）：
  news                  并发采集 RSS/Atom AI 资讯 → md + html + json，套用中文翻译
      --only id|分组     按信源 id 或分组过滤
      --per-source N    每源最多条数（默认 8）
      --workers N       并发数（默认 8，1 为串行）
      --offline         只用 data/cache/feeds 缓存
  translate --news      资讯翻译流水线：--todo 导出 / --apply 合并 / --coverage 覆盖率
  discover              信源自动发现（网页/OPML/远程清单）→ 待审队列 → --accept 采纳
  doctor                网络通路、信源/缓存、类目自检
  categories            列出已注册 GitHub 类目

已封存（legacy，代码保留可用）：
  run                   GitHub 项目采集 → 分类 → 检测 → 评分 → Markdown + HTML
  render / translate（不带 --news）  仓库简介翻译与重渲染

设计：资讯 IO 集中在 feeds.py，GitHub IO 在 gh_client；业务规则在
registry/classify/detectors/scorer，报告在 report.py / html_report.py。
加资讯源只动 data/sources/feeds.json，加 GitHub 类目只动 categories/*.yaml。
"""
import argparse
import json
import pathlib
import sys
import time
from datetime import datetime

import gh_client
import registry
import classify as classify_mod
import detectors
import scorer as scorer_mod
import report
import html_report
import i18n
import feeds
import collectors
import enrich
import discover
import db

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def _log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def _drop_flagged_noise(entries, log=None):
    """对 feeds.json 里标了 noise_filter 的论坛类源做去噪，返回过滤后的列表。

    只影响显式标记的源（如奶昔论坛最新话题），正常资讯源不受影响。
    """
    if not entries:
        return entries
    try:
        flagged = {s["id"] for s in feeds.load_feeds(include_disabled=True)
                   if s.get("noise_filter")}
    except Exception:
        return entries
    if not flagged:
        return entries
    subset = [e for e in entries if e.get("source_id") in flagged]
    if not subset:
        return entries
    kept, dropped = enrich.drop_noise(subset, log)
    if not dropped:
        return entries
    kept_ids = {id(e) for e in kept}
    return [e for e in entries
            if e.get("source_id") not in flagged or id(e) in kept_ids]


def _serialize_news(entries):
    """把 feeds 的 datetime 转成 ISO 字符串，便于 JSON 落盘。"""
    out = []
    for e in entries:
        out.append({**e, "published": e["published"].isoformat() if e.get("published") else None})
    return out


# --------------------------------------------------------------- doctor

def cmd_doctor(_args):
    _log("检查运行环境……")
    print(f"Python      : {sys.version.split()[0]}")
    print(f"token 来源  : {gh_client.token_source()}")
    try:
        cats = registry.load_categories()
        print(f"类目加载    : {len(cats)} 个 → {[c.id for c in cats]}")
        rules = registry.load_global()
        print(f"全局规则    : 模型本体排除词 {len(rules.get('exclude_model_body', {}).get('keywords', []))} 条")
    except Exception as e:
        print(f"类目加载失败: {e}")
        return 1
    try:
        t = gh_client.fetch_trending("daily")
        print(f"trending 通路: OK，今日榜 {len(t)} 条（示例 {t[0]['full_name'] if t else '-'}）")
    except Exception as e:
        print(f"trending 通路: 失败 {e}")
        return 1
    # 资讯信源：只校验配置与本地缓存，不额外发网络请求
    try:
        enabled = feeds.load_feeds()
        all_src = feeds.load_feeds(include_disabled=True)
        cached = len(list((DATA / "cache" / "feeds").glob("*.xml"))) if (DATA / "cache" / "feeds").exists() else 0
        ids = [s["id"] for s in all_src]
        dup = {x for x in ids if ids.count(x) > 1}
        print(f"资讯信源    : 启用 {len(enabled)}/{len(all_src)} 个，本地缓存 {cached} 个"
              + (f"，⚠️ 重复 id: {dup}" if dup else ""))
    except Exception as e:
        print(f"资讯信源    : 配置异常 {e}")
    return 0


def cmd_categories(_args):
    for c in registry.load_categories():
        qs = c.queries()
        print(f"- {c.id:12s} {c.name} | topics={len(c.topics)} 查询={len(qs)} "
              f"readme信号={len(c.readme_signals)} keep_lists={c.keep_lists}")
        print(f"    {c.desc}")


# --------------------------------------------------------------- 采集

def collect_candidates(cats, since, quick, offline):
    """trending + 各类目搜索，按 full_name 去重合流。"""
    pool = {}

    def absorb(item, cat_id=None):
        key = item["full_name"].lower()
        old = pool.get(key)
        if old is None:
            pool[key] = item
        else:
            # 合流：保留 gained/topics 等更全的字段
            for k in ("gained", "topics", "created_at", "pushed_at", "license", "archived"):
                if not old.get(k) and item.get(k):
                    old[k] = item[k]
            old["source"] = old.get("source", "") + "+" + item.get("source", "")
        if cat_id:
            hints = set(pool[key].get("cat_hints", []))
            hints.add(cat_id)
            pool[key]["cat_hints"] = sorted(hints)

    if not offline:
        _log(f"抓 trending({since})……")
        try:
            for r in gh_client.fetch_trending(since):
                absorb(r)
        except Exception as e:
            _log(f"trending 失败（继续走搜索）: {e}")

    if not quick:
        token = gh_client.get_token()
        queries = []
        for c in cats:
            queries.extend((c, qn) for qn in c.queries())
        _log(f"Search 候选查询 {len(queries)} 条（{'有 token' if token else '匿名，自动限流 8s/条'}）")
        for i, (cat, (q, per_page)) in enumerate(queries, 1):
            cached = gh_client.cache_get("search", f"q={q}|n={per_page}") is not None
            try:
                for item in gh_client.search(q, per_page=per_page, use_cache=True):
                    absorb(item, cat.id)
            except gh_client.RateLimited:
                _log("Search 额度用完，剩余查询跳过（可用 --quick 或配 token）")
                break
            except Exception as e:
                _log(f"查询失败跳过：{q} → {e}")
            # 匿名 search 限额 10 次/分钟；缓存命中没有发请求，不占额度也不必等
            if not token and not cached and i < len(queries):
                time.sleep(8)
    _log(f"候选池合计 {len(pool)} 个去重仓库")
    return list(pool.values())


def _hot(r):
    return (r.get("gained", 0) > 0, r.get("stars", 0))


def _stratified_select(candidates, cats, top_n):
    """按类目配额截断，避免全局按星数一刀切把新类目/新项目挤没。

    每类目保底 ceil(top_n/类目数) 个名额，从该类目的搜索来源候选里按热度取；
    保底分完后，剩余名额对全部候选按热度补齐、去重。trending 候选无类目提示，
    自然进入最后的热度补齐池。
    """
    import math
    quota = math.ceil(top_n / max(len(cats), 1))
    chosen, names = [], set()

    def take(seq, n):
        cnt = 0
        for r in sorted(seq, key=_hot, reverse=True):
            nm = r["full_name"].lower()
            if nm in names:
                continue
            names.add(nm)
            chosen.append(r)
            cnt += 1
            if cnt >= n:
                break

    # 第一轮：各类目保底（用搜索阶段记录的 cat_hints）
    for c in cats:
        bucket = [r for r in candidates if c.id in r.get("cat_hints", [])]
        take(bucket, quota)
    # 第二轮：剩余名额按热度全局补齐（含 trending 与未归类候选）
    if len(chosen) < top_n:
        take(candidates, top_n - len(chosen))
    return chosen[:top_n]


# --------------------------------------------------------------- 主流程

def cmd_run(args):
    cats = registry.load_categories(only=args.only.split(",") if args.only else None)
    rules = registry.load_global()
    candidates = collect_candidates(cats, args.since, args.quick, args.offline)

    candidates = _stratified_select(candidates, cats, args.top)
    if not args.offline:
        rem = gh_client.preflight(min_remaining=len(candidates) + 5)
        if gh_client.core_exhausted():
            _log(f"匿名 core 额度仅剩 {rem} 次（需 ~{len(candidates)}），本轮直接走网页/raw 通路（慢但零额度）")
        elif rem is not None:
            _log(f"core 剩余额度 {rem} 次")
    _log(f"深度分析前 {len(candidates)} 个候选（补详情 + README 静态分析）……")

    results, rejected = [], []
    for idx, repo in enumerate(candidates, 1):
        name = repo["full_name"]
        detail, readme = {}, ""
        if not args.offline:
            try:
                detail = gh_client.repo_detail(name) or {}
            except Exception as e:
                _log(f"  详情失败 {name}: {e}")
            try:
                readme = gh_client.readme(name)
            except Exception as e:
                _log(f"  README 失败 {name}: {e}")
        else:
            detail = gh_client.cache_get("repo", name) or {}
            readme = gh_client.cache_get("readme", name) or ""
        # 网页兜底的星数/license 选择器可能失效给 0/空串，不允许覆盖 search/trending 的真值
        merged = dict(repo)
        for k, v in detail.items():
            if k == "readme":
                continue
            if k in ("stars", "forks", "open_issues") and not v and merged.get(k):
                continue
            if k in ("license", "topics", "homepage", "desc", "lang") and not v and merged.get(k):
                continue
            merged[k] = v

        hits = classify_mod.classify(merged, cats, readme)
        if not hits:
            rejected.append({"full_name": name,
                             "reason": classify_mod.reject_reason(merged, cats, readme)})
            continue

        eng = detectors.engineering_signals(readme, merged.get("desc", ""))
        detector = None
        if "free-tokens" in hits:
            detector = detectors.detect_token_offer(readme, merged.get("desc", ""))
            if detector is None:
                # 粗捞进来但 README 既无免费额度也无优惠信号：仅保留清单/网关类
                # （清单本身有情报价值，命中 _FORM_SIGNALS 即放行）
                hits.remove("free-tokens")
                detector = None
        if not hits:
            rejected.append({"full_name": name, "reason": "无免费/优惠实证信号"})
            continue

        cat0 = next(c for c in cats if c.id == hits[0])
        sc = scorer_mod.score(merged, cat0, eng, detector)
        results.append({
            "repo": merged, "categories": hits, "score": sc,
            "eng": eng, "detector": detector,
            "readme_head": readme[:500],
        })
        _log(f"  [{idx}/{len(candidates)}] {name} → {hits} {sc['grade']}({sc['total']})")

    results.sort(key=lambda x: x["score"]["total"], reverse=True)

    # 资讯信源（RSS/Atom）：独立容错，失败不影响 GitHub 主链路
    news_entries, news_failures = [], []
    if not args.offline or (DATA / "cache" / "feeds").exists():
        _log("采集 AI 资讯信源（RSS/Atom）……")
        news_entries, news_failures, news_dup = feeds.fetch_all(
            offline=args.offline, per_source_limit=args.news_per, log=_log)
        col_entries, col_failures = collectors.fetch_all(
            offline=args.offline, log=_log)
        if col_entries:
            have = {e.get("link") for e in news_entries}
            news_entries.extend(e for e in col_entries if e.get("link") not in have)
        news_failures.extend(col_failures)
        news_entries = _drop_flagged_noise(news_entries, _log)
        enrich.attach(news_entries)
        _log(f"资讯合计 {len(news_entries)} 条，失败信源 {len(news_failures)} 个，去重 {news_dup} 条")

    payload = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "since": args.since, "mode": "quick" if args.quick else "full",
        "token_source": gh_client.token_source(),
        "counts": {"candidates": len(candidates), "selected": len(results),
                   "rejected": len(rejected), "news": len(news_entries)},
        "results": results, "rejected": rejected,
        "news": _serialize_news(news_entries),
        "news_failures": news_failures,
    }
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    out_json = DATA / f"run-{stamp}.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    md_path, html_path = _write_reports(payload, cats, stamp)
    _log(f"完成：入选 {len(results)} / 淘汰 {len(rejected)}")
    _log(f"Markdown: {md_path}")
    _log(f"HTML:     {html_path}")
    _log(f"数据:     {out_json}")
    return 0


# --------------------------------------------------------------- 翻译流水线

def _latest_run():
    """找最新一份 run-*.json（translate/render 默认基于它）。

    交付目录清理后可能只剩 sample-run.json，回退用它，保证 render/translate 可演示。
    """
    files = sorted(DATA.glob("run-*.json"))
    if files:
        return files[-1]
    sample = DATA / "sample-run.json"
    if sample.exists():
        return sample
    raise FileNotFoundError("data/ 下没有 run-*.json，先跑一次 run")


def cmd_translate(args):
    # --news：资讯翻译通道（按文章 link 建 key，独立存储）
    if getattr(args, "news", False):
        payload = _news_payload_for_translate()
        entries = payload.get("news", [])
        if args.coverage:
            done, pending, native = i18n.news_coverage(entries)
            total = done + pending
            pct = f"{done / total * 100:.0f}%" if total else "—"
            print(f"资讯翻译库条目：{len(i18n.load_news_store())}")
            print(f"本轮英文标题 {total} 条：已译 {done}（{pct}），待译 {pending}；"
                  f"另有 {native} 条原文即中文")
            return 0
        if args.apply:
            added, skipped = i18n.apply_news_todo()
            _log(f"资讯翻译合并完成：新增 {added} 条，跳过 {skipped} 条（空译或已存在）")
            _rerender_news(payload)
            return 0
        if getattr(args, "auto", False):
            # 免费机翻通道：批量英译中，直接写入资讯翻译库
            stat = i18n.auto_translate_news(
                entries, log=_log,
                limit=getattr(args, "limit", None),
                provider=getattr(args, "provider", None))
            _log(f"机翻完成：处理 {stat['considered']} 条，成功 {stat['translated']} 条，"
                 f"失败 {stat['failed']} 条，跳过 {stat['skipped']} 条"
                 f"（通道：{stat['provider']}）")
            _rerender_news(payload)
            done, pending, native = i18n.news_coverage(entries)
            _log(f"当前覆盖率：已译 {done} / 待译 {pending}（原文中文 {native}）")
            return 0 if stat["translated"] or not stat["considered"] else 1
        todo = i18n.build_news_todo(entries)
        path = i18n.write_news_todo(todo)
        _log(f"资讯待译清单：{path}（{len(todo['items'])} 条）")
        if todo["items"]:
            print("下一步：编辑该文件，给每条填 zh_title（必填）和 zh_summary（可选），再跑：")
            print("  python3 radar.py translate --news --apply")
        else:
            print("没有需要翻译的英文标题（已全译或原文即中文）。")
        return 0

    # 默认：GitHub 仓库简介翻译通道（run 已封存，基于最新 run/sample 数据）
    payload = json.loads(_latest_run().read_text(encoding="utf-8"))
    if args.coverage:
        done, pending, native = i18n.coverage(payload["results"])
        total = done + pending
        pct = f"{done / total * 100:.0f}%" if total else "—"
        print(f"翻译库条目：{len(i18n.load_store())}")
        print(f"本轮英文简介 {total} 条：已译 {done}（{pct}），待译 {pending}；"
              f"另有 {native} 条原文即中文")
        return 0
    if args.apply:
        added, skipped = i18n.apply_todo()
        _log(f"翻译合并完成：新增 {added} 条，跳过 {skipped} 条（空译或已存在）")
        # apply 后顺手重渲染最新报告
        md = _rerender(payload)
        _log(f"报告已刷新: {md}")
        return 0
    # 默认：导出待译清单
    todo = i18n.build_todo(payload["results"])
    path = i18n.write_todo(todo)
    _log(f"待译清单：{path}（{len(todo['items'])} 条）")
    if todo["items"]:
        print("下一步：编辑该文件，给每条的 zh 字段填中文（可只填部分），再跑：")
        print("  python3 radar.py translate --apply")
    else:
        print("没有需要翻译的英文简介（已全译或原文即中文）。")
    return 0


def _rerender_news(payload):
    """用最新 news 数据 + 当前资讯翻译库重渲染 md + html，并同步插件固定文件。"""
    payload["news_translations"] = i18n.load_news_store()
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    md_path = DATA / f"news-{stamp}.md"
    html_path = DATA / f"news-{stamp}.html"
    md_path.write_text(report.render_news_markdown(payload), encoding="utf-8")
    html_path.write_text(html_report.render_news_html(
        payload, payload["news_translations"]), encoding="utf-8")
    _log(f"资讯报告已刷新: {md_path} / {html_path}")
    # 工作台插件读的是固定路径的 plugin-news.json，翻译后要同步一次，
    # 否则面板刷新也看不到新译文（Data flow: translate → plugin-news.json → 面板）
    plugin_json = DATA / "plugin-news.json"
    if plugin_json.exists():
        try:
            saved = json.loads(plugin_json.read_text(encoding="utf-8"))
            saved["news_translations"] = payload["news_translations"]
            plugin_json.write_text(
                json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
            _log("插件固定文件已同步译文")
        except (json.JSONDecodeError, OSError) as exc:
            _log(f"插件固定文件同步失败：{exc}")


def _write_reports(payload, cats, stamp):
    """同一 payload 同时落 Markdown 与自包含 HTML，返回 (md_path, html_path)。"""
    md_path = DATA / f"report-{stamp}.md"
    html_path = DATA / f"report-{stamp}.html"
    md_path.write_text(report.render_markdown(payload, cats), encoding="utf-8")
    html_path.write_text(html_report.render_html(payload, cats), encoding="utf-8")
    return md_path, html_path


def _rerender(payload):
    """重渲染最新报告（md + html），返回 Markdown 路径（保持旧调用方签名）。"""
    cats = registry.load_categories()
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    md_path, html_path = _write_reports(payload, cats, stamp)
    _log(f"HTML: {html_path}")
    return md_path


def cmd_render(_args):
    """用最新 run 数据 + 当前翻译库重新渲染报告（不重新抓取）。"""
    payload = json.loads(_latest_run().read_text(encoding="utf-8"))
    md = _rerender(payload)
    _log(f"已重渲染: {md}")
    return 0


# --------------------------------------------------------------- 资讯信源

def _latest_news():
    """找最新一份 news-*.json（资讯翻译/重渲染默认基于它），回退 sample-news.json。"""
    files = sorted(DATA.glob("news-*.json"))
    if files:
        return files[-1]
    sample = DATA / "sample-news.json"
    if sample.exists():
        return sample
    raise FileNotFoundError("data/ 下没有 news-*.json，先跑一次 news")


def _news_payload_for_translate():
    """翻译/重渲染要基于**最全的一份**资讯，而不是最新的 news-*.json。

    插件日常走 `news --quiet --json-out plugin-news.json`（不产 news-*.json），
    会导致最新 news-*.json 停在很久以前、漏掉新增条目，机翻因此「处理 0 条」。
    优先用 plugin-news.json（条目通常最新最全），回退最新 news-*.json。
    """
    plugin_json = DATA / "plugin-news.json"
    candidates = []
    if plugin_json.exists():
        candidates.append(plugin_json)
    candidates.extend(sorted(DATA.glob("news-*.json")))
    sample = DATA / "sample-news.json"
    if sample.exists():
        candidates.append(sample)
    best, best_n = None, -1
    for p in candidates:
        try:
            n = len(json.loads(p.read_text(encoding="utf-8")).get("news", []))
        except (json.JSONDecodeError, OSError):
            continue
        if n > best_n:
            best, best_n = p, n
    if best is None:
        raise FileNotFoundError("data/ 下没有可翻译的资讯文件，先跑一次 news")
    return json.loads(best.read_text(encoding="utf-8"))


def cmd_news(args):
    """主力命令：并发采集 RSS/Atom 资讯，套用中文翻译，出 md + html + json 三份产物。

    不碰 GitHub（GitHub 项目拉取已封存到 run 命令）。
    """
    offline = getattr(args, "offline", False)
    db.init_db()

    if offline:
        # 离线模式：DB 就是持久化缓存，跳过采集直接读
        # DB 空时回退到 feed 缓存兜底（首次离线使用场景）
        db_entries = db.query_news(days=db.RETENTION_DAYS)
        if db_entries:
            entries, failures, dup_count = db_entries, [], 0
            if not getattr(args, "quiet", False):
                _log(f"离线模式：从 SQLite 读 {len(db_entries)} 条（跳过采集）")
        else:
            # 首次离线使用，DB 为空，走 feed 缓存兜底
            entries, failures, dup_count = feeds.fetch_all(
                only=args.only, offline=True,
                per_source_limit=args.per_source,
                log=(lambda *_a, **_k: None) if getattr(args, "quiet", False) else _log,
                workers=getattr(args, "workers", 8))
            if not getattr(args, "quiet", False):
                _log(f"离线模式：DB 空，回退到 feed 缓存 {len(entries)} 条")
    else:
        # 在线模式：正常采集（带进度追踪）
        try:
            entries, failures, dup_count = feeds.fetch_all(
                only=args.only, offline=False,
                per_source_limit=args.per_source,
                log=(lambda *_a, **_k: None) if getattr(args, "quiet", False) else _log,
                workers=getattr(args, "workers", 8))
        finally:
            feeds.clear_progress()

    # ---- 非 RSS 结构化 API 采集器（OpenRouter 免费模型 / Hacker News 等）----
    # 离线时只读本地缓存，无缓存则该源记失败，不影响 RSS 主链路
    quiet_log = (lambda *_a, **_k: None) if getattr(args, "quiet", False) else _log
    col_entries, col_failures = collectors.fetch_all(
        only=getattr(args, "only", None), offline=offline, log=quiet_log)
    if col_entries:
        existing_links = {e.get("link") for e in entries}
        added = [e for e in col_entries if e.get("link") not in existing_links]
        entries.extend(added)
        if not offline and not getattr(args, "quiet", False):
            _log(f"结构化采集器新增 {len(added)} 条（{len(col_entries)} 条去重后）")
    failures.extend(col_failures)

    # ---- 论坛类源去噪（只对 feeds.json 标了 noise_filter 的源生效）----
    entries = _drop_flagged_noise(entries, quiet_log)

    if not entries:
        if getattr(args, "quiet", False):
            return 1
        _log("没有抓到任何资讯条目（全部信源失败或离线无缓存）")
        for f in failures:
            print(f"  ✗ {f['name']}: {f['error']}")
        return 1

    # ---- 规则增强：form/obtain/topics/codes（纯函数，渲染层也可重算）----
    enrich.attach(entries)
    for e in entries:
        # 领域标签写进 tags 列随 DB 持久化；codes/obtain 渲染时按 title+summary 重算
        if e.get("topics") and not e.get("tags"):
            e["tags"] = e["topics"]

    news_trans = i18n.load_news_store()

    # ---- SQLite 持久化 ----
    # RSS 直读 DB（离线有数据）时跳过，避免重复 ISO 化；结构化采集器的新条目
    # 即使在离线模式（读本地缓存）也要入库，单独序列化写入。
    need_write = bool(entries) and not isinstance(entries[0].get("published"), str)
    if need_write:
        db.upsert_news(_serialize_news(entries))
    elif col_entries:
        db.upsert_news(_serialize_news(col_entries))
    pruned = db.prune_old()
    # 从 DB 读回最近 RETENTION_DAYS 天，作为插件消费的 JSON 快照
    # （这样历史资讯不丢、跨采集合并，且 JSON 恒定在 30 天窗口内，体积可控）
    db_entries = db.query_news(days=db.RETENTION_DAYS)
    # 历史条目（含此前未增强的 RSS 数据）在渲染前统一补算 form/obtain/codes
    # 历史入库的噪音（交易/问询帖）在渲染层也过滤掉，不必等下次在线采集清理
    db_entries = _drop_flagged_noise(db_entries, None)
    enrich.attach(db_entries)
    if pruned and not getattr(args, "quiet", False):
        _log(f"保留策略：清理 {pruned} 条 {db.RETENTION_DAYS} 天前的过期资讯")

    payload = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "mode": "news-only",
        "news": db_entries,
        "news_failures": failures,
        "news_dup": dup_count,
        "news_translations": news_trans,
    }
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    DATA.mkdir(parents=True, exist_ok=True)
    quiet = getattr(args, "quiet", False)
    if quiet:
        # 工作台插件模式：不写时间戳三件套，只靠 --json-out 出固定路径 JSON
        json_path = md_path = html_path = None
    else:
        json_path = DATA / f"news-{stamp}.json"
        md_path = DATA / f"news-{stamp}.md"
        html_path = DATA / f"news-{stamp}.html"
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        md_path.write_text(report.render_news_markdown(payload), encoding="utf-8")
        html_path.write_text(html_report.render_news_html(payload, news_trans), encoding="utf-8")

    done, pending, native = i18n.news_coverage(entries)
    # 展示统计/分组按 DB 回读的 30 天窗口（更贴近插件实际看到的条数）
    groups = {}
    for e in db_entries:
        groups.setdefault(e["group"], []).append(e)
    if not quiet:
        print(f"\n{'='*64}\nAI 资讯 {len(db_entries)} 条（30 天窗口，{len(groups)} 个分组，"
              f"本次采集新增 {len(entries)} / 失败信源 {len(failures)} 个）\n"
              f"标题翻译：已译 {done} / 待译 {pending} / 原文即中文 {native}\n{'='*64}")
        for gname, items in groups.items():
            print(f"\n## {gname}（{len(items)}）")
            for it in items[:args.per_source]:
                pub = it.get("published")
                # DB 回读条目 published 是 ISO 字符串，本次采集的是 datetime，统一转 MM-DD
                if isinstance(pub, str) and len(pub) >= 10:
                    date = pub[5:10].replace("-", "-")
                elif pub:
                    date = pub.strftime("%m-%d")
                else:
                    date = "--"
                tr = news_trans.get(it.get("link", "")) or {}
                title = tr.get("zh_title") or it["title"]
                print(f"- [{date}] {title[:72]}  —— {it['source_name']}")
        if failures:
            print("\n失败/停用信源：" + "，".join(f["name"] for f in failures))
    if args.out:
        path = pathlib.Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report.render_news_markdown(payload), encoding="utf-8")
    if not quiet:
        _log(f"JSON: {json_path}")
        _log(f"Markdown: {md_path}")
        _log(f"HTML: {html_path}")
    if getattr(args, "json_out", ""):
        jo = pathlib.Path(args.json_out)
        jo.parent.mkdir(parents=True, exist_ok=True)
        jo.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        if not quiet:
            _log(f"JSON 固定路径副本: {jo}")
    if getattr(args, "translate", False) and payload.get("news"):
        stat = i18n.auto_translate_news(
            payload["news"], log=(None if quiet else _log),
            limit=getattr(args, "translate_limit", None))
        if not quiet:
            _log(f"机翻：成功 {stat['translated']} / 失败 {stat['failed']} / "
                 f"跳过 {stat['skipped']}（通道：{stat['provider']}）")
            pending = i18n.news_coverage(payload["news"])[1]
    if pending and not quiet:
        _log(f"有 {pending} 条英文标题待译：python3 radar.py translate --news --todo")
    return 0


def cmd_discover(args):
    """信源自动发现：网页 link/常见路径、OPML、远程清单 → 待审队列 → 采纳写回。"""
    if args.list:
        data = discover.load_suggestions()
        pending = [s for s in data["suggestions"] if s["status"] == "pending"]
        if not pending:
            print("待审队列为空。先运行：python3 radar.py discover")
            return 0
        print(f"待审信源 {len(pending)} 个（队列文件 data/source-suggestions.json）：\n")
        for s in pending:
            latest = (s.get("latest_item_at") or "")[:10] or "--"
            print(f"- {s['id']}  [{s.get('group', '其他')}]  {s['name'][:40]}")
            print(f"    {s['url']}")
            print(f"    条目 {s.get('item_count', '?')} · 最近更新 {latest} · 来源：{s.get('found_via', '')}")
        print("\n采纳：python3 radar.py discover --accept id1,id2（或 --accept-all）")
        print("忽略：python3 radar.py discover --ignore id1,id2")
        return 0

    if args.accept_all or args.accept or args.ignore:
        ids = []
        if args.accept_all:
            ids = [s["id"] for s in discover.load_suggestions()["suggestions"]
                   if s["status"] == "pending"]
            status = "accepted"
        elif args.accept:
            ids, status = [x.strip() for x in args.accept.split(",") if x.strip()], "accepted"
        else:
            ids, status = [x.strip() for x in args.ignore.split(",") if x.strip()], "ignored"
        changed = discover.set_status(ids, status)
        if not changed:
            print("没有匹配的待审条目（可能已处理或 id 写错）。")
            return 1
        for s in changed:
            mark = "✓ 采纳并写入 feeds.json" if status == "accepted" else "✗ 已忽略"
            print(f"{mark}: {s['id']} ({s['name'][:40]})")
        return 0

    # 发现模式（可组合；不带任何通道参数时默认网页发现）
    any_channel = args.opml or args.remote
    if not any_channel:
        _log("网页自动发现：解析种子站点的 RSS/Atom 声明并验证……")
        stats = discover.run_web_discovery(args.seeds, log=_log)
        print(f"种子 {stats['seeds']} 站：新增 {stats['added']}，已在信源表 {stats['exists']}，"
              f"队列重复 {stats['duplicate']}，验证失败 {stats['invalid']}，首页错误 {stats['errors']}")
    opml_targets = []
    if args.opml:
        opml_targets.append(args.opml)
    if args.opml_catalog:
        catalog = discover.load_opml_catalog()
        for alias in [x.strip() for x in args.opml_catalog.split(",") if x.strip()]:
            if alias not in catalog:
                print(f"✗ 目录中无别名 {alias}，可用：{', '.join(sorted(catalog))}")
                return 1
            _log(f"OPML 目录：{catalog[alias]['name']}")
            opml_targets.append(catalog[alias]["url"])
    for target in opml_targets:
        _log(f"OPML 导入：{target}")
        stats = discover.run_opml_import(target, log=_log)
        print(f"OPML 条目 {stats['entries']}：新增 {stats['added']}，已在表 {stats['exists']}，"
              f"重复 {stats['duplicate']}，失败 {stats['invalid']}")
    if args.remote:
        url = args.remote if isinstance(args.remote, str) and args.remote != "" else None
        _log(f"远程清单同步：{url or discover.DEFAULT_REMOTE}")
        stats = discover.run_remote_sync(url, log=_log)
        print(f"远程源 {stats['remote_sources']}：新增 {stats['added']}，已在表 {stats['exists']}，"
              f"重复 {stats['duplicate']}，失败 {stats['invalid']}")
    _log("完成。查看待审队列：python3 radar.py discover --list")
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        prog="radar.py",
        description="AI 资讯雷达：主力为 RSS/Atom 信源采集（news）；GitHub 项目拉取（run）已封存保留。")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor").set_defaults(func=cmd_doctor)
    sub.add_parser("categories").set_defaults(func=cmd_categories)
    r = sub.add_parser(
        "run",
        epilog="【已封存 legacy】GitHub 项目采集/分类/评分功能，代码保留可用；日常资讯请用 news 子命令（更快，零额度）。")
    r.add_argument("--quick", action="store_true", help="只用 trending，不打 Search API")
    r.add_argument("--since", default="daily", choices=["daily", "weekly", "monthly"])
    r.add_argument("--top", type=int, default=50,
                   help="最多深度分析多少个候选（默认 50；匿名走网页通路时较慢，配 token 走 API 更快）")
    r.add_argument("--only", default="", help="逗号分隔的类目 id，只跑指定 GitHub 类目")
    r.add_argument("--offline", action="store_true")
    r.add_argument("--news-per", type=int, default=8, dest="news_per",
                    help="每个资讯信源最多取多少条（默认 8）")
    r.set_defaults(func=cmd_run)
    t = sub.add_parser("translate", help="中文翻译流水线：导出待译清单 / 合并 / 覆盖率")
    t.add_argument("--todo", action="store_true", help="导出待译清单（默认动作）")
    t.add_argument("--apply", action="store_true", help="把填好的译文合并进翻译库并重渲染")
    t.add_argument("--coverage", action="store_true", help="只看翻译覆盖率")
    t.add_argument("--news", action="store_true",
                   help="走资讯翻译通道（标题/简介，按文章 link 存 news_translations.json）；不带则走仓库简介通道")
    t.add_argument("--auto", action="store_true",
                   help="（配合 --news）走免费机翻通道自动翻译并直接入库，无需人工填表")
    t.add_argument("--limit", type=int, default=None,
                   help="（配合 --auto）本次最多翻译多少条，默认全部")
    t.add_argument("--provider", default=None, choices=["transmart", "mymemory"],
                   help="（配合 --auto）指定翻译通道，默认自动降级")
    t.set_defaults(func=cmd_translate)
    sub.add_parser("render", help="【封存】用最新 GitHub run 数据和翻译库重新渲染报告").set_defaults(func=cmd_render)
    n = sub.add_parser("news", help="★ 主力命令：并发采集 RSS/Atom AI 资讯，出 md + html + json 并套用中文翻译")
    n.add_argument("--only", default="", help="按信源 id 或分组过滤，如 openai-news 或 科技媒体")
    n.add_argument("--per-source", type=int, default=8, help="每个信源最多取多少条（默认 8）")
    n.add_argument("--offline", action="store_true", help="只用缓存的 feed XML")
    n.add_argument("--workers", type=int, default=8, help="并发抓取信源数（默认 8；1 为串行）")
    n.add_argument("--out", default="", help="可选：额外把资讯写成指定 Markdown 文件")
    n.add_argument("--json-out", default="",
                   help="可选：把资讯 JSON 另写到固定路径（工作台插件用，避免时间戳文件名）")
    n.add_argument("--quiet", action="store_true",
                   help="静默模式：不打印分组摘要、不写时间戳三件套（工作台插件用，配合 --json-out）")
    n.add_argument("--translate", action="store_true",
                   help="采集后自动走免费机翻通道翻译英文标题/摘要")
    n.add_argument("--translate-limit", type=int, default=None,
                   help="（配合 --translate）本次最多翻译多少条，默认全部")
    n.set_defaults(func=cmd_news)
    d = sub.add_parser(
        "discover",
        help="信源自动发现：网页/OPML/远程清单 → 待审队列，--accept 采纳后写入 feeds.json")
    d.add_argument("--seeds", default="", help="自定义种子 JSON 路径（默认 data/sources/discover-seeds.json）")
    d.add_argument("--opml", default="", help="从 OPML 文件或 URL 批量导入订阅")
    d.add_argument("--opml-catalog", default="", dest="opml_catalog",
                   help="按 data/sources/opml-catalog.json 中的别名导入，逗号分隔（如 tidings-ai,rsshub-routes）")
    d.add_argument("--remote", nargs="?", const="", default=None,
                   help="同步远程开源信源表（裸用默认 AIHOT，也可传 JSON URL）")
    d.add_argument("--list", action="store_true", help="只列出待审队列")
    d.add_argument("--accept", default="", help="采纳指定 id（逗号分隔），写回 feeds.json")
    d.add_argument("--accept-all", action="store_true", help="采纳全部待审条目")
    d.add_argument("--ignore", default="", help="忽略指定 id（逗号分隔），保留记录不启用")
    d.set_defaults(func=cmd_discover)
    return p


if __name__ == "__main__":
    _args = build_parser().parse_args()
    sys.exit(_args.func(_args))
