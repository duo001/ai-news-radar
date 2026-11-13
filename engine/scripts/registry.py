# -*- coding: utf-8 -*-
"""声明式类目注册表。

categories/*.yaml 每个文件一个类目，启动时自动发现、加载即注册。
加新类目 = 丢一个新 yaml，无需改任何代码。_global.yaml 是全局规则，不作为类目。
"""
import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
CAT_DIR = ROOT / "categories"


class Category:
    def __init__(self, data, path):
        self.path = path
        self.id = data["id"]
        self.name = data.get("name", self.id)
        self.desc = data.get("desc", "")
        self.enabled = data.get("enabled", True)
        self.topics = [t.lower() for t in data.get("topics", [])]
        self.name_keywords = [k.lower() for k in data.get("name_keywords", [])]
        # core_keywords 支持两种写法：纯列表（全当强词）或 {strong:[...], weak:[...]}
        ck = data.get("core_keywords", [])
        if isinstance(ck, dict):
            self.strong_kw = [k.lower() for k in ck.get("strong", [])]
            self.weak_kw = [k.lower() for k in ck.get("weak", [])]
        else:
            self.strong_kw = [k.lower() for k in ck]
            self.weak_kw = []
        self.readme_signals = data.get("readme_signals", [])
        self.exclude_keywords = [k.lower() for k in
                                 (data.get("exclude", {}) or {}).get("keywords", [])]
        self.keep_lists = data.get("keep_lists", False)
        self.max_age_days = data.get("max_age_days")
        self.card_fields = data.get("card_fields", [])
        # 严格 topic 模式：规则②只认 ≥2 个类目 topic 或本类目强词，
        # 不再接受"单个生态 topic + 泛 AI 身份词"（防止通用工具挂一个标签混入）。
        self.strict_topic_match = data.get("strict_topic_match", False)

    def queries(self, per_page=20):
        """把类目翻译成 GitHub 搜索查询串。

        topic 不支持 OR，每个 topic 单独一条；name_keywords 合并成一条 in:name 兜底。
        ai-tech 类目带 max_age_days 时附加 created:> 条件。
        """
        from datetime import datetime, timedelta, timezone
        out = []
        age = ""
        if self.max_age_days:
            d = (datetime.now(timezone.utc) - timedelta(days=self.max_age_days)).strftime("%Y-%m-%d")
            age = f" created:>{d}"
        for t in self.topics:
            out.append((f"topic:{t}{age} stars:>=30", per_page))
        if self.name_keywords:
            kw = ",".join(self.name_keywords[:8])
            out.append((f"{kw} in:name{age} stars:>=30", per_page))
        return out

    def __repr__(self):
        return f"<Category {self.id}>"


def load_global():
    p = CAT_DIR / "_global.yaml"
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def load_categories(only=None):
    """返回启用的类目列表，按文件名排序（文件名前缀数字即展示顺序）。"""
    cats = []
    for p in sorted(CAT_DIR.glob("*.yaml")):
        if p.name.startswith("_"):
            continue
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if not data.get("enabled", True):
            continue
        if only and data.get("id") not in only:
            continue
        cats.append(Category(data, p))
    if not cats:
        raise RuntimeError(f"categories/ 下没有可用类目：{CAT_DIR}")
    return cats


def _kw_hit(keyword, text):
    """关键词命中。

    纯 ASCII 短词（如 ai/llm/mcp/rag/gpt）必须用词边界，避免 ai 命中 main、
    rag 命中 storage 这类子串误报；含中文等非 ASCII 的词仍走子串匹配。
    """
    import re
    if keyword.isascii():
        return re.search(r"(?<![a-z0-9])" + re.escape(keyword) + r"(?![a-z0-9])", text) is not None
    return keyword in text


# 核心 AI 身份标签：出现一个就足以说明项目是 AI 向。
# 其余类目 topic（mcp/rag/multimodal/computer-use 等）是"协议/技术"标签——
# 非 AI 应用也可能接一个（如健身 App 暴露 mcp 接口），单个不足以准入。
_CORE_AI_TOPICS = {
    "ai", "llm", "llms", "large-language-models", "generative-ai", "genai",
    "ai-agent", "ai-agents", "agentic-ai", "autonomous-agents", "agents",
    "artificial-intelligence", "aigc", "gpt", "chatgpt", "claude",
    "deepseek", "deepseek-harness", "copilot", "ai-tools", "ai-crawler",
    "ai-scraping", "ai-search", "ai-security", "llm-ui", "llm-webui",
}

# 协议/技术词：非 AI 应用也能接一个（健身 App 加 mcp 接口、笔记软件做 rag）。
# 这些词单独出现不准入，必须再有一个 AI 身份信号佐证。
_PROTOCOL_WORDS = {
    "mcp", "rag", "a2a", "computer-use", "multimodal", "inference",
    "evaluation", "vector-database", "embedding", "embeddings",
}

# AI 身份词：命中即说明项目本身是 AI 向（与类目强词表取交集时用）。
_IDENTITY_WORDS = {
    "ai", "llm", "agent", "agents", "gpt", "chatgpt", "chatbot", "copilot",
    "claude", "deepseek", "aigc", "generative-ai", "generative", "大模型",
    "智能体", "人工智能",
}


def _has_identity_signal(cat, text_blob):
    """name/desc/topics 文本里是否有 AI 身份词（给协议词/协议标签做佐证）。"""
    return any(_kw_hit(w, text_blob) for w in _IDENTITY_WORDS)


def match_category(cat, text_blob, topic_blob=""):
    """本地二次校验：候选项目是否属于该类目。

    两个通道严格分开，避免 topic 名冒充关键词：
      · text_blob 只放 name/desc（readme_signals 类目可含 README），强/弱词只在这里匹配
      · topic_blob 只走规则②的 topic 交集，不参与关键词命中

    准入规则（满足其一）：
      ① 在 name/desc 命中 AI 身份强词；协议强词（mcp/rag…）需另有身份词佐证
      ② 项目 topic 与类目 topic 有交集，且满足 AI 亲和度（见下）
      ③ 在 name/desc 命中两个及以上弱信号词
    若类目定义了 readme_signals，则改为必须命中信号正则（免费/优惠类走这条）。

    规则②的 AI 亲和度：命中核心 AI 标签即过；只命中协议/技术标签时，要求
    命中 ≥2 个类目 topic，或 name/desc 另有 AI 身份词佐证（防健身 App 靠一个 mcp 入选）。
    strict_topic_match 类目进一步收紧：单 topic 时只认本类目强词，不认泛身份词。
    """
    import re
    if cat.exclude_keywords and any(_kw_hit(k, text_blob) for k in cat.exclude_keywords):
        return False
    if cat.readme_signals:
        return any(re.search(pat, text_blob, re.I) for pat in cat.readme_signals)

    # 规则①：强词（只在 name/desc 文本，不含 topic）
    strong_hits = [k for k in cat.strong_kw if _kw_hit(k, text_blob)]
    if strong_hits:
        if any(k not in _PROTOCOL_WORDS for k in strong_hits):
            return True
        if _has_identity_signal(cat, text_blob):
            return True

    # 规则②：topic 交集 + AI 亲和度（独立通道）
    if topic_blob:
        repo_topics = {t.strip() for t in re.split(r"[\s,]+", topic_blob) if t.strip()}
        overlap = [t for t in cat.topics if t in repo_topics]
        if overlap:
            if any(t in _CORE_AI_TOPICS for t in overlap):
                return True
            if len(overlap) >= 2:
                return True
            if cat.strict_topic_match:
                # 严格模式：泛 AI 身份词不作数，必须 name/desc 命中本类目生态专属强词
                if any(_kw_hit(k, text_blob) for k in cat.strong_kw):
                    return True
            elif _has_identity_signal(cat, text_blob):
                return True

    weak_hits = sum(1 for k in cat.weak_kw if _kw_hit(k, text_blob))
    return weak_hits >= 2
