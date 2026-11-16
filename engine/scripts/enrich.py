"""资讯增强：规则版内容形态 / 获取方式 / 领域标签 / 兑换码抽取。

借鉴 ZiChuanLan/freebie-radar 的正交分类模型（kind × category × obtain），
但**不调 AI、不花额度**——全部用关键词规则，确定性、可回归、零成本。

- form（内容形态）：freebie / deal / release / paper / tutorial / opensource / news
- obtain（获取方式）：free / conditional / lottery / trial / promo / paid（仅福利类有意义）
- topics（领域标签）：模型 / Agent / MCP / RAG / 推理部署 / 多模态 / 训练微调 /
  工具框架 / 安全 / 硬件算力 / 政策合规 / 商业融资 / 评测榜单 / 开源（AI 相关）
  + 编程开发 / 云计算与基础设施 / 数据 / 消费电子 / 游戏 / 影音媒体 / 设计创意 /
  产品与增长 / 职场商业 / 教育学习 / 金融财经 / 汽车出行 / 生活方式（通用领域，不局限 AI）
- codes（兑换码/邀请码）：黄色胶囊一键复制

用法：
    import enrich
    enrich.attach(entries)       # 原地批量补字段
    enrich.form_of(title, summary)
"""

import re
from datetime import datetime, timezone


def _w(pat):
    """给英文词加词边界（中文不受影响）；把裸短词的子串误匹配（ev→ever、ar→car）挡掉。"""
    return r"(?<![a-z0-9])" + pat + r"(?![a-z0-9])"


# ---------------------------------------------------------------- 内容形态

_FORM_RULES = (
    ("freebie", r"免费额度|免费\s*(token|额度|api|key|模型)|白嫖|限时免费|限免|0\s*元|零元|"
                r"免费领|领取|赠送|注册送|送\s*\d+\s*(美元|\$|token|额度)|"
                r"free\s+(tier|credits?|quota|api|plan|model)|free\s+of\s+charge|"
                r":free\b|\(free\)|\bfree\b\s*(模型|额度|调用)|"
                r"抽奖|开奖|抽名额|giveaway|raffle|随机送"),
    ("deal", r"优惠|折扣|立减|促销|特价|优惠券|券码|黑五|双\s*11|618|返现|返利|"
             r"discount|coupon|%\s*off|deal|price\s*cut|promo"),
    ("paper", r"arxiv|论文|paper|预印本|研究成果|benchmark\s+study|ablation"),
    ("release", r"发布|上线|推出|正式版|general\s+availability|\bGA\b|"
               r"release[sd]?\b|launch(es|ed)?\b|introduc(es|ing)\b|now\s+available|"
               r"v\d+\.\d+(\.\d+)?|changelog|版本"),
    ("opensource", r"开源|open[\s-]?source|\bgithub\b|\brepo(sitory)?\b|"
                 r"self[\s-]?host"),
    ("tutorial", r"教程|指南|手把手|实战|入门|最佳实践|踩坑|how[\s-]?to|"
                r"guide|tutorial|walkthrough|cookbook"),
)

# 形态优先级：福利/优惠最具体，其次论文、发布，最后才是通用资讯
_FORM_ORDER = ("freebie", "deal", "paper", "release", "tutorial", "opensource")

_FORM_LABEL = {
    "freebie": "福利", "deal": "优惠", "release": "发布", "paper": "论文",
    "tutorial": "教程", "opensource": "开源", "news": "资讯",
}


def form_of(title, summary=""):
    """判定内容形态；命中顺序按精确度，默认 news。"""
    text = f"{title} {summary}".lower()
    for kind in _FORM_ORDER:
        for name, pat in _FORM_RULES:
            if name == kind and re.search(pat, text):
                return kind
    return "news"


# ---------------------------------------------------------------- 获取方式

_OBTAIN_RULES = (
    ("lottery", r"抽奖|抽\s*\d+\s*(份|个|名|位)|开奖|随机送|giveaway|raffle|抽名额"),
    ("promo", r"注册送|充值|体验金|推广|邀请好友|返现|首充|引流|优惠码|折扣码"),
    ("trial", r"免费试用|试用\s*\d+\s*天|首月免费|\d+\s*天\s*免费|free\s+trial|trial"),
    ("conditional", r"回帖|盖楼|转发|关注后|评论送|点赞|邀请|实名|绑卡|扫码"),
    ("paid", r"需付费|付费|订阅|充值后|月费|\$\s*\d+(\.\d+)?\s*/|每年"),
)

_OBTAIN_LABEL = {
    "free": "直接领", "conditional": "需互动", "lottery": "抽奖",
    "trial": "试用", "promo": "推广", "paid": "付费",
}


def obtain_of(title, summary="", form=None):
    """判定获取方式。非福利/优惠形态返回 None（对纯资讯没意义）。"""
    form = form if form is not None else form_of(title, summary)
    if form not in ("freebie", "deal"):
        return None
    text = f"{title} {summary}".lower()
    for name, pat in _OBTAIN_RULES:
        if re.search(pat, text):
            return name
    return "free"


# ---------------------------------------------------------------- 领域标签

_TOPIC_RULES = (
    # ---------- AI 相关（先匹配，保证 AI 文章优先打 AI 标签）----------
    ("模型", r"\b(gpt|claude|gemini|llama|qwen|kimi|mistral|gemma|o[134])\b|"
              # deepseek 单独出现多指模型；后接 harness/平台/插件，或处于 URL 路径中
              # （/r/deepseek/、deepseek-ai/、deepseek-creator-mode 等）时是产品名/链接
              r"\bdeepseek\b(?!\s+(?:harness|平台|插件|plugin)|[/\-_])"
              r"|大模型|模型(发布|升级|迭代)|新模型|frontier\s+model"),
    ("Agent", r"\bagent(s)?\b|智能体|自治体|copilot|多智能体|autonomous"),
    ("MCP", r"\bmcp\b|model\s+context\s+protocol"),
    ("RAG", r"\brag\b|retrieval|检索增强|向量(库|检索)|embedding|知识库"),
    ("推理部署", r"推理|inference|部署|deploy|量化|quantiz|vllm|sglang|ollama|llama\.cpp|"
                r"本地运行|serving|吞吐"),
    ("多模态", r"多模态|multimodal|视觉语言|\bvlms?\b|文生图|图像生成|语音合成|视频生成|"
              r"diffusion"),
    ("训练微调", r"训练|微调|fine[\s-]?tun|lora|rlhf|预训练|pretrain|蒸馏|distill|数据集"),
    ("工具框架", r"框架|framework|\bsdk\b|library|\bcli\b|插件|plugin|工具链|toolkit|"
                r"编程助手|coding\s+assistant"),
    ("评测榜单", r"benchmark|评测|榜单|leaderboard|\bsota\b|排行|评测集|\beval\b"),
    # ---------- 技术与工程（非 AI 专属）----------
    ("编程开发", r"编程|开发|前端|后端|全栈|\bjavascript\b|typescript|python|java|golang|"
                r"rust|node\.?js|react|vue|编程语言|代码|开源项目|api\s+设计|微服务|"
                r"devops|\bci/cd\b|docker|kubernetes|\bk8s\b|git|数据库|sql|linux|"
                r"web\s+development|software\s+engineering|ffmpeg|nvim|neovim|"
                + _w(r"nim")),
    ("安全", r"安全|security|漏洞|vulnerab|攻击|attack|注入|prompt\s+injection|供应链|"
             r"supply[\s-]?chain|越狱|jailbreak|隐私|privacy|malware|恶意|"
             r"rubygems?|npm\s+attack|数据泄露|breach|phishing|钓鱼|零日|0day|"
             r"勒索|ransomware|加密|encryption|\bxss\b|劫持|hijack|宕机|障害|outage"),
    ("云计算与基础设施", r"云计算|云服务|\baws\b|azure|\bgcp\b|云原生|serverless|"
                       r"边缘计算|cdn|服务器|数据中心|infrastructure|\bvm\b|容器|"
                       r"kubernetes|terraform|observability|可观测"),
    ("数据", r"数据工程|数据分析|数据仓库|data\s+engineering|analytics|\betl\b|"
            r"数据管道|pipeline|数据治理|bi\s+工具|可视化|dashboard|数据科学"),
    ("硬件算力", r"\bgpu\b|h100|h200|b200|gb200|算力|芯片|tpu|npu|数据中心|显存|"
                r"infrastructure|accelerator|半导体|semiconductor|处理器|cpu|arm|"
                r"risc[\s-]?v|内存|存储硬件|英伟达|nvidia|黄仁勋|詹森|jensen\s+huang"),
    # ---------- 行业与垂直领域 ----------
    # 时政/国际用 (标签, 标题强信号, 摘要弱信号) 三元组：摘要里 government/worldwide
    # 之类的泛词太常见，只在摘要命中时要求与标题共同佐证，避免大量误判（见坑文档 33）
    ("时政要闻",
     r"政治|政府|总统|大选|选举|议会|白宫|国会|国务院|外交部|外交|军事|战争|制裁|"
     r"关税|政党|首相|总理|国家主席|行政命令|政权|停火|俄乌|中东局势|地缘政治|"
     r"geopolit|sanction|tariff|trade\s+war|war\s+(?:crimes|zone|in|on)|"
     + _w(r"election") + r"|" + _w(r"government") + r"|" + _w(r"president") +
     r"|" + _w(r"military"),
     r"政治|政府|总统|大选|选举|议会|白宫|国会|外交部|外交|军事|战争|制裁|关税|"
     r"首相|总理|停火|俄乌|中东|地缘政治|geopolit|sanction|tariff|trade\s+war|"
     r"war\s+(?:crimes|zone|in|on)|" + _w(r"election") + r"|" + _w(r"military")),
    ("国际资讯",
     r"国际(?:关系|贸易|局势|政治|新闻|峰会|制裁|争端|合作|秩序|局势)|"
     r"联合国|峰会|欧盟|中美(?:关系|贸易|关税|博弈|外交|制裁)|中欧|东盟|地缘|"
     r"全球(?:贸易|经济|治理|格局|峰会|供应链)|"
     r"international\s+(?:news|relations|affairs|trade|community|cooperation)|"
     r"world\s+news|global\s+news",
     r"国际(?:关系|贸易|局势|政治|新闻|峰会|制裁|争端|合作|秩序)|跨国|联合国|峰会|欧盟|"
     r"中美(?:关系|贸易|关税|博弈|外交|制裁)|中欧|东盟|地缘|各国|international"),
    ("政策合规", r"监管|regulat|合规|法案|政策|禁令|\bban\b|版权|著作权|copyright|"
                r"欧盟|eu\s+ai\s+act|反垄断|antitrust|诉讼|lawsuit|gdpr"),
    ("商业融资", r"融资|funding|估值|valuation|\bipo\b|收购|acquisition|营收|revenue|"
                r"裁员|layoff|创业|startup|独角兽|并购|财报|季度业绩"),
    ("金融财经", r"金融|理财|支付|银行|crypto|加密货币|比特币|bitcoin|以太坊|ethereum|"
                r"区块链|blockchain|" + _w(r"nft") + r"|股票|股市|基金|保险|fintech|"
                r"数字人民币|支付清算|信贷|证券"),
    ("消费电子", r"手机|智能手机|iphone|安卓|android|笔记本|平板|耳机|智能手表|"
                r"消费电子|gadget|硬件新品|发布会|苹果|华为|小米|三星|可穿戴|"
                + _w(r"vr") + r"|" + _w(r"ar\b") + r"|" + _w(r"xr\b") + r"|显示器|monitor|mini\s?led"),
    ("汽车出行", r"电动车|新能源汽车|自动驾驶|autonomous\s+driving|特斯拉|tesla|比亚迪|"
                r"智能座舱|车载|网约车|充电桩|电动汽车|\bev\b|车企|轿车|suv|车型"),
    ("游戏", r"游戏|gaming|" + _w(r"steam") + r"|epic\s+games|游戏主机|" + _w(r"ps5") +
            r"|xbox|switch|手游|游戏开发|game\s+dev|电竞|独立游戏|3a|玩家|"
            r"warhammer|战锤|原神|黑神话|塞尔达|任天堂|nintendo|"
            r"dawn\s+of\s+war|游戏ip|主机游戏|益智游戏|puzzle\s+game"),
    ("影音媒体", r"视频|流媒体|streaming|netflix|youtube|音乐|spotify|播客|podcast|"
                r"电影|影视|短视频|直播|hbo|迪士尼|内容创作|自媒体|剧集|综艺|影院"),
    ("设计创意", r"设计|design|" + _w(r"ui") + r"|" + _w(r"ux") + r"|figma|创意|平面设计|"
                r"工业设计|品牌设计|排版|字体|3d\s+建模|动画制作|插画"),
    ("产品与增长", r"产品经理|产品设计|用户增长|growth|运营|marketing|营销|seo|"
                  r"转化率|saas|需求分析|用户体验|indie\s+hacker|独立开发"),
    ("职场商业", r"职场|求职|面试|招聘|远程工作|remote\s+work|自由职业|freelance|"
                r"管理|领导力|创业经验|副业|效率工具|生产力|productivity"),
    ("教育学习", r"教育|学习|课程|教程体系|在线教育|mooc|知识付费|考试|学术|大学|"
                r"科研|science|论文写作|自学"),
    ("生活方式", r"健康|健身|医疗|医学|美食|旅行|旅游|家居|亲子|情感|消费|购物|"
                r"电商|e[\s-]?commerce|亚马逊|amazon|生活"),
    # ---------- 兜底类，放最后 ----------
    # AI 综合：谈 AI 但不落到具体技术/产品形态的泛讨论（AI 时代/AI 热潮/人工智能应用）
    ("AI 综合", r"\bai\b|artificial\s+intelligence|人工智能|aigc|生成式(ai|人工智能)|"
                r"大模型时代|ai\s+(era|boom|hype|story|stories|risk|adoption)|"
                r"machine\s+learning|\bml\b|机器学习|深度学习"),
    ("开源", r"开源|open[\s-]?source|\bgithub\b|apache|mit\s+licen|self[\s-]?host"),
)

_TOPIC_MAX = 5

# 信源分组 → 兜底标签：规则全未命中时用，保证强领域信源不会大面积无标签。
# 只放领域身份明确的组；开发者社区/科技媒体这类杂烩组不兜底（宁可留空也不硬贴）。
_GROUP_FALLBACK_TOPIC = {
    "厂商官方": "AI 综合",
    "学术研究": "AI 综合",
    "AI 媒体": "AI 综合",
    "DSH 生态": "工具框架",
    "DSH生态": "工具框架",
    "安全": "安全",
    "硬件与芯片": "硬件算力",
    "创业与商业": "商业融资",
    "开源生态": "开源",
    "模型优惠与福利": "AI 综合",
}


def topics_of(title, summary=""):
    """抽取领域标签，最多 _TOPIC_MAX 个。

    规则有两种形状：
    - 二元组 (name, pattern)：标题+摘要合并匹配；
    - 三元组 (name, title_pat, summary_pat)：时政/国际专用，标题命中即准入，
      摘要命中必须同时在标题里找到任一强/弱信号，防止摘要泛词（government、
      worldwide 等）把无关资讯误判成时政/国际新闻。
    """
    title = title or ""
    summary = summary or ""
    tl = title.lower()
    hits = []
    for rule in _TOPIC_RULES:
        if len(rule) == 3:
            name, title_pat, summary_pat = rule
            if re.search(title_pat, tl):
                hits.append(name)
            elif re.search(summary_pat, summary.lower()) and re.search(title_pat, tl):
                hits.append(name)
        else:
            name, pat = rule
            if re.search(pat, f"{tl} {summary.lower()}"):
                hits.append(name)
    return hits[:_TOPIC_MAX]


# ---------------------------------------------------------------- 兑换码

_CODE_LABEL_RE = re.compile(
    r"(?:邀请码|兑换码|激活码|优惠码|折扣码|礼品码|promo\s*code|invite\s*code|coupon)\s*[:：]?\s*"
    r"([A-Z0-9][A-Z0-9_-]{2,39})", re.I)
_CODE_SEG_RE = re.compile(r"\b[A-Z0-9]{4,6}(?:-[A-Z0-9]{4,6}){1,3}\b")
_CODE_LONG_RE = re.compile(r"\b[A-Z0-9]{10,40}\b")

# 常见英文词/纯数字不是码
_CODE_STOP = {
    "FREE", "WINNER", "STEAM", "GITHUB", "PROMO", "CODE", "OPENAI", "CLAUDE",
    "GEMINI", "API", "HTTP", "HTTPS", "WWW", "HTML", "JSON", "TRUE", "FALSE",
    "NULL", "TODO", "README", "LICENSE", "MIT", "AI", "GPT", "LLM", "RAG",
    "MCP", "URL", "ID", "CPU", "GPU", "RAM", "SSD", "USB", "PDF", "PNG",
}


def _valid_code(tok):
    tok = tok.strip().strip(".,;:!?()[]<>\"'")
    if not tok or tok.upper() in _CODE_STOP:
        return None
    if tok.isdigit():                       # 纯数字多为价格/数量
        return None
    if not re.search(r"[A-Z]", tok.upper()):  # 必须含字母
        return None
    if len(tok) < 4:
        return None
    return tok


def codes_of(title, summary="", limit=3):
    """抽取兑换码/邀请码，去重后最多 limit 个。"""
    text = f"{title}\n{summary}"
    found, seen = [], set()

    def add(tok):
        tok = _valid_code(tok)
        if tok and tok.lower() not in seen:
            seen.add(tok.lower())
            found.append(tok)

    for m in _CODE_LABEL_RE.finditer(text):
        add(m.group(1))
    for pat in (_CODE_SEG_RE, _CODE_LONG_RE):
        for m in pat.finditer(text):
            add(m.group(0))
            if len(found) >= limit:
                break
        if len(found) >= limit:
            break
    return found[:limit]


# ---------------------------------------------------------------- 噪音判定
# 论坛/羊毛类信源（奶昔论坛等）的 RSS 是「最新话题」流，混进大量二手交易、
# 资费问询帖。这类既不是资讯也归不进任何领域，直接丢弃优于打标签。
# 只对 feeds.json 里显式标了 noise_filter 的源生效（默认关闭），避免误伤
# 正常资讯源里含「出」「收」等字的标题。

_NOISE_RULES = (
    ("交易帖", re.compile(
        r"(出售|转让|求购|收购|闲置|包邮|代购|回收|已出|已售|出货|"
        r"求带|走闲鱼|回血|甩卖|低价出|高价收)")),
    # 标题以交易动词开头（「出一张…」「出V0 MAX」「收个…」）。排除「出品/出行/
    # 发现/出于」等正常词，这类只在论坛类源生效。
    ("交易帖", re.compile(r"^\s*[\[【(（]?(出|收|求|转|清)(?!品|行|版|发|现|于|自|了|售|问|学|账|让)")),
    ("求助/问询帖", re.compile(
        r"(请教|求问|求推荐|老哥们|大佬们|救救|怎么办|怎么弄|"
        r"有没有.{0,14}(推荐|渠道|办法)|是不是.{0,3}(要|能|可以|该|转|换|好|行|办)|"
        r"靠谱吗|值得吗|哪个好|能通过.{0,20}吗)")),
    ("资费问询", re.compile(r"((实名|认证).{0,2}(吗|了|的|？|\?)|转套餐|换套餐|改套餐|"
                            r"转网|保号|靓号|漫游费|套餐(怎么|如何|推荐))")),
    # 论坛纯闲聊/求职帖：没有资讯价值（只在标了 noise_filter 的源生效）
    ("闲聊帖", re.compile(r"(找工作|求职|面试经历|内推|上岸|简历|离职|裁员|"
                          r"同事|老板|吐槽|好难|求助各位|求支招)")),
)

# 明确是「白给福利」的标题：即使命中上面的问询规则也保留
# （例如「我们做了一个免费公益应用（送激活码）」是值得看的内容）
_GIVEAWAY_GUARD = re.compile(
    r"(免费|白嫖|0元|零元|领取|抽奖|赠送|福利|限时领|送.{0,8}(激活码|会员|额度|体验)|"
    r"迎新|新人礼|优惠码|折扣码|返现)")


def noise_reason(title, summary=""):
    """返回噪音原因（字符串），不是噪音返回 None。"""
    text = f"{title or ''} {summary or ''}".strip()
    if not text:
        return None
    title = title or ""
    # 交易帖优先于福利豁免：标题以「出/收」开头的一律按交易处理
    for reason, pat in _NOISE_RULES:
        if pat.search(title):
            if reason == "求助/问询帖" and _GIVEAWAY_GUARD.search(title):
                return None
            return reason
    return None


def drop_noise(entries, log=None):
    """过滤噪音条目，返回 (保留列表, 丢弃列表)。"""
    kept, dropped = [], []
    for e in entries:
        reason = noise_reason(e.get("title"), e.get("summary"))
        if reason:
            dropped.append({"title": e.get("title"), "reason": reason,
                            "source": e.get("source_name")})
        else:
            kept.append(e)
    if dropped and log:
        log(f"  过滤噪音 {len(dropped)} 条（交易/问询帖）")
        for d in dropped[:5]:
            log(f"    - [{d['reason']}] {(d['title'] or '')[:44]}")
    return kept, dropped


# ---------------------------------------------------------------- 跨源近似去重

# 来源优先级：数字越小越优先保留（权威/官方源胜出，其次技术媒体；未列出的源给 50）
_SOURCE_PRIORITY = {
    "厂商官方": 10, "学术研究": 20, "DSH生态": 25, "安全": 30,
    "开源生态": 35, "AI媒体": 40, "科技媒体": 45,
    "技术博客": 55, "开发者社区": 60, "个人与社区": 70,
    "播客": 75, "创业与商业": 50, "硬件与芯片": 30,
}
_DEDUP_THRESHOLD = 0.62   # 词元 Jaccard 阈值
_DEDUP_MIN_TOKENS = 4     # 标题太短不比，防止短标题误合并
_STOP_TOKENS = {"the", "a", "an", "to", "of", "and", "or", "for", "in", "on",
                "with", "is", "are", "was", "how", "why", "what", "from", "at",
                "by", "its", "it", "this", "that", "new", "vs", "你", "的",
                "了", "在", "与", "和", "及", "是"}
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_WORD_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]")


def _norm_title(title):
    return re.sub(r"\s+", " ", (title or "").lower()).strip()


def _title_tokens(title):
    """英文按词、中文按单字切词，去停用词；返回 set。"""
    norm = _norm_title(title)
    toks = set(t for t in _WORD_RE.findall(norm) if t not in _STOP_TOKENS and len(t) > 1)
    return toks


def _jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _entry_time(entry):
    """published 可能是 datetime / ISO 字符串 / 缺失，统一转可比较的 datetime。"""
    p = entry.get("published")
    if isinstance(p, datetime):
        return p if p.tzinfo else p.replace(tzinfo=timezone.utc)
    if isinstance(p, str) and p:
        try:
            dt = datetime.fromisoformat(p.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def cluster_duplicates(entries, threshold=_DEDUP_THRESHOLD, log=None):
    """同语言标题 Jaccard 聚类（渲染层，不改 DB）。

    每个聚类保留一个主条目（来源组优先级高 → 时间新 → 标题长），
    其余条目标 dup_of=<主条目 link>，主条目带 dup_count 与 dup_sources。
    返回 (kept_entries, dropped_count)；kept 保持输入相对顺序。
    """
    prepared = []
    for e in entries:
        title = e.get("zh_title") or e.get("title") or ""
        prepared.append({
            "entry": e,
            "tokens": _title_tokens(title),
            "cjk": bool(_CJK_RE.search(title)),
            "link": e.get("link") or e.get("source_id", ""),
        })

    clusters = []  # 每项: {"rep": idx, "members": [idx...]}
    idx_of = {}
    for i, item in enumerate(prepared):
        if len(item["tokens"]) < _DEDUP_MIN_TOKENS:
            clusters.append({"rep": i, "members": [i]})
            idx_of[i] = len(clusters) - 1
            continue
        best, best_sim = None, 0.0
        for ci, cl in enumerate(clusters):
            rep = prepared[cl["rep"]]
            if rep["cjk"] != item["cjk"]:
                continue  # 只在同语言间比对，防跨语言误杀
            sim = _jaccard(item["tokens"], rep["tokens"])
            if sim >= threshold and sim > best_sim:
                best, best_sim = ci, sim
        if best is None:
            clusters.append({"rep": i, "members": [i]})
            idx_of[i] = len(clusters) - 1
        else:
            clusters[best]["members"].append(i)
            idx_of[i] = best

    def rank_key(idx):
        e = prepared[idx]["entry"]
        grp = e.get("group") or ""
        prio = _SOURCE_PRIORITY.get(grp, 50)
        ts = _entry_time(e)
        ts_key = ts.timestamp() if ts else 0.0
        title_len = len(e.get("zh_title") or e.get("title") or "")
        return (prio, -ts_key, -title_len)

    primary_links = set()
    dropped = 0
    for cl in clusters:
        if len(cl["members"]) < 2:
            primary_links.add(prepared[cl["rep"]]["link"])
            continue
        winner = min(cl["members"], key=rank_key)
        cl["rep"] = winner
        win_link = prepared[winner]["link"]
        primary_links.add(win_link)
        win_entry = prepared[winner]["entry"]
        dup_sources = []
        for idx in cl["members"]:
            if idx == winner:
                continue
            e = prepared[idx]["entry"]
            e["dup_of"] = win_link
            name = e.get("source_name") or e.get("source_id") or "未知源"
            if name not in dup_sources:
                dup_sources.append(name)
            dropped += 1
        win_entry["dup_count"] = len(dup_sources)
        win_entry["dup_sources"] = dup_sources
        if log:
            t = (win_entry.get("zh_title") or win_entry.get("title") or "")[:40]
            log(f"  近似去重：{t}… 合并 {len(dup_sources)} 条（{', '.join(dup_sources[:3])}）")

    kept = [prepared[i]["entry"] for i, item in enumerate(prepared)
            if item["link"] in primary_links]
    return kept, dropped


# ---------------------------------------------------------------- 对外接口

def enrich_entry(entry):
    """原地补 form/obtain/topics/codes，返回同一 dict。"""
    title = entry.get("title") or ""
    summary = entry.get("summary") or ""
    form = form_of(title, summary)
    entry["form"] = form
    entry["obtain"] = obtain_of(title, summary, form)
    topics = topics_of(title, summary)
    if not topics:
        fallback = _GROUP_FALLBACK_TOPIC.get(entry.get("group") or "")
        if fallback:
            topics = [fallback]
    entry["topics"] = topics
    entry["codes"] = codes_of(title, summary)
    return entry


def attach(entries):
    """批量补字段，返回入参列表。"""
    for e in entries:
        enrich_entry(e)
    return entries


def summarize(entries):
    """统计形态与获取方式分布，供日志/report 头使用。"""
    from collections import Counter
    forms = Counter(e.get("form") or "news" for e in entries)
    obtains = Counter(e.get("obtain") for e in entries if e.get("obtain"))
    return {"forms": dict(forms), "obtains": dict(obtains),
            "with_codes": sum(1 for e in entries if e.get("codes"))}
