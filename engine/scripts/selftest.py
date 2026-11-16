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


# ---- [16] 免费机翻通道（不联网，mock 翻译调用）----
def test_mt():
    import tempfile, os, json, pathlib as _pl
    import i18n, mt

    # 1) 双预算切片：条数上限与字符上限都生效
    chunks = mt._chunk_texts(["a" * 100] * 10, 4, 250)
    check(len(chunks) == 5, "字符预算把每批压到 2 条（100+100=200，第三条 300>250）")
    check(sum(len(c) for c in chunks) == 10, "切片不丢文本")
    check(all(len(c) <= 4 for c in chunks), "切片遵守条数上限")
    check(all(sum(len(t) for t in c) <= 250 for c in chunks), "切片遵守字符上限")
    # 单条超预算也不死循环（自成一批）
    big = mt._chunk_texts(["x" * 999], 4, 250)
    check(big == [["x" * 999]], "超长单条自成一批")

    # 2) 摘要补译：已有译文但摘要空缺的条目要重新进清单（只补摘要）
    tmp0 = tempfile.mktemp(suffix=".json")
    old0 = i18n.NEWS_STORE
    i18n.NEWS_STORE = _pl.Path(tmp0)
    try:
        i18n.save_news_store({
            "https://x/1": {"zh_title": "已有标题", "zh_summary": "", "source_title": "T"},
            "https://x/2": {"zh_title": "完整", "zh_summary": "有摘要"},
        })
        todo = i18n.build_news_todo([
            {"link": "https://x/1", "title": "T", "summary": "English summary"},
            {"link": "https://x/2", "title": "U", "summary": "done"},
            {"link": "https://x/3", "title": "Fresh", "summary": "New"},
        ])["items"]
        by = {i["link"]: i for i in todo}
        check(by["https://x/1"].get("only_summary") is True, "标题已译/摘要空缺 → 摘要补译任务")
        check("https://x/2" not in by, "完整译文不再进清单")
        check(by["https://x/3"].get("only_summary") is None, "新条目走完整翻译")
    finally:
        i18n.NEWS_STORE = old0
        if _pl.Path(tmp0).exists():
            _pl.Path(tmp0).unlink()

    tmp = tempfile.mktemp(suffix=".json")
    old_store = i18n.NEWS_STORE
    i18n.NEWS_STORE = _pl.Path(tmp)
    real_batch = mt.translate_batch
    calls = {}

    def fake_batch(texts, log=None, provider=None):
        calls["texts"] = list(texts)
        out = []
        for t in texts:
            out.append("译:" + t[:20])
        return out, "fake"

    mt.translate_batch = fake_batch
    try:
        entries = [
            {"link": "https://x/1", "title": "Hello world", "summary": "Sum one"},
            {"link": "https://x/2", "title": "Second title", "summary": ""},
            {"link": "https://x/3", "title": "已经是中文标题", "summary": ""},
            {"link": "https://x/4", "title": "", "summary": "no title"},
        ]
        stat = i18n.auto_translate_news(entries, log=lambda *_: None)
        check(stat["translated"] == 2, "英文标题翻 2 条（中文标题/空标题跳过）")
        check(stat["provider"] == "fake", "记录所用通道")
        # 标题 + 摘要都送翻
        check(len(calls["texts"]) == 3, "提交 2 标题 + 1 摘要共 3 段")
        store = json.loads(_pl.Path(tmp).read_text(encoding="utf-8"))
        check(len(store) == 2 and "https://x/1" in store, "译文入库且 key 是 link")
        check(store["https://x/1"]["zh_summary"].startswith("译:"), "摘要译文一并入库")
        check(store["https://x/1"]["source"] == "auto:fake", "标记来源通道")

        # 2) 幂等：已译的不再送翻
        before = len(calls["texts"])
        stat2 = i18n.auto_translate_news(entries, log=lambda *_: None)
        check(stat2["translated"] == 0 and len(calls["texts"]) == before,
              "已译条目不重复送翻（幂等）")

        # 3) limit 生效
        more = [{"link": f"https://y/{i}", "title": f"Title {i}", "summary": ""}
                for i in range(5)]
        stat3 = i18n.auto_translate_news(more, log=lambda *_: None, limit=2)
        check(stat3["considered"] == 2 and stat3["translated"] == 2, "limit 限制本次条数")

        # 4) 通道全失败时不入库
        mt.translate_batch = lambda texts, log=None, provider=None: (
            [None] * len(texts), "none")
        stat4 = i18n.auto_translate_news(
            [{"link": "https://z/1", "title": "Fails", "summary": ""}],
            log=lambda *_: None)
        check(stat4["translated"] == 0 and stat4["failed"] == 1, "翻译失败不写库")
        store2 = json.loads(_pl.Path(tmp).read_text(encoding="utf-8"))
        check("https://z/1" not in store2, "失败条目不污染翻译库")
    finally:
        mt.translate_batch = real_batch
        i18n.NEWS_STORE = old_store
        if os.path.exists(tmp):
            os.remove(tmp)


# ---- [17] 规则增强（enrich）与结构化采集器（collectors）----
def test_enrich():
    import enrich

    # 形态判定
    check(enrich.form_of("OpenRouter 新免费模型：X (free)") == "freebie",
          "(free)/:free 后缀识别为福利")
    check(enrich.form_of("某平台黑五 5 折优惠") == "deal", "折扣识别为优惠")
    check(enrich.form_of("一篇 arXiv 论文：新的 RAG 方法") == "paper", "论文识别")
    check(enrich.form_of("某框架发布 v2.3.0") == "release", "版本发布识别")
    check(enrich.form_of("普通行业动态一条") == "news", "无信号默认资讯")

    # obtain 仅对福利/优惠有意义，且抽奖优先
    check(enrich.obtain_of("评论区抽 10 份会员，关注后开奖", form="freebie") == "lottery",
          "抽奖形态判 lottery")
    check(enrich.obtain_of("注册送 5 美元额度", form="freebie") == "promo", "注册送判推广")
    check(enrich.obtain_of("某框架发布 v2.3.0", form="release") is None,
          "非福利形态 obtain 为 None")
    check(enrich.obtain_of("OpenRouter 免费模型 (free)", form="freebie") == "free",
          "无附加条件判直接领 free")

    # 领域标签
    tp = enrich.topics_of("Claude 与 GPT 模型的 MCP server 安全漏洞分析")
    check({"模型", "MCP", "安全"} <= set(tp), f"多领域标签命中: {tp}")
    check(len(enrich.topics_of(" ".join(["agent"] * 20))) <= enrich._TOPIC_MAX,
          f"领域标签最多 {enrich._TOPIC_MAX} 个")

    # 通用（非 AI）领域标签 + 短词边界回归（v0.12 扩充分类）
    check("游戏" in enrich.topics_of("Steam 玩家期待 GTA6 新主机游戏发布"), "游戏领域命中")
    check("汽车出行" in enrich.topics_of("比亚迪新款电动车自动驾驶升级，车载座舱体验提升"),
          "汽车出行领域命中")
    check("金融财经" in enrich.topics_of("比特币与区块链支付在银行 fintech 场景落地"),
          "金融财经领域命中")
    # ev 不得命中 ever/every，ar 不得命中 car 之外的子串
    check("汽车出行" not in enrich.topics_of("Every developer should write tests"),
          "ev 词边界：every 不命中汽车")
    check("消费电子" not in enrich.topics_of("Learn regular expressions step by step"),
          "vr 词边界：regular 不命中消费电子")

    # 时政要闻 / 国际资讯（v0.12 新增，三元组规则）
    check("时政要闻" in enrich.topics_of("日本首相宣布大选日期，政府公布选举安排"),
          "时政要闻中文正例")
    check("时政要闻" in enrich.topics_of("US government grounds all flights after FAA order"),
          "时政要闻英文正例")
    check("国际资讯" in enrich.topics_of("中美贸易摩擦升级，G20 峰会将举行磋商"),
          "国际资讯正例")
    check("国际资讯" in enrich.topics_of("欧盟通过新一轮制裁，国际秩序面临调整"),
          "国际资讯正例（欧盟/国际）")
    # 摘要泛词不得把无关资讯误判成时政/国际
    check("时政要闻" not in enrich.topics_of(
        "Xbox Helix 新品发布", "The president of gaming division commented on the launch"),
        "摘要 president 泛词不单独触发时政")
    check("国际资讯" not in enrich.topics_of(
        "Microsoft 365 宕机一天", "Services went down worldwide for enterprise users"),
        "摘要 worldwide 泛词不单独触发国际")
    check("时政要闻" not in enrich.topics_of("War Room 组建以迎接 CEO 回归", ""),
          "商业比喻 war room 不触发时政")
    check("国际资讯" not in enrich.topics_of("DeepSeek Harness – Creator Mode 发布", ""),
          "g7 等子串不误伤（Creator 不含国际信号）")

    # 游戏 IP（Warhammer/战锤）归入游戏
    check("游戏" in enrich.topics_of("Warhammer 40,000: Dawn of War IV is coming"),
          "Warhammer 游戏 IP 命中游戏分类")
    check("时政要闻" not in enrich.topics_of("Warhammer 40,000: Dawn of War IV 即将发售"),
          "Dawn of War 游戏标题不误判时政")

    # deepseek 在 URL/产品名中不算模型词，但真模型新闻仍命中
    check("模型" not in enrich.topics_of("DeepSeek Harness – Creator Mode",
          "Article URL: https://www.reddit.com/r/DeepSeek/s/abc Comments URL: x"),
          "URL 中的 deepseek 不触发模型标签")
    check("模型" not in enrich.topics_of("DeepSeek Harness new Creator Mode",
          "https://github.com/deepseek-ai/dsh-superagent releases"),
          "github 路径 deepseek-ai 不触发模型标签")
    check("模型" in enrich.topics_of("DeepSeek 发布 V4 新模型，推理能力提升"),
          "真模型发布仍命中模型标签")
    check("模型" in enrich.topics_of("deepseek-v4 模型升级"),
          "deepseek-v4 模型升级仍命中（中文模型升级词）")

    # 兑换码：显式标注、分段码、长码；排除纯数字/常见词/无字母
    codes = enrich.codes_of("邀请码: ABCD-EFGH-IJKL 限时", "promo code ZXCV9999")
    check("ABCD-EFGH-IJKL" in codes and "ZXCV9999" in codes, f"兑换码抽取: {codes}")
    check(enrich.codes_of("价格 12345 元，数量 67890") == [], "纯数字不当兑换码")
    check(enrich.codes_of("见 GITHUB 与 README 文档") == [], "常见英文词不当兑换码")

    # 原地增强 + 汇总
    e = enrich.enrich_entry({"title": "免费额度领取", "summary": ""})
    check(e["form"] == "freebie" and "codes" in e and "topics" in e,
          "enrich_entry 原地补全四字段")
    stat = enrich.summarize([
        {"form": "news", "obtain": None, "codes": []},
        {"form": "freebie", "obtain": "free", "codes": ["X"]},
    ])
    check(stat["with_codes"] == 1 and stat["forms"]["freebie"] == 1, "summarize 分布统计")

    # 论坛噪音：交易帖/问询帖丢弃，福利帖保留（奶昔论坛真实样本）
    noise = [
        "出一张全新3HK DIY大湾区储值卡",
        "出V0 MAX，V0，海豚小白卡和B0",
        "[已出]出已激活Lebara uk 9.9r",
        "voxi这样是不是就转好paygo了",
        "德国沃达丰现在强制实名了吗",
        "北京联通请教转套餐",
        "血亏4000人民币，孩子被topcashback反薅了，快来救救孩子",
    ]
    keep = [
        "🇭🇰 香港八达通迎新福利｜消费 HK$100 送 HK$150！",
        "b站限时领一周大会员",
        "免费1GB流量eSIM 大陆可以用 多地区 🈚aff",
        "我们做了一个100%免费公益的应用（送隔壁终身版激活码）",
        "OpenAI 发布新模型",
        "KTC 预告 6K Mini LED 显示器 M32P2",
    ]
    for t in noise:
        check(enrich.noise_reason(t) is not None, f"噪音识别: {t[:18]}")
    for t in keep:
        check(enrich.noise_reason(t) is None, f"福利/资讯不误伤: {t[:18]}")
    kept, dropped = enrich.drop_noise([{"title": t} for t in noise + keep])
    check(len(dropped) == len(noise) and len(kept) == len(keep), "drop_noise 批量二分")


def test_collectors():
    import collectors
    from datetime import datetime

    # 配置加载：默认只返回启用项
    confs = collectors.load_collectors()
    ids = {c["id"] for c in confs}
    check("openrouter-free-models" in ids and "hackernews-ai" in ids,
          f"两个启用采集器存在: {ids}")
    check("v2ex-free" not in ids and "bluesky-ai" not in ids,
          "默认禁用的采集器不返回")
    # only 过滤
    assert collectors.load_collectors(only="hackernews-ai")[0]["type"] == "hackernews"

    # 缓存读写与离线回退
    cid = "selftest-probe"
    collectors._write_cache(cid, {"fetched_at": 0, "entries": [
        {"title": "缓存条目", "link": "https://x/1", "summary": "",
         "published": "2026-11-01T00:00:00+00:00", "source_id": cid,
         "source_name": "probe", "group": "g", "kind": "hackernews"}]})
    got = collectors._from_cache(cid)
    check(len(got) == 1 and isinstance(got[0]["published"], datetime),
          "缓存读回并把 ISO 还原成 datetime")
    # fetch_one 离线走缓存
    items = collectors.fetch_one(
        {"id": cid, "type": "hackernews", "name": "probe"}, offline=True)
    check(items and items[0]["link"] == "https://x/1", "离线 fetch_one 回退缓存")
    # 未知类型报错
    try:
        collectors.fetch_one({"id": "z", "type": "nope"}, offline=False)
        raise AssertionError("未知采集器类型应报错")
    except collectors.CollectorError:
        print("  ✓ 未知采集器类型抛 CollectorError")
    # 清理测试缓存
    collectors._cache_path(cid).unlink(missing_ok=True)

    # OpenRouter 解析逻辑（用桩数据，不发网络）
    fake = {"data": [
        {"id": "vendor/new:free", "name": "New Free", "created": 9999999999,
         "pricing": {"prompt": "0", "completion": "0"}, "context_length": 32768,
         "description": "a free model"},
        {"id": "vendor/paid", "name": "Paid", "created": 9999999999,
         "pricing": {"prompt": "0.001", "completion": "0.002"}},
        {"id": "vendor/oldfree:free", "name": "Old", "created": 1,
         "pricing": {"prompt": "0", "completion": "0"}},
    ]}
    orig_http = collectors._http_json
    collectors._http_json = lambda url: fake
    try:
        out = collectors.collect_openrouter(
            {"id": "or-test", "type": "openrouter", "name": "OR",
             "group": "g", "max_age_days": 14, "limit": 20})
    finally:
        collectors._http_json = orig_http
    links = [e["link"] for e in out]
    check(any("vendor/new:free" in l for l in links), "免费模型入选")
    check(not any("vendor/paid" in l for l in links), "付费模型被过滤")
    check(not any("vendor/oldfree" in l for l in links), "超龄免费模型被过滤")
    check(all(e["kind"] == "openrouter" for e in out), "kind 标记为 openrouter")
    collectors._cache_path("or-test").unlink(missing_ok=True)

    # HN 解析：标题不含 AI 信号的丢弃
    fake_hn = {"hits": [
        {"objectID": "1", "title": "Show HN: My new LLM agent framework",
         "url": "https://p/1", "created_at_i": 1700000000, "points": 50,
         "num_comments": 10, "story_text": ""},
        {"objectID": "2", "title": "How I cook pasta perfectly",
         "url": "https://p/2", "created_at_i": 1700000001, "points": 5,
         "num_comments": 1, "story_text": ""},
    ]}
    collectors._http_json = lambda url: fake_hn
    try:
        hn = collectors.collect_hackernews(
            {"id": "hn-test", "type": "hackernews", "name": "HN",
             "group": "g", "limit": 30, "hits_per_query": 20, "queries": ["AI"]})
    finally:
        collectors._http_json = orig_http
    check(len(hn) == 1 and "LLM" in hn[0]["title"], "HN 只保留 AI 相关故事")
    check("50 分" in hn[0]["summary"] and hn[0]["kind"] == "hackernews",
          "HN 摘要含分数且 kind 正确")
    collectors._cache_path("hn-test").unlink(missing_ok=True)


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

    # 合法但零条目的 feed（arXiv 周末无公告）返回 [] 而非抛错，
    # 否则连续 3 次会被健康检查误判自动停用（坑 34）
    empty_rss = ('<?xml version="1.0"?><rss version="2.0"><channel>'
                 '<title>cs.AI updates on arXiv.org</title>'
                 '<skip><day>Saturday</day><day>Sunday</day></skip>'
                 '</channel></rss>')
    check(feeds.parse_feed(empty_rss, src) == [], "合法空 feed 返回空列表不抛错")
    empty_atom = ('<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">'
                  '<title>empty</title></feed>')
    check(feeds.parse_feed(empty_atom, src) == [], "合法空 Atom 返回空列表不抛错")
    # 非 feed 的 HTML 页面（含 <rss 字样的错误页除外）仍要判失败
    try:
        feeds.parse_feed("<html><body>404 Not Found</body></html>", src)
        raise AssertionError("HTML 页面应抛 FeedError")
    except feeds.FeedError:
        print("  ✓ 非 feed 的 HTML 页面仍判失败")

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

    print("[16] 免费机翻通道")
    test_mt()

    print("[17] 规则增强与结构化采集器")
    test_enrich()
    test_collectors()
    print("\n全部自测通过 ✅")


if __name__ == "__main__":
    main()
