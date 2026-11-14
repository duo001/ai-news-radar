# -*- coding: utf-8 -*-
"""离线自测：不发网络请求，用内置样本验证分类/检测/评分逻辑。

    python3 selftest.py
全部断言通过退出码 0，可作为改完规则后的回归检查。
"""
import detectors
import registry
import scorer


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print("  ✓", msg)


# ---- [15] SQLite 存储层 ----
def test_sqlite():
    import tempfile, os
    import db as dbm
    tmp = tempfile.mktemp(suffix=".db")
    try:
        dbm.init_db(tmp)
        check(dbm.count(tmp) == 0, "初始空库")
        # UPSERT 两条（用相对日期，避免硬编码过期）
        import datetime as _dt
        d5 = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=5)).isoformat()
        d1 = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=1)).isoformat()
        dbm.upsert_news([
            {"link": "https://a/1", "title": "A1", "summary": "s1", "published": d5,
             "source_id": "src", "source_name": "Src", "group": "厂商官方", "kind": "rss"},
            {"link": "https://a/2", "title": "A2", "published": d1,
             "source_id": "src", "source_name": "Src", "group": "厂商官方"},
        ], path=tmp)
        check(dbm.count(tmp) == 2, "写入两条")
        # 相同 link 覆盖（UPSERT）
        dbm.upsert_news([
            {"link": "https://a/1", "title": "A1-新标题", "published": "2026-11-10T00:00:00+00:00",
             "source_id": "src", "source_name": "Src", "group": "厂商官方", "kind": "rss"},
        ], path=tmp)
        check(dbm.count(tmp) == 2, "UPSERT 不新增行")
        rows = dbm.query_news(path=tmp)
        check(len(rows) == 2, "查询全表")
        a1 = next(r for r in rows if r["link"] == "https://a/1")
        check(a1["title"] == "A1-新标题", "UPSERT 覆盖标题")
        # 按 group 过滤
        rows_g = dbm.query_news(path=tmp, group="厂商官方")
        check(len(rows_g) == 2, "按 group 过滤")
        # 保留策略：清理 3 天前的，5 天前那条被清，1 天前那条保留
        pruned = dbm.prune_old(path=tmp, days=3)
        check(pruned == 1, "prune_old 清理超期条目")
        check(dbm.count(tmp) == 1, "未超期条目保留")
        # 空值 published 不被清理（防御）
        dbm.upsert_news([
            {"link": "https://b/x", "title": "NoDate", "source_id": "s", "source_name": "S", "group": "其他"},
        ], path=tmp)
        check(dbm.count(tmp) == 2, "无日期条目写入（1 天前 + 无日期）")
        dbm.prune_old(path=tmp, days=1)
        check(dbm.count(tmp) == 1, "无日期条目不被 prune_old 清除")
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def main():
    print("[1] 类目加载与扩展机制")
    cats = registry.load_categories()
    ids = {c.id for c in cats}
    check(ids == {"ai-tools", "free-tokens", "ai-tech", "agent-skills"},
          f"四个类目齐全: {ids}")
    at, ft, tech, ask = (next(c for c in cats if c.id == i) for i in
                         ("ai-tools", "free-tokens", "ai-tech", "agent-skills"))
    check(ft.keep_lists is True, "免费/优惠类豁免清单排除")
    check(tech.max_age_days == 120, "技术类目有 120 天年龄上限")
    check(getattr(ask, "max_age_days", None) is None, "生态类目不设年龄上限")

    print("[2] 分类词边界与强弱词")
    check(registry.match_category(at, "thealgorithms java algorithms") is False,
          "ai 不误命中无关项目")
    check(registry.match_category(at, "an ai agent framework with llm") is True,
          "强词命中正常准入")
    check(registry.match_category(at, "machine learning based system") is False,
          "单个弱词不准入")
    check(registry.match_category(at, "machine learning 与人工智能结合") is True,
          "两个弱词准入")
    check(registry.match_category(at, "some tool", "llm,rag") is True,
          "topic 交集准入（逗号分隔兼容）")
    # 协议词/协议标签的 AI 亲和度：非 AI 应用单挂一个 mcp 不准入
    gym_topics = ("apple-watch bodyweight docker fitness gym health ios mcp nodejs "
                  "pwa react weightlifting workout-tracker")
    check(registry.match_category(at, "open-source gym body-weight tracker, log workouts",
                                  gym_topics) is False,
          "健身 App 单挂 mcp 标签不准入（openGym 回归）")
    check(registry.match_category(at, "an mcp server for llm agents to query data",
                                  "mcp llm") is True,
          "mcp 有 llm 身份词佐证时准入")
    check(registry.match_category(at, "note app with rag search", "note-taking rag") is False,
          "笔记软件单挂 rag 标签不准入")
    check(registry.match_category(at, "mcp 接口的智能体编排平台", "mcp workflow") is True,
          "中文身份词（智能体）佐证协议词准入")
    check(registry.match_category(at, "local-first cross-platform video editor, scriptable via mcp",
                                  "video-editor model-context-protocol ffmpeg voice-cloning") is False,
          "视频编辑器单挂 model-context-protocol 不准入（Concat 回归）")

    print("[3] 免费额度检测")
    d = detectors.detect_token_offer(
        "free tier, $5 free credits, no credit card required. Free API key for LLM.")
    check(d and d["is_free_token"], "免费额度识别")
    check("无需信用卡" in d["signup"] and "需信用卡" not in d["signup"],
          "否定式信用卡不误判")

    print("[4] 优惠活动检测与语境过滤")
    p = detectors.detect_token_offer(
        "首充送 20% credits，限时 50% off，黑五 coupon，OpenAI API token 聚合。")
    check(p and p["has_promo"] and "优惠活动" in p["offer_type"], "优惠活动识别")
    check(detectors.detect_token_offer("Black Friday 80% off VPN, coupon.") is None,
          "无 token 语境的折扣被拒绝")

    print("[5] 网关形态准入")
    g = detectors.detect_token_offer("one-api 分发 OpenAI/Anthropic 的 API key，负载均衡。")
    check(g and any("网关" in f for f in g["form"]), "one-api 网关形态准入")

    print("[6] 安全风险（两种中文语序）")
    r1 = detectors.detect_risks("把你的 OpenAI api key 粘贴到本站平台。")
    r2 = detectors.detect_risks("请在本服务填入 api key 后使用。")
    check(any(x["level"] == "high" for x in r1), "key 在前语序判高风险")
    check(any(x["level"] == "high" for x in r2), "动词在前语序判高风险")

    print("[7] 评分与高风险压级")
    repo = {"stars": 5000, "gained": 300, "pushed_at": "2026-11-10T00:00:00Z",
            "created_at": "2026-10-01T00:00:00Z", "open_issues": 20,
            "license": "MIT", "homepage": "x", "topics": ["llm"], "desc": "x"}
    eng = {"has_one_click": True, "has_deploy_doc": True, "has_docker": True,
           "has_demo": True, "has_chinese": True, "has_cloud_button": False}
    s = scorer.score(repo, at, eng, None)
    check(0 <= s["total"] <= 100 and s["grade"] in "SABC", f"评分合法: {s['total']} {s['grade']}")
    risky = scorer.score(repo, ft, eng, {"risks": [{"level": "high", "note": "x"}], "china": ""})
    check(risky["grade"] not in ("S", "A"), "高风险项目强制不超过 B 级")

    print("[8] 模型定义/训练框架排除（用户硬要求：不含模型本体开发）")
    import classify as classify_mod
    rules = registry.load_global()
    tf = {"full_name": "huggingface/transformers", "name": "transformers",
          "desc": "the model-definition framework for machine learning models, for both inference and training",
          "topics": ["pretrained-models", "model-hub", "llm"], "stars": 100000}
    check(classify_mod.is_model_body(tf, "", rules), "transformers 类模型框架被排除")
    app = {"full_name": "x/dify", "name": "dify",
           "desc": "build agentic workflows and RAG pipelines", "topics": ["ai", "rag"], "stars": 100000}
    check(not classify_mod.is_model_body(app, "", rules), "应用层框架不被误伤")

    print("[9] 网页星数解析（多代页面结构）")
    import gh_client
    check(gh_client._scrape_stars('<span id="repo-stars-counter-star" title="210,237">210k</span>') == 210237,
          "现代 title 锚点")
    check(gh_client._scrape_stars('<a href="/o/r/stargazers"><span>12,345</span></a>') == 12345,
          "旧版 stargazers 链接")
    check(gh_client._scrape_stars("<div>nothing</div>") == 0, "失配返回 0（不覆盖真值）")

    print("[10] 中文翻译流水线")
    import tempfile
    import pathlib
    import i18n
    tmp = pathlib.Path(tempfile.mkdtemp())
    old_store, old_todo = i18n.STORE, i18n.TODO
    i18n.STORE, i18n.TODO = tmp / "translations.json", tmp / "todo_translate.json"
    try:
        check(i18n.has_cjk("一个 AI 智能体框架") and not i18n.has_cjk("an ai agent framework"),
              "中文检测区分中英文简介")
        sample = {"results": [
            {"repo": {"full_name": "o/repo-en", "desc": "An AI agent framework for builders."}},
            {"repo": {"full_name": "o/repo-cn", "desc": "一个中文项目，自带中文简介。"}},
            {"repo": {"full_name": "o/repo-empty", "desc": ""}},
        ]}
        todo = i18n.build_todo(sample["results"])
        keys = {it["key"] for it in todo["items"]}
        check(keys == {"o/repo-en"}, "待译清单只收英文简介（中文/空简介跳过）")
        todo["items"][0]["zh"] = "面向开发者的 AI 智能体框架。"
        i18n.write_todo(todo)
        added, skipped = i18n.apply_todo()
        check(added == 1 and skipped == 0, "apply 合并 1 条翻译")
        check(i18n.lookup("o/repo-en") == "面向开发者的 AI 智能体框架。", "翻译库可查")
        # 二次 apply 不覆盖已存在的精译
        todo["items"][0]["zh"] = "被覆盖的错误翻译"
        i18n.write_todo(todo)
        added2, skipped2 = i18n.apply_todo()
        check(added2 == 0 and i18n.lookup("o/repo-en").startswith("面向开发者"),
              "已翻译内容不被二次 apply 覆盖")
        done, pending, native = i18n.coverage(sample["results"])
        check((done, pending, native) == (1, 0, 1), "覆盖率统计（已译/待译/原文中文）")
    finally:
        i18n.STORE, i18n.TODO = old_store, old_todo

    print("[11] Agent 生态类目与 HTML 报告")
    check(registry.match_category(ask, "a collection of claude code skills and agents",
                                  "claude-code agent-skills") is True,
          "skill/claude-code 身份词准入生态类目")
    check(registry.match_category(ask, "generic todo web app", "react todo") is False,
          "无关项目不混入生态类目")
    # 严格模式：单个生态 topic + 泛 AI 身份词不准入（OpenMausBot 类回归）
    check(registry.match_category(ask, "open-source grok bot with a virtual machine",
                                  "claude-code ai-agents") is False,
          "通用 Bot 单挂 claude-code 标签不混入生态类目（严格模式）")
    # 同一项目若描述里确有 skill/harness 专属词则准入
    check(registry.match_category(ask, "claude code skills pack for game modding",
                                  "claude-code") is True,
          "描述含 skill 专属词时准入")
    # 两个生态 topic 即准入，无需强词
    check(registry.match_category(ask, "an mcp integration",
                                  "claude-code cursor-rules") is True,
          "两个生态 topic 准入")
    # 通用 mcp/ai-agent topic 已从本类目录移除，不能再作为生态准入依据
    check(registry.match_category(ask, "mcp server for data query", "mcp ai-agent") is False,
          "通用 mcp/ai-agent 标签不再混入生态类目")
    # topic 名不得冒充关键词：name/desc 无 skill 词，仅挂一个 "skills" topic 不准入
    # （dify/JavaGuide 回归——它们的 skills 只是兼容性标签，不是生态资产）
    check(registry.match_category(ask, "build agentic workflows and rag pipelines",
                                  "skills workflow mcp llm") is False,
          "skills topic 名不冒充 skill 关键词（dify 回归）")
    check(registry.match_category(ask, "java interview and backend study guide",
                                  "skills java interview mysql") is False,
          "学习指南挂 skills topic 不混入生态类（JavaGuide 回归）")
    import report as report_mod
    import html_report
    check(report_mod.primary_of(["ai-tools", "agent-skills"]) == "agent-skills",
          "主归属：生态类目优先于通用工具")
    check(report_mod.primary_of(["free-tokens", "agent-skills"]) == "free-tokens",
          "主归属：免费/优惠类最优先")
    mini = {
        "generated_at": "2026-11-12T16:00:00+08:00", "since": "daily", "mode": "quick",
        "token_source": "匿名（网页/raw 通路）",
        "counts": {"candidates": 1, "selected": 1, "rejected": 0},
        "results": [{
            "repo": {"full_name": "o/sample-skill", "name": "sample-skill",
                     "desc": "A <b>skill</b> pack & toolkit", "topics": ["agent-skills"],
                     "stars": 1234, "lang": "Python", "license": "MIT"},
            "categories": ["agent-skills"],
            "score": {"total": 72.5, "grade": "A",
                      "dims": {"热度与增速": 20, "项目健康度": 15, "技术前沿度": 12,
                               "可上手性": 10, "国内与中文": 9, "风险与合规": 6.5}},
            "eng": {"has_demo": True, "has_docker": False, "has_one_click": False,
                    "has_chinese": True, "has_deploy_doc": True, "has_cloud_button": False},
            "detector": None,
        }],
        "rejected": [],
    }
    html = html_report.render_html(mini, cats, translations={})
    check(html.lstrip().startswith("<!DOCTYPE html>"), "HTML 是完整文档")
    check('id="o/sample-skill"' in html, "卡片锚点生成")
    check("A &lt;b&gt;skill&lt;/b&gt; pack &amp; toolkit" in html, "HTML 特殊字符已转义")
    check("sec-agent-skills" in html and "Agent 生态" in html, "生态类目分区渲染")
    check("width:80%" in html, "六维分数条按满分换算百分比")

    print("[12] RSS/Atom 资讯信源")
    import gzip as _gzip
    import feeds
    import report as report_mod
    src = {"id": "t", "name": "Test Feed", "group": "测试分组", "url": "http://x"}
    rss = """<?xml version="1.0"?><rss version="2.0"><channel>
      <item><title><![CDATA[GPT-5 发布 & 新功能]]></title>
      <link>https://x.com/a</link><description>&lt;p&gt;Hello &amp;amp; world&lt;/p&gt;</description>
      <pubDate>Thu, 12 Nov 2026 10:00:00 GMT</pubDate></item>
      <item><title>无链接项应被丢弃</title><description>x</description></item>
      </channel></rss>"""
    items = feeds.parse_feed(rss, src)
    check(len(items) == 1, "RSS 解析且丢弃无链接条目")
    check(items[0]["title"] == "GPT-5 发布 & 新功能", "CDATA 标题正确解码")
    check("<" not in items[0]["summary"] and "Hello & world" in items[0]["summary"],
          "HTML 标签清洗与实体解码")
    check(items[0]["published"] is not None and items[0]["published"].tzinfo is not None,
          "RFC822 日期解析为带时区 datetime")

    atom = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
      <entry><title>Atom 条目</title>
      <link rel="alternate" href="https://x.com/b"/>
      <published>2026-11-11T08:30:00Z</published>
      <summary type="html">&lt;b&gt;粗体&lt;/b&gt;摘要</summary></entry></feed>"""
    ait = feeds.parse_feed(atom, src)
    check(len(ait) == 1 and ait[0]["link"] == "https://x.com/b", "Atom entry 与 link@href 解析")
    check(ait[0]["summary"] == "粗体摘要", "Atom HTML summary 清洗")
    check(ait[0]["published"].year == 2026, "Atom ISO8601(Z) 日期解析")

    # gzip 强制解压（deepmind.google 的坑）
    raw = _gzip.compress(rss.encode("utf-8"))
    check(feeds._decode_body(raw, "gzip").startswith("<?xml"), "按 Content-Encoding 解压 gzip")
    check(feeds._decode_body(raw, "").startswith("<?xml"), "按魔数 1f8b 解压无标识 gzip")

    # 坏 XML 抛 FeedError 而不是裸异常
    try:
        feeds.parse_feed("<not-valid", src)
        raise AssertionError("坏 XML 应抛 FeedError")
    except feeds.FeedError:
        print("  ✓ 坏 XML 抛 FeedError（单源容错）")

    # style/script 整块与 CSS 注释清洗（GitHub 字体版权、MS 样式混入的坑）
    noisy = ('<style>.a{color:red}</style>/* Copyright Font */'
             '<p>Real <b>summary</b> here.</p><script>var x=1;</script><!-- c -->')
    cleaned = feeds._strip_html(noisy)
    check("{" not in cleaned and "Copyright" not in cleaned and "var x" not in cleaned
          and "Real summary here." in cleaned, "style/script/CSS 注释噪声被清除且正文保留")
    check("{name}" in feeds._strip_html("<p>keep {name} placeholder</p>"),
          "正常花括号文本不被样式规则正则误伤")

    # 资讯渲染进 Markdown 与 HTML
    news_payload = {"news": [
        {"title": "资讯甲", "link": "https://x/a", "summary": "摘要甲",
         "published": "2026-11-12T10:00:00+00:00", "source_id": "t",
         "source_name": "Test Feed", "group": "测试分组"}],
        "news_failures": [{"id": "dead", "name": "失效源", "error": "超时"}]}
    md_news = report_mod.render_news_markdown(news_payload)
    check("资讯甲" in md_news and "失效源" in md_news, "独立资讯 Markdown 渲染含失败标注")
    mini["news"] = news_payload["news"]
    mini["news_failures"] = news_payload["news_failures"]
    html2 = html_report.render_html(mini, cats, translations={})
    check('id="sec-news"' in html2 and "资讯甲" in html2 and "失效源" in html2,
          "HTML 报告含资讯分区与失败信源标注")

    print("[13] 资讯翻译流水线与并发抓取")
    import tempfile, pathlib as _pl
    entries = [
        {"title": "OpenAI Ships New Model", "link": "https://x/e1",
         "summary": "English summary one", "published": None,
         "source_id": "t", "source_name": "Test", "group": "g"},
        {"title": "国产模型发布新版", "link": "https://x/e2",
         "summary": "原生中文摘要", "published": None,
         "source_id": "t", "source_name": "Test", "group": "g"},
        {"title": "AWS Cuts Bedrock Price", "link": "https://x/e3",
         "summary": "English summary three", "published": None,
         "source_id": "t", "source_name": "Test", "group": "g"},
    ]
    with tempfile.TemporaryDirectory() as td:
        td = _pl.Path(td)
        # 重定向资讯翻译库与待译清单到临时目录
        i18n.NEWS_STORE = td / "news_translations.json"
        i18n.NEWS_TODO = td / "todo_news.json"
        todo = i18n.build_news_todo(entries)
        check(len(todo["items"]) == 2, "build_news_todo 只收英文且跳过原生中文")
        check(all(it["zh_title"] == "" for it in todo["items"]), "待译条目 zh_title 初始为空")
        # 填前两条英文（含一条只填标题）
        todo["items"][0]["zh_title"] = "OpenAI 发布新模型"
        todo["items"][0]["zh_summary"] = "英文摘要一的译文"
        todo["items"][1]["zh_title"] = "AWS 下调 Bedrock 价格"
        i18n.write_news_todo(todo)
        added, skipped = i18n.apply_news_todo()
        check(added == 2 and skipped == 0, "apply_news_todo 合并新译文")
        # 再 apply 一次：不覆盖已存在
        added2, skipped2 = i18n.apply_news_todo()
        check(added2 == 0 and skipped2 == 2, "重复 apply 不覆盖已有译文")
        done, pending, native = i18n.news_coverage(entries)
        check((done, pending, native) == (2, 0, 1),
              f"news_coverage 统计正确（已译{done}/待译{pending}/原生{native}）")
        store = i18n.load_news_store()
        tr1 = store["https://x/e1"]
        check(tr1["zh_title"] == "OpenAI 发布新模型" and tr1["zh_summary"],
              "翻译库按 link 建 key 且含标题与摘要")

        # 译文渲染进 md 与 html
        p2 = {"news": entries, "news_failures": [], "news_translations": store}
        md2 = report_mod.render_news_markdown(p2)
        check("OpenAI 发布新模型" in md2 and "英文摘要一的译文" in md2
              and "原标题：OpenAI Ships New Model" in md2,
              "资讯 Markdown 显示中文标题/摘要并保留原标题")
        check("国产模型发布新版" in md2, "原生中文条目正常显示")
        html3 = html_report.render_news_html(p2, store)
        check('id="sec-news"' in html3 and "OpenAI 发布新模型" in html3
              and "英文摘要一的译文" in html3 and html3.lstrip().startswith("<!DOCTYPE html>"),
              "独立资讯 HTML 含译文且为完整文档")
        # HTML 转义仍生效
        p3 = {"news": [{"title": "A & B <script>", "link": "https://x/e4",
                        "summary": "", "published": None, "source_id": "t",
                        "source_name": "T", "group": "g"}],
              "news_failures": [], "news_translations": {}}
        check("<script>" not in html_report.render_news_html(p3, {}),
              "资讯 HTML 对特殊字符转义")

    # 并发 workers=1 与默认 workers 对同一缓存源结果一致（离线、确定性）
    one, fail1, _ = feeds.fetch_all(only="", offline=True, per_source_limit=3,
                                 log=lambda *_: None, workers=1)
    many, failm, _ = feeds.fetch_all(only="", offline=True, per_source_limit=3,
                                  log=lambda *_: None, workers=8)
    check(len(one) == len(many) and {e["link"] for e in one} == {e["link"] for e in many},
          f"并发与串行抓取条目一致（{len(one)} 条，离线缓存）")

    print("[14] 信源自动发现与健康检查")
    import discover
    import json
    import urllib.error as _urlerr

    rss_feed = """<?xml version="1.0"?><rss version="2.0"><channel><title>Probe Feed</title>
      <item><title>Probe item</title><link>https://probe.example/a</link>
      <pubDate>Thu, 12 Nov 2026 10:00:00 GMT</pubDate><description>d</description></item></channel></rss>"""
    page_html = ('<!doctype html><head>'
                 '<link rel="alternate" type="application/rss+xml" title="RSS" href="/feed.xml">'
                 '<link rel="alternate" type="text/html" href="/not-a-feed">'
                 '<link rel="alternate" type="application/atom+xml" '
                 'title="Comments" href="https://blog.example/comments/feed/"></head>')
    opml = """<?xml version="1.0"?><opml><body>
      <outline title="Probe" text="Probe" type="rss"
        xmlUrl="https://probe.example/feed.xml" htmlUrl="https://probe.example/"/>
      <outline text="Dup" type="rss" xmlUrl="HTTPS://Probe.Example/feed.xml/"/>
      <outline text="NoUrl" type="rss"/>
      </body></opml>"""
    opml2 = opml.replace(
        'xmlUrl="https://probe.example/feed.xml"',
        'xmlUrl="https://probe.example/second.xml"').replace(
        'xmlUrl="HTTPS://Probe.Example/feed.xml/"',
        'xmlUrl="https://probe.example/second.xml/"')

    with tempfile.TemporaryDirectory() as td:
        td = _pl.Path(td)
        # 全部落盘路径重定向到临时目录，绝不污染真实 data/
        discover.SUGGESTIONS_FILE = td / "source-suggestions.json"
        feeds.FEEDS_CONF = td / "feeds.json"
        feeds.HEALTH_FILE = td / "source-health.json"
        feeds.save_conf({"sources": [
            {"id": "old", "name": "Old", "url": "https://old.example/rss",
             "kind": "rss", "group": "g", "enabled": True},
            {"id": "manual-off", "name": "M", "url": "https://m.example/rss",
             "kind": "rss", "group": "g", "enabled": False, "manual_disabled": True},
        ]})

        # _http_get 打桩：按 URL 返回首页/feed/OPML/404
        def fake_get(url, accept="*/*"):
            if url == "https://path.example/":
                return "<html><head></head><body>no feed links</body></html>", url
            if "path.example" in url and url.endswith("/feed.xml"):
                return rss_feed, url                    # 常见路径探测命中
            if url.startswith("https://blog.example/") and "feed.xml" not in url:
                return page_html, url
            if "probe.example" in url or url.endswith("/feed.xml"):
                return rss_feed, url  # final_url 保持请求 URL，模拟无重定向
            if url.endswith("catalog.opml"):
                return opml, url
            if url.endswith("catalog2.opml"):
                return opml2, url
            raise _urlerr.URLError("boom")
        discover._http_get = fake_get

        # 通道 1：网页 link 标签发现，相对路径转绝对、非 feed 类型过滤、评论 feed 剔除
        cands = discover.discover_from_page(
            {"url": "https://blog.example/", "name": "B", "group": "科技媒体"})
        check(cands == ["https://blog.example/feed.xml"],
              f"网页发现只留有效 RSS 链接（过滤 text/html 与评论 feed）: {cands}")

        # 待审队列四态：added → duplicate → exists → invalid
        data = discover.load_suggestions()
        st1, _ = discover.add_suggestion(
            data, "https://probe.example/feed.xml", found_via="测试",
            group="科技媒体", name="Probe")
        check(st1 == "added" and data["suggestions"][0]["item_count"] == 1,
              "add_suggestion 验证通过后入队且记录条目数")
        st2, _ = discover.add_suggestion(
            data, "HTTPS://probe.example/feed.xml/", found_via="测试",
            group="g", name="Dup")
        check(st2 == "duplicate", "URL 归一化后重复入队被判 duplicate")
        st3, _ = discover.add_suggestion(
            data, "https://old.example/rss", found_via="测试", group="g")
        check(st3 == "exists", "已在信源表的 URL 判 exists")
        st4, _ = discover.add_suggestion(
            data, "https://dead.example/feed", found_via="测试", group="g")
        check(st4 == "invalid", "无法验证的 feed 判 invalid 且不入队")
        discover.save_suggestions(data)

        # 通道 1b：整轮网页发现（并发抓种子站 + 并发验证）
        seeds = [{"name": "BlogB", "url": "https://blog.example/", "group": "科技媒体"},
                 {"name": "PathSite", "url": "https://path.example/", "group": "学术研究"},
                 {"name": "DeadSite", "url": "https://dead.example/", "group": "其他"}]
        (td / "seeds.json").write_text(
            json.dumps({"seeds": seeds}, ensure_ascii=False), encoding="utf-8")
        wstats = discover.run_web_discovery(str(td / "seeds.json"), log=lambda *_: None)
        check(wstats["seeds"] == 3 and wstats["errors"] == 1, "整轮发现统计：不可达站点计 errors")
        q = discover.load_suggestions()
        urls = {s["url"] for s in q["suggestions"]}
        check("https://blog.example/feed.xml" in urls,
              "整轮发现：link 标签通道命中")
        check("https://path.example/feed.xml" in urls,
              "整轮发现：无 link 声明时常见路径探测命中")
        check(not any("comments" in u for u in urls), "整轮发现：评论 feed 未入队")

        # 通道 2：OPML 解析去重（大小写/尾斜杠归一）+ 无 xmlUrl 跳过
        entries = discover.parse_opml(opml)
        check(len(entries) == 1 and entries[0]["name"] == "Probe",
              f"OPML 只提有效 xmlUrl 且归一去重: {len(entries)} 条")
        (td / "catalog.opml").write_text(opml, encoding="utf-8")
        stats = discover.run_opml_import(str(td / "catalog.opml"), log=lambda *_: None)
        check(stats["entries"] == 1 and stats["duplicate"] == 1 and stats["added"] == 0,
              "OPML 导入统计：已在待审队列的记 duplicate")
        # 另一份含新源的 OPML：验证 added 路径与重复条目同文件归一
        (td / "catalog2.opml").write_text(opml2, encoding="utf-8")
        stats2 = discover.run_opml_import(str(td / "catalog2.opml"), log=lambda *_: None)
        check(stats2["entries"] == 1 and stats2["added"] == 1,
              "OPML 新源验证通过后 added")

        # 采纳：写回 feeds.json 且条目状态变 accepted；忽略不写信源表
        discover.save_suggestions(data)
        sid = data["suggestions"][0]["id"]
        changed = discover.set_status([sid], "accepted")
        check(len(changed) == 1 and changed[0]["status"] == "accepted", "采纳更新队列状态")
        conf = feeds.load_conf()
        check(any(s["id"] == sid and s["enabled"] for s in conf["sources"]),
              "采纳的信源写回 feeds.json 并默认启用")
        # 再采一个待忽略项
        d_live = discover.load_suggestions()
        st5, _ = discover.add_suggestion(
            d_live, "https://probe.example/other.xml",
            found_via="测试", group="g", name="Other")
        # other.xml 也能通过桩验证（含 probe.example 域名）
        check(st5 == "added", f"第二个新源入队（实际 {st5}）")
        discover.save_suggestions(d_live)
        n_before = len(feeds.load_conf()["sources"])
        d2 = discover.load_suggestions()
        other_id = next(s["id"] for s in d2["suggestions"]
                        if s["url"] == "https://probe.example/other.xml")
        discover.set_status([other_id], "ignored")
        check(len(feeds.load_conf()["sources"]) == n_before,
              "忽略不写回信源表")

        # 健康检查：连续 3 次失败自动停用，成功一次重置；手动停用不被自动逻辑改写
        feeds.record_health(set(), {"old": "timeout"}, log=lambda *_: None)
        feeds.record_health(set(), {"old": "timeout"}, log=lambda *_: None)
        h2 = feeds.record_health(set(), {"old": "timeout"}, log=lambda *_: None)
        check(h2["old"]["consecutive_failures"] == 3 and h2["old"].get("auto_disabled"),
              "连续失败达阈值写 auto_disabled 标记")
        old_row = next(s for s in feeds.load_conf()["sources"] if s["id"] == "old")
        check(old_row["enabled"] is False and "健康检查自动停用" in old_row.get("disabled_reason", ""),
              "健康检查自动停用信源并写明原因")
        # manual_disabled 源即使失败 3 次也不被自动逻辑触碰
        feeds.record_health(set(), {"manual-off": "x"}, log=lambda *_: None)
        feeds.record_health(set(), {"manual-off": "x"}, log=lambda *_: None)
        feeds.record_health(set(), {"manual-off": "x"}, log=lambda *_: None)
        m_row = next(s for s in feeds.load_conf()["sources"] if s["id"] == "manual-off")
        check(m_row.get("manual_disabled") is True and "健康检查" not in m_row.get("disabled_reason", ""),
              "手动停用源受保护，健康检查不覆盖其停用原因")
        # 成功重置
        h3 = feeds.record_health({"old"}, set(), log=lambda *_: None)
        check(h3["old"]["consecutive_failures"] == 0 and "last_error" not in h3["old"],
              "成功采集一次即重置失败计数")

    print("[15] SQLite 存储层")
    test_sqlite()
    print("\n全部自测通过 ✅")


if __name__ == "__main__":
    main()
