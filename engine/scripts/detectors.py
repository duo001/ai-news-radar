# -*- coding: utf-8 -*-
"""README 静态信号检测器。

全部基于文本正则，不实际调用任何第三方 API、不需要用户 key（用户明确选择的 v1 范围）。
四块能力：
  1. 免费 token/额度信号：额度内容、注册门槛、国内可用性
  2. 优惠活动信号：折扣、优惠券、首充赠送、限时活动、返现
  3. 安全风险：第三方 key 池 / 代理网关的偷 key 与中间人风险
  4. 通用工程信号：demo、docker、一键部署、中文文档（供评分用）
"""
import re

# ----------------------------------------------------------- 免费额度

# 额度内容：尽量抽出"多少 + 单位 + 周期"的片段
_QUOTA_PATTERNS = [
    r"(?:free|免费|赠送|含|送)[^。\n]{0,40}?(\d[\d,\.]*\s*(?:k|m|million|万|千)?\s*(?:tokens?|credits?|次|calls?|requests?))[^。\n]{0,30}",
    r"(\$\d+(?:\.\d+)?\s*(?:free )?(?:credits?|额度|in free))",
    r"(\d+\s*(?:requests?|calls?|次)[^。\n]{0,20}(?:per|/|每)\s*(?:day|month|minute|天|月|分钟))",
    r"(free tier[^。\n]{0,80})",
    r"(免费额度[^。\n]{0,80})",
]

# 注册门槛。
# 注意顺序坑："no credit card required" 含 "credit card"，必须先判否定式，
# 命中否定式后跳过肯定式，否则同一项目会同时出现"需信用卡/无需信用卡"。
_SIGNUP_SIGNALS = [
    (r"phone\s*(number|verification)|手机(号)?验证", "需手机验证"),
    (r"waitlist|候补|排队|邀请码|invite[ -]?only", "需候补/邀请"),
    (r"student|学生包|edu\s*mail|教育邮箱", "学生/教育优惠"),
    (r"github\s*(account|oauth)|github 登录|github 授权", "GitHub 账号即可"),
]
_CARD_YES = re.compile(r"credit\s*card|信用卡", re.I)
_CARD_NO = re.compile(r"(?:no|without|无需|免|不需要)\s*credit\s*card|无需信用卡|免信用卡|不需要信用卡", re.I)

# 国内可用性
_CN_DIRECT = [
    r"deepseek|智谱|zhipu|glm|月之暗面|moonshot|kimi|通义|qwen|dashscope|百炼",
    r"豆包|doubao|火山|方舟|百度|文心|ernie|讯飞|星火|minimax|阶跃|stepfun",
    r"硅基流动|siliconflow|腾讯云|阿里云|华为云|天翼",
]
_PROXY_HINT = [r"需(要)?翻墙|需(要)?代理|not available in china|blocked in china|国内无法直连"]

# 项目形态
_FORM_SIGNALS = [
    (r"one-api|new-api|one api", "聚合网关（one-api 系）"),
    (r"litellm", "统一网关（LiteLLM）"),
    (r"openrouter", "OpenRouter 路由"),
    (r"api[- ]?key.{0,12}(池|pool|分享|共享|免费领取)|白嫖", "key 池/白嫖集合"),
    (r"mirror|镜像站|反向代理|reverse proxy", "镜像/反代站"),
    (r"awesome|curated list|资源合集|导航|清单", "资源清单"),
    (r"free program|free tier 合集|免费(额度|api)合集", "免费政策合集"),
]

# ----------------------------------------------------------- 优惠活动

# 优惠活动：分类型，命中后在报告里单独成块（优惠有时效，提示用户先核日期）
_PROMO_PATTERNS = [
    (r"promo(?:tion)?(?:[ _-]?code)?|优惠券?|优惠码|促销(?:码|活动)?", "折扣/促销码"),
    (r"coupon|voucher", "优惠券"),
    (r"(\d{1,2})\s*%\s*off|立减\s*\d+|直降\s*\d+", "百分比折扣"),
    (r"bonus credits?|double credits?|extra credits?|额外(赠送|加送).{0,6}(credit|token|额度)", "加赠额度"),
    (r"rebate|cashback|返现|返利", "返现/返利"),
    (r"首充|充值.{0,10}(赠送|返|送)|充\s*\d+\s*送", "首充/充值赠送"),
    (r"black friday|黑五|cyber monday|周年庆|新年(优惠|活动)|new year deal|双\s*11|618", "节点大促"),
    (r"limited[- ]time(?: offer)?|限时(优惠|免费|折扣|活动)|deal[s]?\s+alert", "限时活动"),
    (r"学生(优惠|折扣|免费)|student discount|edu(?:cation)?\s*(?:discount|deal)", "学生优惠"),
]

# 只有"优惠"没有任何 token/API/额度语境的，视为噪声（避免把卖 VPN、云主机折扣拉进来）
_PROMO_CONTEXT = [
    r"token|credit|api|llm|gpt|model|额度|大模型|算力|推理|inference",
]


def detect_promos(text):
    """抽取优惠活动，返回 [{type, detail}]；无 token/API 语境的优惠不计入。"""
    if not re.search("|".join(_PROMO_CONTEXT), text, re.I):
        return []
    seen, out = set(), []
    for pat, label in _PROMO_PATTERNS:
        for m in re.finditer(pat, text, re.I):
            frag = re.sub(r"\s+", " ", m.group(0)).strip()
            if frag.lower() in seen or len(frag) > 80:
                continue
            seen.add(frag.lower())
            out.append({"type": label, "detail": frag})
    return out[:6]


# ----------------------------------------------------------- 安全风险

_RISK_RULES = [
    # 要求把官方 key 填进非官方服务 = 最高风险。
    # 中文语序两种都要覆盖：「粘贴 key 到本站」（动词在前）与「把 key 粘贴到本站」（key 在前）。
    (r"(填入|粘贴|输入|enter|paste|put).{0,20}(api[ -]?key|token|密钥).{0,30}(本站|本服务|本项目|平台|here|this (service|site|gateway))",
     "high", "要求把官方 API key 填入第三方服务，存在 key 被盗用风险"),
    (r"(api[ -]?key|token|密钥)[^。\n]{0,24}(填入|粘贴|输入|发给|上传|提交|paste|enter|send)[^。\n]{0,24}(本站|本服务|本项目|平台|第三方|here|this (service|site|gateway))",
     "high", "要求向第三方提交/填入密钥，存在 key 泄露风险"),
    # 第三种语序：「在本服务/本站/平台 填入 key」——第三方标记在动词之前
    (r"(?:在|于)\s*(?:本站|本服务|本项目|平台|第三方|this (?:service|site|gateway))[^。\n]{0,12}(?:填入|粘贴|输入|paste|enter|send)[^。\n]{0,12}(api[ -]?key|token|密钥)",
     "high", "要求在第三方服务内填入密钥，存在 key 泄露风险"),
    (r"(api[ -]?key|token|密钥).{0,16}(发给|上传|提交到|send to|upload to).{0,20}(第三方|本站|平台)",
     "high", "要求向第三方提交密钥，存在泄露风险"),
    # 非官方域名代理官方 API
    (r"https?://(?!api\.openai\.com|api\.anthropic\.com|generativelanguage\.googleapis\.com)[a-z0-9.-]+\.(?:com|net|io|ai|cn|app)[^\s]{0,40}/v1/(chat/completions|messages)",
     "medium", "通过非官方域名代理官方 API，存在中间人/记录请求风险"),
    (r"免费.{0,6}代理|公益.{0,6}代理|free\s+proxy\s+(api|gpt|openai)",
     "medium", "公益/免费代理服务，稳定性与数据安全无保障"),
    # 免责声明缺失本身不是风险，但"免责声明 + 不担责"要提示
    (r"use at your own risk|不承担.{0,6}责任|风险自负|as[- ]is",
     "low", "项目声明风险自负，使用前自行评估"),
]


def _first(patterns, text, flags=re.I):
    for pat in patterns:
        m = re.search(pat, text, flags)
        if m:
            return m
    return None


def detect_token_offer(readme, desc=""):
    """免费/优惠 token 项目的结构化抽取。文本为空时返回 None（调用方据此跳过）。

    入选两类信号任一成立：
      ① 免费额度（free tier / 免费额度 / 白嫖 / 聚合网关形态等）
      ② 优惠活动（折扣 / 优惠券 / 首充赠送 / 限时活动，且处于 token/API 语境）
    """
    text = f"{desc}\n{readme or ''}"
    if not text.strip():
        return None
    out = {"is_free_token": False, "has_promo": False, "offer_type": [],
           "quotas": [], "promos": [], "signup": [], "china": "",
           "form": [], "risks": []}

    quota_hits = set()
    for pat in _QUOTA_PATTERNS:
        for m in re.finditer(pat, text, re.I):
            frag = re.sub(r"\s+", " ", m.group(1) if m.groups() else m.group(0)).strip()
            if 3 < len(frag) < 120:
                quota_hits.add(frag)
    out["quotas"] = sorted(quota_hits)[:5]
    free_hit = bool(quota_hits) or _first(
        [r"free[ -]?tier", r"free credits?", r"免费额度", r"白嫖", r"free api key"], text) is not None
    out["is_free_token"] = free_hit

    out["promos"] = detect_promos(text)
    out["has_promo"] = bool(out["promos"])

    for pat, label in _FORM_SIGNALS:
        if re.search(pat, text, re.I):
            out["form"].append(label)

    # 准入：免费信号 / 优惠信号 / 类目形态（网关·key池·镜像·清单）任一成立
    form_hit = bool(out["form"])
    if not free_hit and not out["has_promo"] and not form_hit:
        return None

    out["offer_type"] = ((["免费额度"] if free_hit else [])
                         + (["优惠活动"] if out["has_promo"] else [])
                         + (["形态相关"] if (not free_hit and not out["has_promo"]) else []))

    for pat, label in _SIGNUP_SIGNALS:
        if re.search(pat, text, re.I):
            out["signup"].append(label)
    # 信用卡：否定式优先（"no credit card required" 不得误判为需要信用卡）
    if _CARD_NO.search(text):
        out["signup"].append("无需信用卡")
    elif _CARD_YES.search(text):
        out["signup"].append("需信用卡")

    if _first(_CN_DIRECT, text):
        out["china"] = "国内厂商/国内可直连"
    elif _first(_PROXY_HINT, text):
        out["china"] = "需代理/国内受限"
    else:
        out["china"] = "未注明（默认按海外服务对待）"

    out["risks"] = detect_risks(text)
    return out


# 向后兼容旧函数名（radar.py / 测试代码可能已引用）
def detect_free_token(readme, desc=""):
    return detect_token_offer(readme, desc)


def detect_risks(text):
    """安全风险检测，返回 [{level, note}]，按 high→low 去重排序。"""
    rank = {"high": 0, "medium": 1, "low": 2}
    seen, out = set(), []
    for pat, level, note in _RISK_RULES:
        if re.search(pat, text, re.I | re.S) and note not in seen:
            seen.add(note)
            out.append({"level": level, "note": note})
    return sorted(out, key=lambda r: rank[r["level"]])


# ----------------------------------------------------------- 通用工程信号

def engineering_signals(readme, desc=""):
    """供可上手性 / 中文友好评分维度使用。"""
    text = f"{desc}\n{readme or ''}"
    return {
        "has_demo": bool(re.search(r"demo|在线体验|live preview|try it|huggingface\.co/spaces", text, re.I)),
        "has_docker": bool(re.search(r"docker|dockerfile|compose\.ya?ml", text, re.I)),
        "has_one_click": bool(re.search(r"one[- ]?click|一键|quickstart|getting started|5\s*minute", text, re.I)),
        "has_chinese": bool(re.search(r"[\u4e00-\u9fff]{20,}", text)),
        "has_deploy_doc": bool(re.search(r"deploy|部署|installation|安装|setup", text, re.I)),
        "has_cloud_button": bool(re.search(r"vercel|railway|render\.com|zeabur|一键部署到", text, re.I)),
    }
