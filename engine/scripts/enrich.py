"""资讯增强：规则版内容形态 / 获取方式 / 领域标签 / 兑换码抽取。

借鉴 ZiChuanLan/freebie-radar 的正交分类模型（kind × category × obtain），
但**不调 AI、不花额度**——全部用关键词规则，确定性、可回归、零成本。

- form（内容形态）：freebie / deal / release / paper / tutorial / opensource / news
- obtain（获取方式）：free / conditional / lottery / trial / promo / paid（仅福利类有意义）
- topics（领域标签）：模型 / Agent / MCP / RAG / 推理部署 / 多模态 / 训练微调 /
  工具框架 / 安全 / 硬件算力 / 政策合规 / 商业融资 / 评测榜单 / 开源
- codes（兑换码/邀请码）：黄色胶囊一键复制

用法：
    import enrich
    enrich.attach(entries)       # 原地批量补字段
    enrich.form_of(title, summary)
"""

import re

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
    ("模型", r"\b(gpt|claude|gemini|llama|qwen|deepseek|kimi|mistral|gemma|o[134])\b|"
              r"大模型|模型(发布|升级|迭代)|新模型|frontier\s+model"),
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
    ("安全", r"安全|security|漏洞|vulnerab|攻击|attack|注入|prompt\s+injection|供应链|"
             r"supply[\s-]?chain|越狱|jailbreak|隐私|privacy|malware|恶意|"
             r"rubygems?|npm\s+attack|数据泄露|breach|phishing|钓鱼"),
    ("硬件算力", r"\bgpu\b|h100|h200|b200|gb200|算力|芯片|tpu|npu|数据中心|显存|"
                r"infrastructure|accelerator"),
    ("政策合规", r"监管|regulat|合规|法案|政策|禁令|\bban\b|版权|著作权|copyright|"
                r"欧盟|eu\s+ai\s+act"),
    ("商业融资", r"融资|funding|估值|valuation|\bipo\b|收购|acquisition|营收|revenue|"
                r"裁员|layoff"),
    ("评测榜单", r"benchmark|评测|榜单|leaderboard|\bsota\b|排行|评测集|eval"),
    ("开源", r"开源|open[\s-]?source|\bgithub\b|apache|mit\s+licen|self[\s-]?host"),
)

_TOPIC_MAX = 4


def topics_of(title, summary=""):
    """抽取领域标签，最多 4 个。"""
    text = f"{title} {summary}".lower()
    hits = [name for name, pat in _TOPIC_RULES if re.search(pat, text)]
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


# ---------------------------------------------------------------- 对外接口

def enrich_entry(entry):
    """原地补 form/obtain/topics/codes，返回同一 dict。"""
    title = entry.get("title") or ""
    summary = entry.get("summary") or ""
    form = form_of(title, summary)
    entry["form"] = form
    entry["obtain"] = obtain_of(title, summary, form)
    entry["topics"] = topics_of(title, summary)
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
