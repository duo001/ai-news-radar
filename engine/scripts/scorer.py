# -*- coding: utf-8 -*-
"""情报评分模型（满分 100，六维加权）。

与参考 skill「变现评分」的区别：不评估能不能卖钱，评估值不值得关注/试用。
  热度与增速 25 | 项目健康度 20 | 技术前沿度 15
  可上手性  15 | 国内可用与中文 15 | 风险与合规 10
硬淘汰在 classify.hard_filter 已做；这里只打分。免费 token 类的 high 风险直接压级。
"""
from datetime import datetime, timezone


def _days_since(iso):
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).days
    except Exception:
        return None


def _clip(x, lo=0, hi=100):
    return max(lo, min(hi, x))


def heat_score(repo):
    """热度与增速（25）：绝对星数 15 + 近期涨速 10。"""
    stars = repo.get("stars", 0)
    base = min(15, stars / 500)                      # 7500 星封顶 15
    gained = repo.get("gained", 0)
    if gained > 0:                                   # trending 给了真实涨星
        gain = min(10, gained / 30)                  # 日涨 300 封顶
    else:                                            # 无涨速数据时按星数打折替代
        gain = min(10, stars / 1500)
    return round(base + gain, 1)


def health_score(repo):
    """健康度（20）：最近 push 10 + issue/star 比 5 + 元数据完整度 5。"""
    d = _days_since(repo.get("pushed_at"))
    if d is None:
        push = 5
    elif d <= 7:
        push = 10
    elif d <= 30:
        push = 8
    elif d <= 90:
        push = 5
    elif d <= 180:
        push = 2
    else:
        push = 0
    stars = max(repo.get("stars", 1), 1)
    ratio = (repo.get("open_issues") or 0) / stars
    issue = 5 if ratio < 0.02 else 3.5 if ratio < 0.06 else 2 if ratio < 0.15 else 0.5
    meta = sum([bool(repo.get("license")), bool(repo.get("homepage")),
                bool(repo.get("topics")), bool(repo.get("desc"))]) * 1.25
    return round(push + issue + min(5, meta), 1)


def frontier_score(repo, cat):
    """前沿度（15）：项目越新越高；ai-tech 类目有年龄上限，整体再加分。"""
    d = _days_since(repo.get("created_at"))
    if d is None:
        age = 7
    elif d <= 30:
        age = 15
    elif d <= 90:
        age = 12
    elif d <= 180:
        age = 9
    elif d <= 365:
        age = 6
    else:
        age = 3
    if cat and cat.id == "ai-tech":
        age = min(15, age + 2)
    return float(age)


def usability_score(eng):
    """可上手性（15）：文档/demo/docker/一键部署信号。"""
    s = 0
    s += 4 if eng.get("has_one_click") else 0
    s += 3 if eng.get("has_deploy_doc") else 0
    s += 3 if eng.get("has_docker") or eng.get("has_cloud_button") else 0
    s += 3 if eng.get("has_demo") else 0
    s += 2 if eng.get("has_chinese") else 0
    return float(min(15, s))


def china_score(eng, detector):
    """国内可用与中文（15）：中文文档 8 + 国内直连信号 7。"""
    s = 8 if eng.get("has_chinese") else 3
    cn = (detector or {}).get("china", "")
    if "国内" in cn and "直连" in cn:
        s += 7
    elif "代理" in cn or "受限" in cn:
        s += 1
    else:
        s += 3
    return float(min(15, s))


def risk_score(repo, detector):
    """风险与合规（10）：许可证 + 安全风险标记。"""
    lic = (repo.get("license") or "").upper()
    s = 6 if lic and lic != "NOASSERTION" else 2 if lic else 0
    for r in (detector or {}).get("risks", []):
        if r["level"] == "high":
            s -= 5
        elif r["level"] == "medium":
            s -= 2
        else:
            s -= 0.5
    return float(_clip(s, 0, 10))


def grade(total):
    if total >= 80:
        return "S"
    if total >= 65:
        return "A"
    if total >= 50:
        return "B"
    return "C"


def score(repo, cat, eng, detector=None):
    """返回总分、等级与六维明细分（报告直接展示，让分数可解释）。"""
    dims = {
        "热度与增速": heat_score(repo),                    # 满分 25
        "项目健康度": health_score(repo),                  # 满分 20
        "技术前沿度": frontier_score(repo, cat),           # 满分 15
        "可上手性": usability_score(eng),                  # 满分 15
        "国内与中文": china_score(eng, detector),          # 满分 15
        "风险与合规": risk_score(repo, detector),          # 满分 10
    }
    total = round(sum(dims.values()), 1)
    g = grade(total)
    # 免费 token 类 high 风险：强制不超过 B，避免把危险项目评成推荐
    if detector:
        if any(r["level"] == "high" for r in detector.get("risks", [])) and g in ("S", "A"):
            g = "B"
    return {"total": total, "grade": g, "dims": dims}
