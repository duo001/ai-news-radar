"""术语表归一化（v0.16）。

transmart 机翻对 AI 术语的译法不统一：
- Agent 被译成「代理」（与网络代理混淆），行业通行译法是「智能体」
- Token 在 LLM 语境被译成「令牌/代币/标记」三种，行业通行保留英文 Token
- Prompt 被译成「提示/提示符」，行业通行「提示词」
- Agentic 被译成「解释/代理式」等，统一「智能体（式）」

设计原则：
1. 只处理带 source=auto:* 的机翻条目，人工精译（无 source 字段）一字不动
2. 每条规则都有语境护栏，避免误伤非 AI 语义（代理服务器、安全令牌等）
3. 纯函数 normalize_text 可单测；normalize_store 批量改库并记录 normalized_at
"""
from __future__ import annotations

import re
from datetime import datetime, timezone


# 归一化规则：(名称, 编译正则, 替换串, 语境要求)
# 语境要求是对【原文】的判断函数，None 表示不看原文直接替换
def _src_has(*words):
    cre = re.compile(r"\b(?:" + "|".join(words) + r")\b", re.IGNORECASE)
    return lambda src: bool(cre.search(src or ""))


# 「代理」替换时必须排除的非 AI 组合词（网络代理/代理人/代理商等）
_DAILI_GUARD = re.compile(r"代理(?:人|商|服务|器|权|网络|机构|店|厂|品牌|记账|诉讼|律师|投票|选举)")

# 替换前先把护栏组合词临时占位，替换后还原
_PLACEHOLDER = "\x00GUARD\x00"


def _replace_daili(text: str) -> str:
    """代理 → 智能体，但跳过代理服务器/代理人等组合词。"""
    guards = _DAILI_GUARD.findall(text)
    tmp = _DAILI_GUARD.sub(_PLACEHOLDER, text)
    tmp = tmp.replace("代理", "智能体")
    for g in guards:
        tmp = tmp.replace(_PLACEHOLDER, g, 1)
    # 消除替换后的冗余叠词：人工智能智能体 → 智能体
    tmp = tmp.replace("人工智能智能体", "智能体")
    return tmp


# Token 语境：LLM/模型相关的 token 才保留英文；安全令牌(service token)不动
_TOKEN_CTX = re.compile(r"llm|gpt|model|inference|tokenizer|generat|推理|模型|每秒|per second|tokens?/|context window", re.IGNORECASE)

_RULES = [
    # --- Agent 家族（要求原文出现 agent/agency/agentic 词根）---
    ("agent→智能体",
     re.compile(r"代理"),
     lambda m: "智能体",
     _src_has("agent", "agents", "agency", "agentic", "agenticai", "superagent")),
    ("agentic→智能体式",
     re.compile(r"解释(?:性|型)?框架|代理式"),
     lambda m: "智能体式框架" if "框架" in m.group(0) else "智能体式",
     _src_has("agentic")),
    # --- Token 家族（要求原文是 LLM 语境）---
    ("token→Token(LLM语境)",
     re.compile(r"令牌|代币"),
     lambda m: "Token",
     lambda src: bool(_TOKEN_CTX.search(src or ""))),
    # 「标记」只在 tokenizer/token 语境改，且要求原文出现 token 词根
    ("tokenizer标记→Token",
     re.compile(r"标记(?:器|化)?") ,
     lambda m: "Token" + ("izer" if "器" in m.group(0) else ""),
     _src_has("token", "tokens", "tokenizer", "tokenization")),
    # --- Prompt 家族（要求原文出现 prompt 词根）---
    ("prompt→提示词",
     re.compile(r"提示符|提示(?!灯|牌|框|音|剂|词)"),
     lambda m: "提示词",
     _src_has("prompt", "prompts", "prompting")),
]


def normalize_text(zh_text: str, source_text: str = "") -> tuple[str, list[str]]:
    """对单段中文做术语归一化，返回 (新文本, 命中规则名列表)。空文本原样返回。"""
    if not zh_text:
        return zh_text, []
    out = zh_text
    hits = []
    for name, pattern, repl, ctx in _RULES:
        if ctx is not None and not ctx(source_text):
            continue
        if name.startswith("agent→"):
            # 代理规则走带护栏的专用替换
            new = _replace_daili(out)
            if new != out:
                out = new
                hits.append(name)
            continue
        new = pattern.sub(repl, out)
        if new != out:
            out = new
            hits.append(name)
    return out, hits


def normalize_store(store: dict, log=None, dry_run: bool = False) -> dict:
    """批量归一化翻译库（原地修改并返回统计）。

    只动 source 以 "auto:" 开头的机翻条目；人工精译不处理。
    命中任一字段即给条目写 normalized_at 与 normalized_rules。
    返回 {"scanned","changed","rules":Counter}。
    """
    import collections
    stats = {"scanned": 0, "changed": 0, "rules": collections.Counter()}
    for link, item in store.items():
        src = str(item.get("source", ""))
        if not src.startswith("auto:"):
            continue
        stats["scanned"] += 1
        source_blob = " ".join([
            item.get("source_title") or "",
            item.get("source_summary") or "",
        ])
        all_hits = []
        changed = False
        for field in ("zh_title", "zh_summary"):
            old = item.get(field)
            if not old:
                continue
            new, hits = normalize_text(old, source_blob)
            if hits:
                changed = True
                all_hits.extend(hits)
                if not dry_run:
                    item[field] = new
        if changed:
            stats["changed"] += 1
            for h in all_hits:
                stats["rules"][h] += 1
            if not dry_run:
                item["normalized_at"] = datetime.now(timezone.utc).isoformat()
                item["normalized_rules"] = sorted(set(all_hits))
            if log:
                log(f"  归一化 {link}: {', '.join(sorted(set(all_hits)))}")
    stats["rules"] = dict(stats["rules"])
    return stats
