# -*- coding: utf-8 -*-
"""自包含 HTML 报告渲染：单文件、内联 CSS、无 JS/无外部资源，可直接浏览器打开或转发。

与 report.render_markdown 共用同一份 payload、翻译库和主归属规则（report.PRIORITY），
保证 Markdown 与 HTML 两份报告的分类、排序、口径完全一致。
"""
from datetime import datetime
from html import escape

import i18n
from report import primary_of

# 六维满分（与 scorer.py 对齐），用于把原始分换算成分数条百分比
DIM_MAX = {
    "热度与增速": 25,
    "项目健康度": 20,
    "技术前沿度": 15,
    "可上手性": 15,
    "国内与中文": 15,
    "风险与合规": 10,
}

GRADE_COLOR = {"S": "#d4380d", "A": "#389e0d", "B": "#0958d9", "C": "#8c8c8c"}
RISK_ICON = {"high": ("🔴", "高"), "medium": ("🟠", "中"), "low": ("🟡", "低")}
ENG_LABEL = [
    ("has_one_click", "一键部署"),
    ("has_deploy_doc", "部署文档"),
    ("has_docker", "Docker"),
    ("has_demo", "在线 Demo"),
    ("has_chinese", "中文"),
    ("has_cloud_button", "云按钮"),
]

CSS = """
:root {
  --bg: #f4f5f7; --card: #ffffff; --text: #1f2329; --muted: #6b7280;
  --line: #e5e7eb; --accent: #0958d9; --chip: #f0f2f5; --shadow: 0 1px 3px rgba(0,0,0,.08);
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #14161a; --card: #1d2026; --text: #e6e8eb; --muted: #9aa0a8;
    --line: #2c313a; --accent: #69b1ff; --chip: #262b33; --shadow: 0 1px 3px rgba(0,0,0,.4);
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
    "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  line-height: 1.6; font-size: 15px;
}
.wrap { max-width: 1060px; margin: 0 auto; padding: 0 20px 60px; }
header.hero { padding: 36px 0 18px; }
h1 { margin: 0 0 10px; font-size: 28px; letter-spacing: .5px; }
.meta { color: var(--muted); font-size: 13px; display: flex; flex-wrap: wrap; gap: 6px 16px; }
.meta b { color: var(--text); font-weight: 600; }
.notice {
  margin: 14px 0 0; padding: 10px 14px; border-radius: 8px;
  background: var(--chip); color: var(--muted); font-size: 13px;
}
nav.tabs {
  position: sticky; top: 0; z-index: 10; background: var(--bg);
  padding: 10px 0; margin-bottom: 8px; display: flex; flex-wrap: wrap; gap: 8px;
  border-bottom: 1px solid var(--line);
}
nav.tabs a {
  text-decoration: none; color: var(--text); background: var(--card);
  border: 1px solid var(--line); border-radius: 999px; padding: 6px 14px;
  font-size: 13px; box-shadow: var(--shadow);
}
nav.tabs a:hover { border-color: var(--accent); color: var(--accent); }
nav.tabs .n { color: var(--muted); font-size: 12px; margin-left: 4px; }
section.cat { margin-top: 30px; }
section.cat > h2 {
  font-size: 19px; margin: 0 0 14px; padding-bottom: 8px;
  border-bottom: 2px solid var(--accent); display: flex; align-items: baseline; gap: 10px;
}
section.cat > h2 .pill {
  font-size: 12px; font-weight: 500; color: var(--accent);
  background: var(--chip); border-radius: 999px; padding: 2px 10px;
}
.empty { color: var(--muted); font-style: italic; }
.card {
  background: var(--card); border: 1px solid var(--line); border-radius: 12px;
  box-shadow: var(--shadow); padding: 18px 20px; margin-bottom: 14px;
}
.card-top { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.grade {
  flex: none; width: 42px; height: 42px; border-radius: 10px; color: #fff;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  font-weight: 700; line-height: 1.1;
}
.grade .g { font-size: 17px; }
.grade .s { font-size: 11px; opacity: .92; }
.repo-name { font-size: 17px; font-weight: 650; }
.repo-name a { color: var(--text); text-decoration: none; }
.repo-name a:hover { color: var(--accent); }
.repo-meta { color: var(--muted); font-size: 12.5px; display: flex; flex-wrap: wrap; gap: 4px 12px; margin-top: 2px; }
.desc { margin: 12px 0 4px; }
.desc .zh { font-weight: 500; }
.desc .orig { color: var(--muted); font-size: 13px; margin-top: 3px; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0 4px; }
.chip {
  font-size: 12px; color: var(--muted); background: var(--chip);
  border-radius: 6px; padding: 2px 8px;
}
.chip.good { color: #389e0d; }
.dims { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 8px 18px; margin: 12px 0 6px; }
.dim { font-size: 12px; color: var(--muted); }
.dim .bar { height: 6px; border-radius: 3px; background: var(--chip); margin-top: 4px; overflow: hidden; }
.dim .fill { height: 100%; border-radius: 3px; background: var(--accent); }
.dim b { color: var(--text); font-weight: 600; }
.free {
  margin-top: 12px; border: 1px solid var(--line); border-radius: 10px;
  padding: 12px 14px; background: var(--chip); font-size: 13.5px;
}
.free h4 { margin: 0 0 8px; font-size: 13.5px; }
.free ul { margin: 6px 0 0; padding-left: 20px; }
.free .warn { color: #d46b08; }
.risk-high { color: #cf1322; font-weight: 600; }
.risk-medium { color: #d46b08; }
.risk-low { color: #ad8b00; }
.secondary { margin-top: 10px; font-size: 12.5px; color: var(--muted); }
section.news { margin-top: 34px; }
.news-group { margin-bottom: 18px; }
.news-group h3 { font-size: 15px; margin: 0 0 8px; color: var(--accent); }
.news-item {
  background: var(--card); border: 1px solid var(--line); border-radius: 10px;
  padding: 10px 14px; margin-bottom: 8px;
}
.news-item a { color: var(--text); text-decoration: none; font-weight: 600; font-size: 14px; }
.news-item a:hover { color: var(--accent); }
.news-item .nmeta { color: var(--muted); font-size: 12px; margin-top: 2px; }
.news-item .nsum { color: var(--muted); font-size: 12.5px; margin-top: 4px; }
.news-fail { font-size: 12.5px; color: var(--muted); margin-top: 8px; }
details.rejected { margin-top: 34px; }
details.rejected summary { cursor: pointer; font-size: 15px; font-weight: 600; }
details.rejected ul { font-size: 13px; color: var(--muted); }
footer { margin-top: 40px; color: var(--muted); font-size: 12px; text-align: center; }
"""


def _e(x):
    return escape(str(x if x is not None else ""))


def _news_date(published):
    if not published:
        return "--"
    if isinstance(published, str):
        try:
            published = datetime.fromisoformat(published)
        except ValueError:
            return "--"
    return published.strftime("%m-%d")


def _news_html(news, failures, translations=None):
    if not news:
        return ""
    translations = translations or {}
    groups, order = {}, []
    for e in news:
        g = e.get("group", "其他")
        if g not in groups:
            groups[g] = []
            order.append(g)
        groups[g].append(e)
    parts = [f'<section class="news" id="sec-news"><h2>📰 AI 资讯'
             f'<span class="pill">{len(news)} 条 · RSS/Atom 信源</span></h2>']
    for g in order:
        parts.append(f'<div class="news-group"><h3>{_e(g)}（{len(groups[g])}）</h3>')
        for it in groups[g]:
            tr = translations.get(it.get("link", "")) or {}
            zh_title, zh_sum = tr.get("zh_title", ""), tr.get("zh_summary", "")
            head = zh_title or it["title"]
            parts.append(
                '<div class="news-item">'
                f'<a href="{_e(it["link"])}" target="_blank" rel="noopener">[{_e(_news_date(it.get("published")))}] {_e(head)}</a>'
                f'<div class="nmeta">来源：{_e(it["source_name"])}</div>')
            if zh_title and zh_title != it["title"]:
                parts.append(f'<div class="nmeta">原标题：{_e(it["title"][:160])}</div>')
            if zh_sum:
                parts.append(f'<div class="nsum">{_e(zh_sum[:240])}</div>')
            elif it.get("summary"):
                parts.append(f'<div class="nsum">{_e(it["summary"][:200])}</div>')
            parts.append("</div>")
        parts.append("</div>")
    if failures:
        names = "、".join(_e(f["name"]) for f in failures)
        parts.append(f'<div class="news-fail">本轮失败/不可达信源：{names}'
                     '（配置保留在 data/sources/feeds.json）</div>')
    parts.append("</section>")
    return "".join(parts)


def _grade_badge(grade, total):
    color = GRADE_COLOR.get(grade, "#8c8c8c")
    return (f'<div class="grade" style="background:{color}">'
            f'<span class="g">{_e(grade)}</span><span class="s">{total:g}</span></div>')


def _dims_html(dims):
    rows = []
    for name, val in dims.items():
        pct = max(0, min(100, round(float(val) / DIM_MAX.get(name, 10) * 100)))
        rows.append(
            f'<div class="dim"><b>{_e(name)}</b> {val:g}/{DIM_MAX.get(name, 10)}'
            f'<div class="bar"><div class="fill" style="width:{pct}%"></div></div></div>')
    return '<div class="dims">' + "".join(rows) + "</div>"


def _eng_chips(eng):
    chips = [f'<span class="chip good">{label}</span>'
             for key, label in ENG_LABEL if eng.get(key)]
    return ('<div class="chips">' + "".join(chips) + "</div>") if chips else ""


def _free_html(det):
    if not det:
        return ""
    L = ['<div class="free"><h4>🎁 免费 / 优惠情报</h4><ul>']
    L.append(f"<li><b>权益类型</b>：{_e('、'.join(det.get('offer_type', [])) or '—')}</li>")
    if det.get("quotas"):
        L.append("<li><b>免费额度信号</b>：" + _e("；".join(det["quotas"][:3])) + "</li>")
    elif det.get("is_free_token"):
        L.append("<li><b>免费额度信号</b>：README 未给出具体数字（仅声明 free tier/免费）</li>")
    if det.get("promos"):
        L.append('<li class="warn"><b>优惠活动</b>（⚠️ 有时效，以官方页为准）：<ul>')
        for p in det["promos"][:5]:
            L.append(f"<li>[{_e(p['type'])}] {_e(p['detail'])}</li>")
        L.append("</ul></li>")
    if det.get("signup"):
        L.append("<li><b>注册门槛</b>：" + _e("、".join(dict.fromkeys(det["signup"]))) + "</li>")
    L.append(f"<li><b>国内可用</b>：{_e(det.get('china', '—'))}</li>")
    if det.get("form"):
        L.append("<li><b>项目形态</b>：" + _e("、".join(dict.fromkeys(det["form"]))) + "</li>")
    if det.get("risks"):
        L.append("<li><b>安全风险</b>：<ul>")
        for rsk in det["risks"]:
            icon, label = RISK_ICON.get(rsk["level"], ("⚪", rsk["level"]))
            L.append(f'<li class="risk-{_e(rsk["level"])}">{icon} {label}：{_e(rsk["note"])}</li>')
        L.append("</ul></li>")
    L.append("</ul></div>")
    return "".join(L)


def _card_html(item, cat_name, translations):
    r, sc, det, eng = item["repo"], item["score"], item["detector"], item.get("eng", {})
    url = f"https://github.com/{_e(r['full_name'])}"
    meta = [_e(r.get("lang") or "—"), f"⭐ {r.get('stars', 0):,}"]
    if r.get("gained"):
        meta.append(f"近期 +{r['gained']:,}")
    if r.get("license"):
        meta.append(_e(r["license"]))

    desc_html = ""
    if r.get("desc"):
        source = r["desc"].strip()
        zh = translations.get(r["full_name"].lower())
        zh = zh.get("zh") if isinstance(zh, dict) else zh
        if zh:
            desc_html = (f'<div class="desc"><div class="zh">{_e(zh)}</div>'
                         f'<div class="orig">原文：{_e(source[:200])}</div></div>')
        else:
            desc_html = f'<div class="desc">{_e(source[:220])}</div>'

    topics = ""
    if r.get("topics"):
        topics = ('<div class="chips">'
                  + "".join(f'<span class="chip">{_e(t)}</span>' for t in r["topics"][:8])
                  + "</div>")

    secondary = [c for c in item["categories"] if c != item.get("primary_category")]
    sec_html = (f'<div class="secondary">同时涉及：{_e("、".join(secondary))}'
                f'（按主归属「{_e(cat_name)}」展示）</div>') if secondary else ""

    return f"""
    <article class="card" id="{_e(r['full_name'])}">
      <div class="card-top">
        {_grade_badge(sc['grade'], sc['total'])}
        <div>
          <div class="repo-name"><a href="{url}" target="_blank" rel="noopener">{_e(r['full_name'])}</a></div>
          <div class="repo-meta">{'　·　'.join(meta)}</div>
        </div>
      </div>
      {desc_html}
      {topics}
      {_dims_html(sc['dims'])}
      {_eng_chips(eng)}
      {_free_html(det)}
      {sec_html}
    </article>"""


def render_html(payload, cats, translations=None):
    if translations is None:
        translations = i18n.load_store()
    cat_name = {c.id: c.name for c in cats}
    now = payload["generated_at"][:16].replace("T", " ")
    counts = payload["counts"]
    done, pending, native = i18n.coverage(payload["results"])

    grouped = {cid: [] for cid in cat_name}
    for item in payload["results"]:
        primary = primary_of(item["categories"])
        item["primary_category"] = primary
        grouped.setdefault(primary, []).append(item)

    nav, sections = [], []
    for cid, name in cat_name.items():
        items = sorted(grouped.get(cid, []), key=lambda x: x["score"]["total"], reverse=True)
        nav.append(f'<a href="#sec-{_e(cid)}">{_e(name)}<span class="n">{len(items)}</span></a>')
        body = "".join(_card_html(it, name, translations) for it in items) \
            if items else '<p class="empty">本轮无入选项目。</p>'
        sections.append(
            f'<section class="cat" id="sec-{_e(cid)}"><h2>{_e(name)}'
            f'<span class="pill">{len(items)} 个</span></h2>{body}</section>')

    if pending:
        notice = (f"简介中文翻译：{done} 条已译 / {native} 条原文即中文 / {pending} 条待译"
                  f"（radar.py translate --todo 导出待译清单，填好后 --apply 写回）。")
    elif done:
        notice = f"简介中文翻译：{done} 条英文简介已全部翻译，另有 {native} 条原文即中文。"
    else:
        notice = ""

    news_html = _news_html(payload.get("news", []), payload.get("news_failures", []),
                            payload.get("news_translations"))
    news_nav = ('<a href="#sec-news">📰 AI 资讯'
                f'<span class="n">{len(payload.get("news", []))}</span></a>') if news_html else ""

    rejected = ""
    if payload.get("rejected"):
        rows = "".join(f"<li><code>{_e(rj['full_name'])}</code> — {_e(rj['reason'])}</li>"
                       for rj in payload["rejected"][:15])
        rejected = (f'<details class="rejected"><summary>附：淘汰记录'
                    f'（前 15 条，共 {len(payload["rejected"])} 条）</summary>'
                    f'<ul>{rows}</ul></details>')

    today = datetime.now().strftime("%Y-%m-%d")
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI 开源雷达报告 · {_e(now)}</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  <header class="hero">
    <h1>📡 AI 开源雷达报告</h1>
    <div class="meta">
      <span>生成时间 <b>{_e(now)}</b></span>
      <span>trending 口径 <b>{_e(payload['since'])}</b></span>
      <span>模式 <b>{_e(payload['mode'])}</b></span>
      <span>通路 <b>{_e(payload['token_source'])}</b></span>
      <span>候选 <b>{counts['candidates']}</b> · 入选 <b>{counts['selected']}</b> · 淘汰 <b>{counts['rejected']}</b></span>
    </div>
    <div class="notice">全局规则：AI 模型本体开发（权重仓 / 训练推理引擎 / 论文复现）已硬排除。
      额度政策变动快，信息截至 {today}，使用前以官方页面为准。</div>
    {f'<div class="notice">{_e(notice)}</div>' if notice else ""}
  </header>
  <nav class="tabs">{"".join(nav)}{news_nav}</nav>
  {"".join(sections)}
  {news_html}
  {rejected}
  <footer>由 ai-git-radar 生成 · 单文件离线报告 · 数据来源 GitHub + RSS/Atom 资讯信源</footer>
</div>
</body>
</html>"""


def render_news_html(payload, translations=None):
    """只含资讯的自包含单文件 HTML（radar news 的 HTML 产物）。

    复用主报告的 CSS 与 _news_html，不依赖任何 GitHub 项目数据。
    """
    if translations is None:
        translations = i18n.load_news_store()
    news = payload.get("news", [])
    failures = payload.get("news_failures", [])
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    done, pending, native = i18n.news_coverage(news)
    if pending:
        notice = (f"资讯标题翻译：{done} 条已译 / {native} 条原文即中文 / {pending} 条待译"
                  "（radar.py translate --news --todo 导出，填好后 --news --apply 写回）。")
    elif done:
        notice = f"资讯标题翻译：{done} 条英文标题已全部翻译，另有 {native} 条原文即中文。"
    else:
        notice = ""
    body = _news_html(news, failures, translations) or '<p class="empty">本轮无资讯条目。</p>'
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI 资讯速递 · {_e(now)}</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  <header class="hero">
    <h1>📰 AI 资讯速递</h1>
    <div class="meta">
      <span>生成时间 <b>{_e(now)}</b></span>
      <span>资讯条目 <b>{len(news)}</b></span>
      <span>失败信源 <b>{len(failures)}</b></span>
    </div>
    {f'<div class="notice">{_e(notice)}</div>' if notice else ""}
  </header>
  {body}
  <footer>由 ai-git-radar 生成 · 单文件离线报告 · 数据来源 RSS/Atom 资讯信源（零密钥）</footer>
</div>
</body>
</html>"""
