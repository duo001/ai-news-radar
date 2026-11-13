# -*- coding: utf-8 -*-
"""报告渲染（原型期只出 Markdown，方便直接贴飞书/公众号/知识星球）。

按类目分组，每条卡片含：等级总分、六维明细、项目说明、语言/星数/涨星、
免费 token 类独有块（额度/门槛/国内可用/风险）、链接。
"""
from datetime import datetime

# 多类目项目的主归属优先级（数字越小越优先）：
# 免费/优惠最稀缺 → 生态资产 → 最近技术（有年龄门槛）→ 通用工具。
# 抽到模块级，Markdown 与 HTML 渲染共用，保证两份报告归属一致。
PRIORITY = {"free-tokens": 0, "agent-skills": 1, "ai-tech": 2, "ai-tools": 3}


def primary_of(cat_ids):
    return min(cat_ids, key=lambda c: PRIORITY.get(c, 9))


def _dims_line(dims):
    return " · ".join(f"{k} {v:g}" for k, v in dims.items())


def _repo_line(r):
    bits = [r.get("lang") or "—",
            f"⭐ {r.get('stars', 0):,}"]
    if r.get("gained"):
        bits.append(f"近期 +{r['gained']:,}")
    if r.get("license"):
        bits.append(r["license"])
    return " · ".join(bits)


def _free_block(det):
    if not det:
        return ""
    lines = [f"  - **权益类型**：{'、'.join(det.get('offer_type', [])) or '—'}"]
    if det.get("quotas"):
        lines.append("  - **免费额度信号**：" + "；".join(det["quotas"][:3]))
    elif det.get("is_free_token"):
        lines.append("  - **免费额度信号**：README 未给出具体数字（仅声明 free tier/免费）")
    if det.get("promos"):
        lines.append("  - **优惠活动**（⚠️ 有时效，以官方页为准）：")
        for p in det["promos"][:5]:
            lines.append(f"    - [{p['type']}] {p['detail']}")
    if det.get("signup"):
        lines.append(f"  - 注册门槛：{'、'.join(dict.fromkeys(det['signup']))}")
    lines.append(f"  - 国内可用：{det['china']}")
    if det.get("form"):
        lines.append(f"  - 项目形态：{'、'.join(dict.fromkeys(det['form']))}")
    if det.get("risks"):
        lines.append("  - **安全风险**：")
        for rsk in det["risks"]:
            icon = {"high": "🔴 高", "medium": "🟠 中", "low": "🟡 低"}[rsk["level"]]
            lines.append(f"    - {icon}：{rsk['note']}")
    return "\n".join(lines)


def _card(item, cat_name, translations=None):
    r, sc, det = item["repo"], item["score"], item["detector"]
    url = f"https://github.com/{r['full_name']}"
    parts = [
        f"### {sc['grade']} · {sc['total']:g} 分｜[{r['full_name']}]({url})",
        f"- 类目：{cat_name}　|　{_repo_line(r)}",
    ]
    if r.get("desc"):
        source = r["desc"].strip()
        zh = (translations or {}).get(r["full_name"].lower())
        zh = zh.get("zh") if isinstance(zh, dict) else zh
        if zh:
            parts.append(f"- 简介：{zh}")
            parts.append(f"  - 原文：{source[:200]}")
        else:
            parts.append(f"- 简介：{source[:220]}")
    if r.get("topics"):
        parts.append("- topics：" + ", ".join(r["topics"][:8]))
    parts.append(f"- 评分明细：{_dims_line(sc['dims'])}（满分 100）")
    block = _free_block(det)
    if block:
        parts.append(block)
    parts.append(f"- 信息截至：{datetime.now().strftime('%Y-%m-%d')}（额度政策变动快，使用前以官方页面为准）")
    return "\n".join(parts)


def render_markdown(payload, cats, translations=None):
    import i18n
    if translations is None:
        translations = i18n.load_store()
    cat_name = {c.id: c.name for c in cats}
    now = payload["generated_at"][:16].replace("T", " ")
    L = [
        f"# AI 开源雷达报告",
        f"",
        f"> 生成时间：{now}　|　trending 口径：{payload['since']}　|　模式：{payload['mode']}　|　通路：{payload['token_source']}",
        f"> 候选 {payload['counts']['candidates']} 个，入选 {payload['counts']['selected']} 个，淘汰 {payload['counts']['rejected']} 个。",
        f"> 全局规则：AI 模型本体开发（权重仓/训练推理引擎/论文复现）已硬排除。",
    ]
    done, pending, native = i18n.coverage(payload["results"])
    if done or pending:
        if pending:
            L.append(f"> 简介中文翻译：{done} 条已译 / {native} 条原文即中文 / {pending} 条待译"
                     f"（`radar.py translate --todo` 导出待译清单，填好后 `--apply` 写回）。")
        else:
            L.append(f"> 简介中文翻译：{done} 条英文简介已全部翻译，另有 {native} 条原文即中文。")
    L.append("")
    # 主类目归属：一个项目只进一个 tab，避免同卡片在多个类目重复。
    grouped = {cid: [] for cid in cat_name}
    cross = []
    for item in payload["results"]:
        cats = item["categories"]
        primary = primary_of(cats)
        item["primary_category"] = primary
        grouped.setdefault(primary, []).append(item)
        if len(cats) > 1:
            cross.append((item, cats))

    for cid, name in cat_name.items():
        items = grouped.get(cid, [])
        L.append(f"## {name}（{len(items)}）")
        if not items:
            L.append("\n_本轮无入选项目。_\n")
            continue
        for item in sorted(items, key=lambda x: x["score"]["total"], reverse=True):
            # 多类目项目在卡片上注明次归属，信息不丢但不重复占榜
            secondary = [cat_name[c] for c in item["categories"] if c != cid]
            card = _card(item, name, translations)
            if secondary:
                card += f"\n- 同时涉及：{'、'.join(secondary)}（按主归属 {name} 展示）"
            L.append(card)
            L.append("")

    # AI 资讯信源（RSS/Atom），独立板块，GitHub 抓取失败也不影响它
    if payload.get("news"):
        L.append("---")
        L.append(_news_markdown_body(
            payload["news"], payload.get("news_failures", []),
            payload.get("news_translations")))

    # 淘汰摘要（帮用户判断过滤是否过严，原型期保留）
    if payload.get("rejected"):
        L.append("---")
        L.append(f"## 附：淘汰记录（前 15 条，共 {len(payload['rejected'])} 条）")
        for rj in payload["rejected"][:15]:
            L.append(f"- `{rj['full_name']}` — {rj['reason']}")
    L.append("")
    return "\n".join(L)


def _news_date(published):
    """资讯条目日期统一成 MM-DD；入参可能是 ISO 字符串（run 落盘后）。"""
    if not published:
        return "--"
    if isinstance(published, str):
        try:
            published = datetime.fromisoformat(published)
        except ValueError:
            return "--"
    return published.strftime("%m-%d")


def _news_markdown_body(news, failures, translations=None):
    """资讯板块正文（也供独立的 news 报告复用）。按 group 分组。

    translations 为资讯翻译库 {link: {zh_title, zh_summary}}；有译文时标题显示中文，
    英文原标题与摘要缩进保留，未翻译条目照旧显示原文。
    """
    translations = translations or {}
    groups, order = {}, []
    for e in news:
        g = e.get("group", "其他")
        if g not in groups:
            groups[g] = []
            order.append(g)
        groups[g].append(e)
    L = [f"## AI 资讯（RSS/Atom 信源，共 {len(news)} 条 / {len(groups)} 个分组）"]
    for g in order:
        L.append(f"\n### {g}（{len(groups[g])}）")
        for it in groups[g]:
            date = _news_date(it.get("published"))
            tr = translations.get(it.get("link", "")) or {}
            zh_title = tr.get("zh_title", "")
            head = zh_title or it["title"]
            L.append(f"- [{date}] [{head[:90]}]({it['link']}) —— {it['source_name']}")
            if zh_title and zh_title != it["title"]:
                L.append(f"  - 原标题：{it['title'][:120]}")
            zh_sum = tr.get("zh_summary", "")
            if zh_sum:
                L.append(f"  - {zh_sum[:200]}")
            elif it.get("summary"):
                L.append(f"  - {it['summary'][:160]}")
    if failures:
        L.append("\n> 本轮失败/不可达信源：" + "、".join(f["name"] for f in failures)
                 + "（配置保留在 data/sources/feeds.json，网络恢复后可启用）")
    return "\n".join(L)


def render_news_markdown(payload):
    """只含资讯的独立 Markdown（radar news --out 用）。"""
    news = payload.get("news", [])
    L = ["# AI 资讯速递",
         f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}　|　"
         f"条目 {len(news)} 条",
         ""]
    L.append(_news_markdown_body(news, payload.get("news_failures", []),
                                  payload.get("news_translations")))
    return "\n".join(L) + "\n"
