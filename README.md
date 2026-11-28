# ai-news-radar

AI 资讯工作台：并发聚合 **526 个零密钥 RSS/Atom 信源** + 2 个结构化采集器，清洗、分组、
去重、套用中文翻译，既可作为 **DSH 工作台插件**常驻侧边栏，也可作为 **Agent Skill /
命令行工具**独立运行。

当前版本 **v0.18.20**。

[![selftest](https://github.com/duo001/ai-news-radar/actions/workflows/selftest.yml/badge.svg)](https://github.com/duo001/ai-news-radar/actions/workflows/selftest.yml)

> CI 为**手动触发**（Actions 页 → selftest → Run workflow），在 Python 3.10 / 3.12 上跑
> **27 组 / 367 条**离线断言 + 语法检查 + 信源配置校验。日常提交前本地跑
> `python engine/scripts/selftest.py` 即可，push 不触发 run。

## 能力概览

| 能力 | 说明 |
|---|---|
| 资讯聚合 | 526 个 RSS/Atom 信源 + OpenRouter 免费模型 / Hacker News 结构化采集器，8 路并发，单源容错、失败回退缓存 |
| 正交分类 | `form`（形态）/ `obtain`（获取方式）/ `topics`（30 个领域标签，含时政/国际/AI 综合兜底）/ `codes`（邀请码）四维独立打标 |
| 中文翻译 | 免费机翻（Bing 网页主通道，失败降级腾讯 transmart/MyMemory，零 key）+ 人工精译双通道，机翻不覆盖精译；术语归一化后处理 |
| 近似去重 | 同语言标题 Jaccard ≥ 0.62 折叠为一条，保留权威源作主条，标注「另有 N 家」 |
| 关键词关注 | 声明式关注词，渲染层打 `watch_hits` 标签，面板可按词筛选 + 高亮 |
| 周报导出 | 近 N 天按主题分组导出 Markdown，含关注词专区与信源体检附榜 |
| 信源治理 | 四条自动发现通道 + 待审队列人工决策；健康检查连续失败自动停用 |
| 运维 | 免费机翻、代理出口、资产备份、前端错误日志、离线自测 |

## 仓库结构（monorepo）

```
ai-news-radar/
├── engine/                       # Python 引擎（同时是一个 DSH Skill，资讯通路纯标准库）
│   ├── SKILL.md                  # Skill 执行契约
│   ├── README.md                 # 引擎详细说明
│   ├── NOTES-legacy.md           # GitHub 项目雷达（封存）说明
│   ├── scripts/                  # radar.py 入口 + 20 个脚本（采集/分类/翻译/运维）
│   ├── categories/               # GitHub 项目雷达的声明式类目（legacy）
│   ├── references/               # 数据源与已知坑（56 条）、评分方法论
│   ├── tools/                    # lightpanda 截图（可选，二进制不入库）
│   └── data/
│       ├── sources/feeds.json         # ★ 资讯信源表（526 条，加源只改这里）
│       ├── sources/collectors.json    # ★ 结构化采集器（2 启用 / 4 预置停用）
│       ├── sources/watch.json         # ★ 关键词关注列表
│       ├── sources/discover-seeds.json# 网页发现种子站（30 个首页）
│       ├── sources/opml-catalog.json  # 内置 OPML 社区目录
│       ├── deals.json                 # 优惠卡（AI 产品折扣/免费额度）
│       └── sample-*                   # 示例产物（md/html/json）
└── plugin/                       # DSH 工作台插件（@local/ai-news-panel）
    ├── index.js                  # Host 半：webServer 路由 + subprocess 调引擎
    ├── client.js                 # Client 半：三页签（React，无 JSX 构建）
    ├── cordis.patch.yml
    └── icon.svg / locale/
```

运行时数据（`news.db`、`news_translations.json`、`plugin-news.json`、`news-read.json`、
`source-health.json`、`client-errors.log`、`backups/`、`proxy.json`）全部 gitignore，
仓库只存代码、配置与示例。

## 两种用法

### 1. 工作台插件（推荐日常使用）

DSH（DeepSeek Harness）中以本地 bundle 安装 `plugin/`（`package.json` 声明了
`dsh.bundle.patch` 与 `dsh.client`）。安装后侧栏出现「AI 资讯」面板，三个页签：

**资讯 tab**
- 分组 / 领域主题 / 关注词 / 时间范围（全部·今日·近 3 天·近 7 天）四维筛选
- 搜索框吸顶常驻，`Ctrl/⌘+K` 聚焦、`Esc` 清空；命中数实时显示
- 瀑布流 / 列表两种视图；卡片显示中文标题、来源、时间、形态/获取方式、领域标签
- 已读标记：单条点击即标记，`只看未读` / `全部已读`；近似重复显示「🔗 另有 N 家」
- 工具栏：`在线刷新`（真采集）、`自动翻译`（免费机翻）、`📰 周报`、`🌐 网络`（代理）、`🐞 日志`
- 右下角悬浮「回到顶部」，滚动后点亮

**发现 tab**
- 四条通道：网页种子发现 / 内置 OPML 目录 / 自定义 OPML / AIHOT 远程清单
- 候选源逐条显示条目数与最近更新，**逐条采纳 / 忽略**，也可「全部采纳」
- 采纳即写回 `feeds.json` 并启用；忽略只留记录，绝不静默改配置

**信源维护 tab**
- 增删 / 启停 RSS/Atom 信源，改动直接写回 `engine/data/sources/feeds.json`

**关注词管理**：资讯 tab 的「关注」筛选条右侧「管理 ⚙」，可增删/启停关注词，保存后立即离线重渲染生效。

插件通过 subprocess 调用引擎，引擎位置按顺序探测：环境变量 `AI_GIT_RADAR_DIR`
→ 同仓 `../engine`（本 monorepo 布局）→ 同级 `../ai-git-radar` → 宿主 cwd 兜底。

### 2. 命令行 / Skill

```bash
cd engine/scripts

# —— 主力：资讯采集 ——
python3 radar.py news                      # 并发采集，出 md+html+json 并套用中文翻译
python3 radar.py news --offline            # 只用 SQLite/缓存，离线出资讯（亚秒级）
python3 radar.py news --only 学术研究       # 按信源 id 或分组过滤
python3 radar.py news --days 14            # 面板快照窗口临时放宽到 14 天
python3 radar.py news --per-source 20      # 每源最多取多少条（默认 8）

# —— 翻译 ——
python3 radar.py translate --news --auto       # 免费机翻批量英译中，直接入库（无需 key）
python3 radar.py translate --news --todo       # 导出待译清单（人工精译用）
python3 radar.py translate --news --coverage   # 只看覆盖率
python3 radar.py translate --news --normalize  # 术语归一化历史机翻

# —— 周报与运维 ——
python3 radar.py weekly                    # 近 7 天周报 Markdown（关注专区 + 主题分区）
python3 radar.py source-check              # 信源体检：静默源 / 连续故障 / health 孤儿
python3 radar.py backup                    # 资产备份 → data/backups/*.zip
python3 radar.py backup --restore          # 从最新备份恢复
python3 radar.py doctor --sources          # 环境自检 + 信源体检

# —— 信源发现 ——
python3 radar.py discover                              # 扫 30 个种子站的 RSS 声明
python3 radar.py discover --opml-catalog tidings-ai    # 内置社区目录
python3 radar.py discover --remote                     # AIHOT 远程开源清单
python3 radar.py discover --list                       # 看待审队列
python3 radar.py discover --accept id1,id2             # 采纳 → 写回 feeds.json

python3 selftest.py                        # 离线回归（27 组 / 367 断言）
```

Python 3.8+，资讯采集与翻译纯标准库。GitHub 项目雷达（legacy）额外需要
`requests` + `pyyaml`。

## 数据流与存储

```
feeds.json ──fetch──> feed XML 缓存(3h) ──parse──> entries
                                                      │
                                    enrich（四维分类）+ watch（关注词）
                                                      │
                              cluster_duplicates（同语言近似去重）
                                                      │
                                        SQLite news.db（保留 30 天）
                                                      │
                           query_news(days=7) ──> plugin-news.json（面板快照 7 天）
                                                      │
                                             插件 /ai-news/news → 面板
```

**两个窗口是分开的**：DB 保留 30 天供周报、去重、跨天合并使用；面板快照只铺最近
7 天（`radar.py` 的 `PANEL_WINDOW_DAYS`，`news --days N` 可覆盖）。调大窗口立刻
可见历史，不需要重抓。

**去重规则**：只在同语言内比对（中英不互比），标题 Jaccard ≥ 0.62 且有效词元 ≥ 4
才折叠；组内按「源权威度 → 时间 → 标题长度」选主条，被折叠条目标 `dup_of`，
主条记录 `dup_count` / `dup_sources`。

## 信源维护

信源表是声明式 JSON（`engine/data/sources/feeds.json`），每条含
`id/name/url/kind(rss|atom)/group/tags/enabled`，停用源保留配置并可写 `disabled_reason`。
插件面板与手编 JSON 两种方式等价；新增源只需追加一条，`doctor` 自动纳入体检与重复 id 检查。

当前 **526 条配置 / 521 启用 / 5 停用 / 15 个分组**（厂商官方、科技媒体、技术博客、
开源生态、AI 媒体、个人与社区、学术研究、开发者社区、播客、DSH 生态、创业与商业、
安全、硬件与芯片、模型优惠与福利、其他）。其中「其他」400 条多为批量采纳的自动发现源，
未归组不影响采集，按需在面板里归位即可。

**不想手维护**就用自动发现：每个候选都**真实下载并解析一遍**（RSS 2.0 / Atom 都试），
记条目数与最近更新时间；下载失败判 `invalid` 不入队；URL 归一化去重；WordPress 评论
feed（`/comments/feed/`）自动剔除。发现结果全部落 `data/source-suggestions.json`
等人工决策，**绝不静默改写 feeds.json**。

**健康检查**：连续 3 次在线采集失败的信源自动停用并写明原因（`source-health.json`），
成功一次即重置；手动停用（`manual_disabled`）的源受保护。`source-check` 可离线查看
静默源与故障源。

## 中文翻译双通道

| 通道 | 触发 | 特点 |
|---|---|---|
| 免费机翻 | `translate --news --auto` 或面板「自动翻译」 | **零 API key**；主通道 Bing 网页端（并发 12 约 8.6 条/秒，token 过期自愈），失败降级腾讯 transmart → MyMemory；通道熔断 + 每页落盘 + 进度可见 |
| 人工精译 | `translate --news --todo` → 填表 → `--apply` | 按文章 link 建库，**机翻不覆盖精译**，跨天复用 |

**英文、日文、韩文以及其它非中文语种一律译成中文**。语种判定按「先假名/谚文、后汉字」
的顺序（`i18n.detect_lang`），因为汉字中日共用——只看「有没有汉字」会把日文标题
误判成「已是中文」而整条漏掉；纯数字/纯 emoji 不送翻译。卡片标题后的
`【英文】【日文】` 小标签标明原文语种。

落库前会走**术语归一化**（`glossary.py`）：agent→智能体、token→Token、prompt→提示词，
均带语境护栏（例如「代理人/代理服务」不会被改写，`prompt` 不会误伤「提示灯/提示框」），
且幂等——重复执行不会产生「提示词词」这类叠词。人工精译不动。

## 关键词关注与周报

`engine/data/sources/watch.json` 声明关注词（默认示例：mcp / agent / claude code / 免费额度）：

```json
{ "keywords": [ { "term": "mcp", "enabled": true } ] }
```

- 匹配范围：标题 + 摘要 + 中文译文；ASCII 词走**整词边界**（`agent` 不命中 `agents`），
  中文走子串
- 命中写入条目的 `watch_hits`，渲染层生效、不写回 DB，改配置即生效
- 面板「关注」筛选条可筛选，卡片显示橙色关注胶囊；「管理 ⚙」支持增删/启停

`weekly` 子命令从 DB 读近 N 天，按主题分组导出 Markdown：总览表 → 关注词命中专区 →
按主题分区（按条数倒序）→ 信源体检附榜。面板「📰 周报」按钮同源，可直接下载 `.md`。

## 扩展点

| 想加什么 | 改哪里 |
|---|---|
| 一个资讯信源 | `engine/data/sources/feeds.json` 追加一条 |
| 一个结构化采集器 | `scripts/collectors.py` 注册 type + `sources/collectors.json` 加配置 |
| 一个领域标签 | `scripts/enrich.py` 的 `_TOPIC_RULES` |
| 一个关注词 | 面板「管理 ⚙」或 `sources/watch.json` |
| 一个网页发现种子 | `sources/discover-seeds.json` |
| 一个 GitHub 项目类目（legacy） | `categories/*.yaml`，规则见 `engine/SKILL.md` |

## 设计要点

- **零 API 密钥**：RSS/Atom 直连 + 免费机翻，单源容错、失败回退缓存、自动处理强制 gzip
- **声明式优先**：信源、采集器、关注词、类目全是数据文件，加东西不改代码
- **人工决策边界**：自动发现只进待审队列，绝不静默改写配置
- **面板即真相源**：插件与 CLI 共用同一份 `feeds.json` 与同一个引擎，无第二套逻辑
- **零 JS 的 HTML 报告**：自包含单文件、内联 CSS，浏览器直接打开，适合存档/发群
- **离线可测**：27 组断言全部离线（含前端 Hook 顺序静态扫描），CI 与本地同源
- **错误可见**：前端错误边界 + 环形日志落盘 `client-errors.log`，渲染异常不再无声白屏

## 环境要求

- Python 3.8+（开发与 CI 覆盖 3.10 / 3.12），资讯通路纯标准库
- DSH（DeepSeek Harness）用于插件形态；CLI 形态不需要
- 可选：`requests` + `pyyaml`（仅 legacy GitHub 通路）

## Legacy：GitHub 项目雷达

早期的「GitHub 热门 AI 项目雷达」（四类目 + 六维情报评分 + 双报告）已**封存为 legacy，
代码保留可用**，`run` / `render` / `categories` 子命令仍可运行，与资讯通路零依赖。
说明见 `engine/NOTES-legacy.md`。

## 文档索引

- `engine/SKILL.md` —— Skill 执行契约、命令全集、扩展与检测口径
- `engine/README.md` —— 引擎模块详解、目录与数据流
- `engine/references/数据源与已知坑.md` —— 56 条踩坑记录（抓取改版、限额、分类误判、白屏排查等）
- `engine/references/评分方法论.md` —— legacy 六维评分口径
- `plugin/README.md` —— 插件架构与 HTTP 契约

## License

MIT
