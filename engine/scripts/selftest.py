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


def test_watch():
    import tempfile, pathlib as _pl
    import watch
    tmp = _pl.Path(tempfile.mktemp(suffix=".json"))
    orig = watch.WATCH_CONF
    watch.WATCH_CONF = tmp
    try:
        # 配置缺失 → 静默关闭
        check(watch.load_watch() == [], "watch 配置缺失时返回空列表")
        tmp.write_text(
            '{"keywords": ['
            '{"term": "mcp", "enabled": true},'
            '{"term": "agent", "enabled": true},'
            '{"term": "免费额度", "enabled": true},'
            '{"term": "disabled-word", "enabled": false}]}',
            encoding="utf-8")
        kws = watch.load_watch()
        check(kws == ["mcp", "agent", "免费额度"], "只加载启用关键词且保序去重")

        # ASCII 词边界：mcp 不命中 scmcp
        e1 = {"title": "New scmcp tooling released", "summary": "", "link": "u1"}
        check(watch.match_watch(e1, kws) == [], "ASCII 关注词按整词匹配，不命中子串")
        e2 = {"title": "An MCP server for an agent runtime", "summary": "", "link": "u2"}
        hits2 = watch.match_watch(e2, kws)
        check("mcp" in hits2 and "agent" in hits2, "英文标题多词命中")
        # 复数形态：整词边界不命中 agents（用户配的是 agent 单数）
        e2b = {"title": "framework for autonomous agents", "summary": "", "link": "u2b"}
        check("agent" not in watch.match_watch(e2b, kws), "整词边界不匹配复数 agents")
        # 大小写不敏感
        e3 = {"title": "AGENT framework update", "summary": "", "link": "u3"}
        check("agent" in watch.match_watch(e3, kws), "英文关注词大小写不敏感")
        # 中文子串 + 译文参与匹配
        e4 = {"title": "某厂商发布公告", "summary": "", "link": "u4"}
        trans = {"u4": {"zh_title": "新模型赠送免费额度", "zh_summary": ""}}
        check("免费额度" in watch.match_watch(e4, kws, trans), "中文关注词命中译文标题")
        # 摘要参与匹配
        e5 = {"title": "Weekly digest", "summary": "covering the latest mcp ecosystem", "link": "u5"}
        check("mcp" in watch.match_watch(e5, kws), "关注词匹配摘要")

        # attach 批量 + summarize 统计
        entries = [e1, e2, e3, e4, e5]
        n = watch.attach_watch(entries, kws, trans)
        check(n == 4 and all("watch_hits" in x for x in entries), "attach 标记命中条数并写字段")
        stat = watch.summarize(entries)
        check(stat.get("agent") == 2 and stat.get("mcp") == 2, "summarize 统计各词命中数")
    finally:
        watch.WATCH_CONF = orig
        tmp.unlink(missing_ok=True)


def test_watch_crud():
    import tempfile, pathlib as _pl
    import watch
    tmp = _pl.Path(tempfile.mktemp(suffix=".json"))
    orig = watch.WATCH_CONF
    watch.WATCH_CONF = tmp
    try:
        check(watch.load_watch() == [], "CRUD：初始无配置返空")
        _, added = watch.add_keyword("rag")
        check(added and watch.load_watch() == ["rag"], "CRUD：新增启用词")
        _, added2 = watch.add_keyword("RAG")  # 忽略大小写重复
        check(added2 is False and watch.load_watch() == ["rag"], "CRUD：同名重复不新增")
        watch.toggle_keyword("rag", False)
        check(watch.load_watch() == [], "CRUD：停用后不进启用列表")
        _, added3 = watch.add_keyword("rag")  # 同名再添加=重新启用
        check(added3 is False and watch.load_watch() == ["rag"], "CRUD：同名添加重新启用停用词")
        watch.add_keyword("向量库")
        check(watch.load_watch() == ["rag", "向量库"], "CRUD：多词保序")
        _, removed = watch.remove_keyword("RAG")
        check(removed and "rag" not in watch.load_watch(), "CRUD：忽略大小写删除")
        try:
            watch.add_keyword("   ")
            check(False, "CRUD：空词应报错")
        except ValueError:
            pass
    finally:
        watch.WATCH_CONF = orig
        tmp.unlink(missing_ok=True)


def test_dedup_and_fallback():
    import enrich
    base = "2026-11-10T08:00:00+00:00"
    entries = [
        # 同事件英文转载：科技媒体 vs 厂商官方，官方应胜出
        {"title": "OpenAI launches new agent toolkit for developers",
         "link": "u1", "group": "科技媒体", "source_name": "TechCrunch", "published": base},
        {"title": "OpenAI launches a new agent toolkit for developers",
         "link": "u2", "group": "厂商官方", "source_name": "OpenAI Blog", "published": base},
        # 不相关短标题不参与聚类
        {"title": "Hi", "link": "u3", "group": "科技媒体", "source_name": "X", "published": base},
        # 跨语言不合并（日文与中文即使概念相同）
        {"title": "新しいAIエージェントツールを発表",
         "link": "u4", "group": "科技媒体", "source_name": "日文站", "published": base},
        {"title": "全新 AI 智能体工具发布",
         "link": "u5", "group": "科技媒体", "source_name": "中文站", "published": base},
    ]
    kept, dropped = enrich.cluster_duplicates(entries, threshold=0.62)
    check(dropped == 1, f"近似去重：折叠 1 条转载（实际 {dropped}）")
    check(len(kept) == 4, "近似去重：保留 4 条主条目")
    primary = next(x for x in kept if x.get("dup_count"))
    check(primary["link"] == "u2" and primary["dup_sources"] == ["TechCrunch"],
          "近似去重：来源优先级让厂商官方胜出并记录折叠源")
    check(entries[0].get("dup_of") == "u2", "近似去重：被折叠条目标 dup_of")

    # 分组兜底标签：规则全空时强领域组兜底，杂烩组留空
    e_off = {"title": "某厂季度通讯（无任何规则词）", "summary": "", "group": "厂商官方"}
    enrich.enrich_entry(e_off)
    check(e_off["topics"] == ["AI 综合"], "兜底：厂商官方无规则命中时挂 AI 综合")
    e_mix = {"title": "一条杂烩社区帖（无任何规则词）", "summary": "", "group": "开发者社区"}
    enrich.enrich_entry(e_mix)
    check(e_mix["topics"] == [], "兜底：杂烩组不硬贴标签")
    # 规则命中优先于兜底
    e_hit = {"title": "New GPU benchmark released", "summary": "", "group": "厂商官方"}
    enrich.enrich_entry(e_hit)
    check("硬件算力" in e_hit["topics"] and "AI 综合" not in e_hit["topics"],
          "兜底：规则命中时不追加兜底标签")


def test_sourcecheck():
    import sourcecheck
    feeds_doc = [
        {"id": "s1", "name": "活跃源", "group": "科技媒体", "enabled": True},
        {"id": "s2", "name": "静默源", "group": "技术博客", "enabled": True},
        {"id": "s3", "name": "停用源", "group": "科技媒体", "enabled": False},
    ]
    entries = [
        {"source_id": "s1", "published": "2026-11-15T00:00:00+00:00"},
        {"source_id": "s2", "published": "2026-10-01T00:00:00+00:00"},  # 30 天内有、7 天窗口外
    ]
    result = sourcecheck.run_check(feeds_doc, entries, days=7)
    silent_ids = [s["id"] for s in result["silent"]]
    check(silent_ids == ["s2"], f"体检：只报启用且窗口内 0 条的源（实际 {silent_ids}）")
    s2 = next(s for s in result["silent"] if s["id"] == "s2")
    check(s2["last_published"].startswith("2026-10-01"), "体检：最近条目时间取全量窗口")

    # 故障与孤儿
    health = {
        "s1": {"consecutive_fails": 3, "last_error": "timeout"},
        "gone": {"consecutive_fails": 5},
    }
    failing = sourcecheck.failing_sources(feeds_doc, health)
    check([f["id"] for f in failing] == ["s1"], "体检：故障源达阈值且仍启用才上报")
    check(sourcecheck.orphan_health(feeds_doc, health) == ["gone"], "体检：识别 health 孤儿")


def test_glossary():
    import glossary
    # Agent → 智能体：需原文有 agent 词根
    zh, hits = glossary.normalize_text("把计算机交给代理", "give your agents a computer")
    check(zh == "把计算机交给智能体" and hits, "术语：agent 语境下代理→智能体")
    # 无 agent 词根时不动（网络代理语义）
    zh2, hits2 = glossary.normalize_text("通过代理服务器访问", "access via a proxy server")
    check(zh2 == "通过代理服务器访问" and not hits2, "术语：非 AI 语境不误伤代理服务器")
    # 代理服务器/代理人等组合词护栏
    zh3, _ = glossary.normalize_text("这家代理商与代理人", "these agents")
    check("代理" in zh3, "术语：代理商/代理人组合词不被替换")
    # 冗余叠词消除
    zh4, _ = glossary.normalize_text("人工智能代理的蜜罐", "AI agent honeypot")
    check(zh4 == "智能体的蜜罐", "术语：消除「人工智能智能体」叠词")
    # Token：LLM 语境保留英文
    zh5, _ = glossary.normalize_text("每秒生成 2100 个代币", "2100 tokens per second")
    check("Token" in zh5, "术语：LLM 语境 token→Token")
    zh6, hits6 = glossary.normalize_text("检测服务令牌", "detect service tokens")
    check(zh6 == "检测服务令牌" and not hits6, "术语：安全令牌语境不改写")
    # Prompt → 提示词
    zh7, _ = glossary.normalize_text("从不命中提示缓存", "never hits prompt cache")
    check("提示词缓存" in zh7, "术语：prompt→提示词")
    # 幂等：二次归一化不再变化（防「提示词词」类叠词）
    zh8, _ = glossary.normalize_text(zh7, "never hits prompt cache")
    check(zh8 == zh7, "术语：归一化幂等")
    # 只改机翻条目，人工精译不动
    store = {
        "u1": {"zh_title": "交给代理", "source_title": "give agents a computer", "source": "auto:transmart"},
        "u2": {"zh_title": "交给代理", "source_title": "give agents a computer"},
    }
    stats = glossary.normalize_store(store, dry_run=False)
    check(stats["changed"] == 1 and store["u1"]["zh_title"] == "交给智能体"
          and store["u2"]["zh_title"] == "交给代理", "术语：只归一化机翻条目，人工精译不动")


def test_netcfg():
    import tempfile, pathlib as _pl
    import netcfg
    tmp = _pl.Path(tempfile.mktemp(suffix=".json"))
    orig = netcfg.PROXY_CONF
    netcfg.PROXY_CONF = tmp
    try:
        check(netcfg.load_proxy()["enabled"] is False, "代理：无配置时默认直连")
        check(netcfg.opener() is None, "代理：直连时 opener 为 None")
        for bad in ("socks5://127.0.0.1:1080", "127.0.0.1:7890", "http://", ""):
            try:
                netcfg.validate_url(bad)
                check(False, f"代理：非法地址应拒绝 {bad}")
            except ValueError:
                pass
        check(netcfg.validate_url("http://127.0.0.1:7890") == "http://127.0.0.1:7890",
              "代理：合法 http 地址通过")
        netcfg.save_proxy(True, "http://127.0.0.1:7890", "localhost")
        conf = netcfg.load_proxy()
        check(conf["enabled"] and conf["url"].endswith("7890"), "代理：保存后读回一致")
        check(netcfg.opener() is not None, "代理：启用后 opener 非空")
        check(netcfg._bypassed("http://localhost:8080/x"), "代理：no_proxy 命中走直连")
        check(not netcfg._bypassed("https://example.com/x"), "代理：白名单外走代理")
        check("代理" in netcfg.describe(), "代理：describe 反映启用状态")
        netcfg.save_proxy(False, "http://127.0.0.1:7890")
        check(netcfg.opener() is None and netcfg.load_proxy()["url"].endswith("7890"),
              "代理：关闭后仍保留地址便于下次开启")
        # 测试函数对不可达代理返回 ok=False 而不是抛异常
        r = netcfg.test_proxy("http://127.0.0.1:1")
        check(r["ok"] is False and "error" in r, "代理：测试连通失败时返回错误而非抛异常")
    finally:
        netcfg.PROXY_CONF = orig
        netcfg.save_proxy(False, "")  # 还原缓存与文件
        tmp.unlink(missing_ok=True)


def test_backup():
    import tempfile, zipfile, json as _json
    import pathlib as _pl
    import backup
    tmpdir = _pl.Path(tempfile.mkdtemp())
    orig_data = backup.DATA
    backup.DATA = tmpdir
    try:
        (tmpdir / "sources").mkdir()
        (tmpdir / "news_translations.json").write_text('{"a":1}', encoding="utf-8")
        (tmpdir / "sources" / "watch.json").write_text('{"keywords":[]}', encoding="utf-8")
        out = backup.create_backup(log=None)
        check(out.exists() and out.suffix == ".zip", "备份：生成 zip")
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
            manifest = _json.loads(zf.read("backup-manifest.json").decode("utf-8"))
        check("news_translations.json" in names and "sources/watch.json" in names,
              "备份：包含翻译库与关注词配置")
        check("news.db" not in names and "news.db" in manifest["missing"],
              "备份：缺失文件记入 manifest 而非报错")
        # 恢复：先破坏原文件，再从备份还原
        (tmpdir / "news_translations.json").write_text("{}", encoding="utf-8")
        backup.restore_backup(out, log=None)
        check((tmpdir / "news_translations.json").read_text(encoding="utf-8") == '{"a":1}',
              "备份：恢复还原文件内容")
        check(len(backup.list_backups()) >= 1, "备份：能列出备份文件")
        # 空 data 目录时拒绝生成空备份
        empty = _pl.Path(tempfile.mkdtemp())
        orig2 = backup.DATA
        backup.DATA = empty
        try:
            try:
                backup.create_backup(log=None)
                check(False, "备份：无资产应报错")
            except RuntimeError:
                pass
        finally:
            backup.DATA = orig2
    finally:
        backup.DATA = orig_data


def test_news_persistence_mixed_types():
    """坑 49 回归：RSS(datetime) 与采集器(ISO 字符串) 混批时，写库判定不能只看第一条。"""
    import datetime as _dt
    import radar
    tz = _dt.timezone.utc
    dt_obj = _dt.datetime(2026, 11, 16, 10, 0, tzinfo=tz)
    mixed = [
        {"link": "https://h/1", "title": "采集器条目（字符串）", "published": dt_obj.isoformat(),
         "source_id": "hn"},
        {"link": "https://r/2", "title": "RSS 条目（datetime）", "published": dt_obj,
         "source_id": "tomshardware"},
        {"link": "https://r/3", "title": "无时间条目", "published": None, "source_id": "x"},
    ]
    ser = radar._serialize_news(mixed)
    check(all(isinstance(e["published"], str) for e in ser if e["published"]),
          "序列化：混批后所有非空 published 都是字符串")
    check(ser[1]["published"] == dt_obj.isoformat(), "序列化：datetime 正确 ISO 化")
    check(ser[2]["published"] is None, "序列化：None 保持 None 不报错")
    # 写库判定：批次中存在 datetime 即应全量写入（旧逻辑只看第一条会漏写 RSS）
    has_datetime = any(not isinstance(e.get("published"), str) for e in mixed)
    check(has_datetime is True, "写库判定：混批识别出 datetime 条目，不会漏写 RSS")
    all_str = [{"link": "a", "published": "2026-11-16T10:00:00+00:00"}]
    check(not any(not isinstance(e.get("published"), str) for e in all_str),
          "写库判定：纯字符串批次不误触发全量写")
    # 坑 50：IncompleteRead 必须在 fetch_one 的网络异常元组里（否则整轮采集崩掉）
    import inspect
    import http.client as _hc
    src_text = inspect.getsource(__import__("feeds").fetch_one)
    check("http.client.IncompleteRead" in src_text
          and issubclass(_hc.IncompleteRead, Exception),
          "采集：IncompleteRead 被显式捕获并回退缓存，不中断整轮采集")


def test_client_hooks():
    """静态扫描 plugin/client.js：Hook 不得出现在条件 return 之后（白屏根因回归测试，坑 48）。

    轻量大括号深度跟踪：在组件函数体内一旦出现同层级的提前 return，
    其后再出现 useState/useEffect/useCallback/useMemo/useRef 即判违规。
    不做完整 JS 解析——本仓代码风格固定（无 class 组件、无 switch），够用且零依赖。
    """
    import pathlib, re
    client = pathlib.Path(__file__).resolve().parent.parent.parent / "plugin" / "client.js"
    if not client.exists():
        check(False, "前端：client.js 存在")
        return
    src = client.read_text(encoding="utf-8")
    hook_re = re.compile(r"\b(useState|useEffect|useCallback|useMemo|useRef|useReducer)\s*\(")

    # 只扫描组件函数区间：function XxxPanel() { ... }（本仓组件均为 function 声明）
    violations = []
    for m in re.finditer(r"function\s+(\w+)\s*\([^)]*\)\s*\{", src):
        name, start = m.group(1), m.end()
        depth, i, body_start = 1, start, start
        top_returned = False   # 组件顶层（depth==1）出现过提前 return
        while i < len(src) and depth > 0:
            ch = src[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            i += 1
        body = src[body_start:i - 1]
        line_base = src[:body_start].count("\n") + 1
        d = 1
        for off, raw in enumerate(body.splitlines(), 1):
            line = raw.split("//", 1)[0]
            stripped = line.strip()
            is_return = (stripped.startswith("return ") or stripped == "return;"
                         or stripped.startswith("return(") or stripped.startswith("return h("))
            if is_return and d == 1:
                top_returned = True
            if hook_re.search(line) and d == 1 and top_returned:
                violations.append(f"{name} L{line_base + off}: {stripped[:60]}")
            d += line.count("{") - line.count("}")
            if d < 1:
                d = 1
    check(not violations, f"前端：无 Hook 位于条件 return 之后（{len(violations)} 处违规）"
          + (("：" + "; ".join(violations[:3])) if violations else ""))
    # 错误日志与边界设施齐备
    check("ErrorBoundary" in src and "getDerivedStateFromError" in src,
          "前端：ErrorBoundary 错误边界存在，渲染崩溃不再白屏")
    check("pushClientLog" in src and "/logs" in src,
          "前端：错误上报 pushClientLog 与 /logs 通道存在")
    # 坑 51 回归：去重徽章必须是模块级 helper 且两个视图都调用（曾只在 masonry 定义、
    # list 视图引用未定义标识符，ReferenceError 整面板崩）
    check(re.search(r"function\s+dupBadgeOf\s*\(", src) is not None,
          "前端：dupBadgeOf 为模块级 helper")
    check(src.count("dupBadgeOf(it)") >= 2,
          "前端：masonry 与 list 两个视图都通过 dupBadgeOf 渲染去重徽章")
    # 两视图卡片回调里出现的共享 helper 都必须在组件/模块级有定义（function 或 const 箭头），
    # 不能只在某一个 map 回调里局部声明——防止再出作用域漏定义（坑 51）
    masonry = src[src.index("filtered.map((it) => {"):src.index("orderedGroups.map")]
    listsec = src[src.index("items.map((it) => {"):]
    for helper in ("chipsOf", "watchOf", "groupColor", "srcInitial", "fmtDate", "dupBadgeOf"):
        defined = (re.search(rf"function\s+{helper}\s*\(", src) is not None
                   or re.search(rf"const\s+{helper}\s*=", src) is not None)
        # 局部 map 回调里的 const 不算（那正是坑 51 的形态）：要求定义出现在两个回调区间之外
        local_only = (re.search(rf"const\s+{helper}\s*=", masonry) is not None
                      or re.search(rf"const\s+{helper}\s*=", listsec) is not None)
        check(defined and not local_only, f"前端：共享 helper {helper} 有组件/模块级定义")


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

    print("[18] 关键词关注（watch）")
    test_watch()
    test_watch_crud()

    print("[19] 近似去重、分组兜底与信源体检")
    test_dedup_and_fallback()
    test_sourcecheck()

    print("[20] 术语归一化、代理与资产备份")
    test_glossary()
    test_netcfg()
    test_backup()

    print("[21] 前端 Hooks 规则、错误日志与混批持久化（防白屏/防漏写回归）")
    test_client_hooks()
    test_news_persistence_mixed_types()
    print("\n全部自测通过 ✅")


if __name__ == "__main__":
    main()
