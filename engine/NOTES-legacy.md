# 封存能力备忘：GitHub 热门项目雷达

> 状态：**保留可用，不主动维护**。日常资讯请用 `radar.py news`。
> 决策记录：2026-11-16 用户确认「保留现状」。

## 它是什么

最初的 ai-git-radar 需求产物——扫 GitHub 热门 AI 项目，按四类目分类、六维评分、出报告：

| 类目 | 覆盖面 |
|---|---|
| `ai-tools` | 应用层 AI 工具：Agent、RAG、MCP、编程助手、生图、工作流 |
| `free-tokens` | 免费额度 + 优惠活动 + 聚合网关 + key 池 + 资源清单 |
| `ai-tech` | 近 120 天新项目、新协议（MCP/A2A/computer use） |
| `agent-skills` | Skills 包、harness（DSH/Claude Code/Cursor）、规则插件 |

硬排除：AI 模型本体开发（权重仓、训练/推理引擎、transformers 式框架、论文复现）。

## 怎么跑

```bash
cd engine
python3 radar.py categories                 # 看类目注册情况
python3 radar.py doctor                     # 环境体检（含额度检查）
python3 radar.py run --quick                # 只用 trending，最快
python3 radar.py run --top 30               # 完整扫描（匿名走网页通路，每仓约 20 秒）
AI_GIT_RADAR_GH_TOKEN=ghp_xxx python3 radar.py run --top 50   # 配 token 走 API，快很多
```

产物：`data/report-*.md` + `report-*.html`（自包含单文件，可直接浏览器打开）。

## 代码构成（1743 行）

| 文件 | 行数 | 职责 |
|---|---|---|
| `scripts/gh_client.py` | 447 | 三档数据通路（API / 网页 / raw）、TTL 缓存、额度耗尽早降级 |
| `scripts/html_report.py` | 417 | 自包含 HTML 报告，零 JS 零外部资源 |
| `scripts/detectors.py` | 213 | 免费额度与优惠活动检测（正则 + 语境过滤） |
| `scripts/report.py` | 205 | Markdown 报告、主类目归属 |
| `scripts/registry.py` | 180 | YAML 类目库、关键词词边界匹配 |
| `scripts/scorer.py` | 145 | 六维评分（热度/健康/前沿/上手/国内/风险） |
| `scripts/classify.py` | 136 | 硬过滤、多类目分类、身份字段隔离 |

外加 `categories/*.yaml` 五个文件（四个类目 + 全局规则）。

## 想扩展类目

新建 `categories/05-xxx.yaml`，照着现有的抄结构即可，`registry.py` 自动加载。
字段：`id / name / desc / topics / name_keywords / strong / weak / max_age_days / strict_topic_match`。

## 已知边界

- 匿名 GitHub API 限流严重（search 10/min、core 60/h），不加 token 时整轮数分钟
- 免费/优惠类目依赖 README 正则，召回受限于候选池（RSS 资讯里这类内容更少）
- 与 news 链路**完全独立**：删掉这七个文件不影响资讯采集（已核实无依赖）

## 相关文档

- 设计口径与坑：`references/`（数据源与已知坑、评分方法论、写作规范）
- 自测覆盖：`scripts/selftest.py` 第 [1]–[11] 组
