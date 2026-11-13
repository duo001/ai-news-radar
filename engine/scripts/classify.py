# -*- coding: utf-8 -*-
"""分类与硬过滤层。

职责：
  1. 全局硬淘汰（归档 / fork / 星数门槛 / 模型本体 / 清单类）
  2. 给候选项目打类目标签（可同时属于多个类目）
规则全部来自 categories/_global.yaml 和各类目 yaml，代码不写死业务词。
"""
import re
from datetime import datetime, timezone

from registry import load_global, match_category


def _age_days(repo):
    """项目年龄（天）。created_at 缺失返回 None（不卡年龄，交给搜索串的 created:> 兜底）。"""
    ca = repo.get("created_at")
    if not ca:
        return None
    try:
        created = datetime.fromisoformat(ca.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - created).days
    except Exception:
        return None

_GLOBAL = None


def global_rules():
    global _GLOBAL
    if _GLOBAL is None:
        _GLOBAL = load_global()
    return _GLOBAL


def _blob(repo, readme=""):
    """全量文本（含 README）：供模型本体排除等"否决型"规则使用，宁可错杀。"""
    parts = [repo.get("full_name", ""), repo.get("name", ""), repo.get("desc", ""),
             " ".join(repo.get("topics", [])), (readme or "")[:3000]]
    return " ".join(parts).lower()


def _identity_blob(repo):
    """项目自述身份文本：只含 name/desc，不含 README、不含 topics。

    分类准入只信身份字段——README 里的徽章、依赖名、链接（如 dosu-ai 徽章）
    会制造大量假阳性，不能作为"这是 AI 项目"的依据。
    topics 走独立的 topic 交集通道（见 registry.match_category），不能拼进
    文本 blob，否则一个叫 "skills" 的 topic 会冒充 skill 关键词造成误准入。
    """
    parts = [repo.get("full_name", ""), repo.get("name", ""), repo.get("desc", "")]
    return " ".join(parts).lower()


def is_list_repo(repo, rules):
    """awesome / 清单类识别。"""
    cfg = rules.get("exclude_lists", {})
    name = repo.get("name", "").lower()
    desc = (repo.get("desc", "") or "").lower()
    np = cfg.get("name_pattern")
    dp = cfg.get("desc_pattern")
    if np and re.search(np, name):
        return True
    if dp and re.search(dp, desc):
        return True
    return False


def is_model_body(repo, readme, rules):
    """模型本体硬排除：权重仓 / 训练推理引擎 / 纯论文复现。

    命中 topic 或关键词任一即排除；size 启发式需同时命中 weight/checkpoint 词。
    """
    cfg = rules.get("exclude_model_body", {})
    blob = _blob(repo, readme)
    topics = {t.lower() for t in repo.get("topics", [])}
    if topics & {t.lower() for t in cfg.get("topics", [])}:
        return True
    for pat in cfg.get("keywords", []):
        if re.search(pat, blob, re.I):
            return True
    size_gb = (repo.get("size_kb") or 0) / 1024 / 1024
    limit = cfg.get("size_heuristic_gb", 8)
    if size_gb >= limit and re.search(r"weight|checkpoint|\.safetensors|\.gguf", blob):
        return True
    return False


def hard_filter(repo, cat, readme, rules):
    """返回 (通过, 淘汰原因)。cat 为 None 表示全局门槛检查。"""
    hf = rules.get("hard_filters", {})
    if hf.get("exclude_archived", True) and repo.get("archived"):
        return False, "已归档"
    if hf.get("exclude_fork", True) and repo.get("fork"):
        return False, "fork 仓"
    if repo.get("stars", 0) < hf.get("min_stars", 30):
        return False, f"星数<{hf.get('min_stars', 30)}"
    if is_model_body(repo, readme, rules):
        return False, "模型本体（全局排除）"
    if is_list_repo(repo, rules) and not (cat and cat.keep_lists):
        return False, "清单类（本类目不保留）"
    return True, ""


def classify(repo, categories, readme=""):
    """返回该 repo 命中的类目 id 列表（一个项目可进多个类目）。"""
    rules = global_rules()
    # 准入只看身份字段；免费/优惠类目例外——它的信号天然在 README 里，用全量文本
    identity = _identity_blob(repo)
    full = _blob(repo, readme)
    topic_blob = " ".join(t.lower() for t in repo.get("topics", []))
    hits = []
    for cat in categories:
        ok, _ = hard_filter(repo, cat, readme, rules)
        if not ok:
            continue
        # 类目年龄上限（如 ai-tech 只收近 120 天的项目）
        if getattr(cat, "max_age_days", None):
            age = _age_days(repo)
            if age is not None and age > cat.max_age_days:
                continue
        blob = full if cat.readme_signals else identity
        if match_category(cat, blob, topic_blob):
            hits.append(cat.id)
    return hits


def reject_reason(repo, categories, readme=""):
    """对不属于任何类目的候选，给出最有解释力的淘汰原因（报告调试用）。"""
    rules = global_rules()
    base_ok, reason = hard_filter(repo, None, readme, rules)
    if not base_ok:
        return reason
    if is_model_body(repo, readme, rules):
        return "模型本体（全局排除）"
    return "未命中任何类目信号"
