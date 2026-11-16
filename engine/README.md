# ai-git-radar · AI 资讯雷达

**v0.6 起主力是 RSS/Atom 资讯**：并发聚合 14 个零密钥 AI 资讯信源，清洗、分组、
套用中文翻译，一次产出 Markdown + 自包含单文件 HTML + JSON 三份资讯速递。
8 路并发约 20 秒采完，零 API 额度。

GitHub 项目扫描能力（分类 + 六维情报评分）**封存为 legacy 保留可用**（`run` 子命令）。
参考「夜秣 git 副业雷达」的架构骨架，重写了类目体系与评分模型。

## 快速开始

```bash
pip install requests pyyaml          # 仅 GitHub legacy 通路需要；资讯模块纯标准库
cd scripts
python3 radar.py doctor               # 自检（含资讯信源与缓存体检）

# —— 主力：资讯 ——
python3 radar.py news                 # 并发拉信源，出 data/news-*.{md,html,json} 并套中文翻译
python3 radar.py news --offline       # 只用缓存，离线出资讯（亚秒级）
python3 radar.py news --only 学术研究   # 按信源 id 或分组过滤
python3 radar.py translate --news --todo    # 导出英文标题待译清单
# 填好 zh_title / zh_summary 后：
python3 radar.py translate --news --apply   # 合并进 news_translations.json（已译不覆盖）并重渲染

# —— 已封存 legacy：GitHub 项目 ——
python3 radar.py run --quick          # 只看今日 trending
python3 radar.py run                  # trending + Search 全量，默认深度分析前 50
python3 radar.py translate --todo     # 仓库简介翻译（另一套翻译库）

python3 radar.py source-check         # 信源体检：静默源/故障源/health 孤儿（v0.15，纯本地）
python3 radar.py weekly               # 近 7 天周报 Markdown（含关注专区、主题分区、体检附榜）
python3 radar.py backup               # 资产备份：翻译库/已读/关注词/DB → data/backups/*.zip
python3 selftest.py                   # 离线回归测试（20 组断言）
```

每次 `news` 产出三份同一数据的文件：`data/news-*.html`（自包含单文件，浏览器直接打开）、
`data/news-*.md`、`data/news-*.json`；资讯翻译库 `data/news_translations.json` 按文章链接
建 key。示例批次（42 条、100% 中文化）固化为 `data/sample-news.{md,html,json}`。
信源配置在 `data/sources/feeds.json`（加源只改数据不改代码），feed 缓存在
`data/cache/feeds/`（3h TTL，单源失败自动容错并回退缓存）。

### 把 HTML 报告截成长图

`tools/lightpanda` 是 Zig 写的轻量无头浏览器单二进制（约 74MB，无系统依赖），
配 `tools/screenshot.py` 可把 HTML 截成 1920 宽全页 PNG，适合发群/存档：

```bash
python3 tools/screenshot.py            # 截最新 report-*.html，输出同名 .png
python3 tools/screenshot.py 某报告.html --port 8790
```

## 目录

```
ai-git-radar/
├── SKILL.md                 # Agent 执行契约与触发说明
├── config.json              # 可选 gh_token（仅 legacy GitHub 通路）
├── categories/              # ★ 声明式 GitHub 类目（legacy，扩展只动这里）
│   ├── _global.yaml         # 全局硬规则：模型本体排除、门槛
│   ├── 01-ai-tools.yaml
│   ├── 02-free-tokens.yaml  # 免费 + 优惠 token
│   ├── 03-ai-tech.yaml
│   └── 04-agent-skills.yaml # Agent 生态：skills / DSH / Claude Code（严格 topic 模式）
├── scripts/
│   ├── radar.py             # CLI 入口：news(主力)/weekly(周报)/translate/doctor；run/render(legacy)
│   ├── feeds.py             # ★ RSS/Atom 采集：并发、gzip 解压、样式清洗、容错+缓存回退
│   ├── collectors.py        # ★ 结构化采集器：OpenRouter 免费模型 / HN AI（零 key JSON API）
│   ├── enrich.py            # ★ 正交分类：form/obtain/topics（29 标签含时政/国际，不局限 AI）/codes
│   ├── watch.py             # ★ 关键词关注：watch.json 声明式配置 + 面板 CRUD，整词/子串匹配，渲染层打 watch_hits
│   ├── sourcecheck.py       # ★ 信源体检（v0.15）：静默源/连续故障/health 孤儿，纯本地不联网
│   ├── netcfg.py            # ★ 网络出口（v0.17）：面板配代理后全部外网请求统一走它
│   ├── glossary.py          # ★ 术语归一化（v0.17）：Agent/Token/Prompt 带语境护栏后处理
│   ├── backup.py            # ★ 资产备份（v0.17）：翻译库/已读/关注词/DB 打包 zip
│   ├── db.py                # SQLite 持久化（30 天保留、UPSERT by link、temp_store=MEMORY）
│   ├── discover.py          # 信源自动发现：网页声明/常见路径/OPML 目录/远程清单 → 待审队列
│   ├── mt.py                # 免费机翻（腾讯 transmart 主通道，零 key，双预算切片）
│   ├── i18n.py              # 两套翻译库：资讯(按 link) + 仓库(按 owner/repo)，已译不覆盖
│   ├── gh_client.py         # [legacy] GitHub 抓取：API/网页/raw 三通路 + 缓存
│   ├── registry.py          # [legacy] 类目加载与查询生成、强弱词/双通道校验
│   ├── classify.py          # [legacy] 硬过滤 + 多类目分类
│   ├── detectors.py         # [legacy] 免费额度/优惠活动/安全风险/工程信号
│   ├── scorer.py            # [legacy] 六维情报评分
│   ├── report.py            # Markdown 渲染（资讯 + legacy 项目，中文优先、主归属常量）
│   ├── html_report.py       # 自包含单文件 HTML（内联 CSS、零 JS、资讯/项目两套渲染）
│   └── selftest.py          # 离线回归（20 组）
├── references/              # 设计文档（数据源坑 30 条、评分方法论）
├── tools/
│   ├── lightpanda           # 轻量无头浏览器二进制（HTML→全页 PNG）
│   └── screenshot.py        # 一键把报告截成长图
└── data/
    ├── sources/feeds.json       # ★ RSS/Atom 信源表（128 源/13 组，加源只改这里）
    ├── sources/collectors.json  # ★ 结构化采集器配置（2 启用 / 4 预置停用）
    ├── sources/watch.json       # ★ 关键词关注列表（watch_hits，改完即生效）
    ├── cache/feeds/             # feed XML 缓存（3h TTL，离线回退）
    ├── cache/collectors/        # 采集器 JSON 缓存（3h TTL）
    ├── sample-news.*        # 资讯示例批次（42 条，100% 中文翻译）
    ├── news_translations.json  # 资讯翻译库（按文章 link）
    └── sample-report.* / sample-run.json / translations.json  # legacy GitHub 示例
```

## 加一个资讯信源 / GitHub 类目

- **资讯源**：在 `data/sources/feeds.json` 的 `sources` 数组追加一条
  （`id/name/url/kind(rss|atom)/group/tags/enabled`），`doctor` 自动纳入体检，无需改代码。
- **GitHub 类目**（legacy）：复制任一 `categories/*.yaml`，改 `id/name/topics/core_keywords`，
  下次运行自动出现在报告里。规则写法（强弱词、`strict_topic_match`、双通道隔离）
  见 SKILL.md「怎么扩展」。

## 边界

资讯只接零密钥 RSS/Atom，需要 key 的信源类型（X 搜索、公众号、网页选择器等）不做；
翻译由 Agent/人工完成、脚本不内置机翻也不引入翻译 API 密钥，已译内容跨天复用；
legacy GitHub 通路只做 README 静态分析、不实测第三方 API；HTML 报告零 JS、纯内联 CSS；
暂无跨天查重、定时任务（后续版本规划，见 SKILL.md）。
