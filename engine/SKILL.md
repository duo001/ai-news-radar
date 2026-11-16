---
name: ai-git-radar
version: 0.17.0
description: AI 资讯雷达。主力能力是并发聚合零密钥 RSS/Atom AI 资讯信源（厂商官方/开源生态/学术研究/科技媒体/个人社区五组），产出带中文翻译的资讯速递（Markdown + 自包含单文件 HTML + JSON 三份），标题与摘要走翻译流水线（可免费机翻自动中文化，无需 API key），按文章链接建库、已译不覆盖，news 子命令 8 路并发约 20 秒采完全部信源。v0.8 新增信源自动发现：网页 RSS 声明扫描、OPML 批量导入（内置 7 个已核实社区目录）、远程开源清单同步（AIHOT），全部进入待审队列，验证通过才一键采纳，不会静默改写 feeds.json；连续 3 次采集失败的信源自动停用并记录原因。同一引擎被工作台插件 @local/ai-news-panel（../ai-news-panel）以 subprocess 复用，提供侧边栏常驻面板、信源可视化维护与「发现」页签，插件走 news --quiet --json-out 固定路径。GitHub 项目扫描能力已封存为 legacy（run 子命令仍可用）：四类目——① 热门 AI 工具（Agent/RAG/MCP/编程助手等应用层）② 免费与优惠 token 项目（免费额度、充值优惠/折扣、聚合网关、key 池/镜像、资源清单，含安全风险标记）③ 最近的 AI 技术（新协议/新范式的工程落地）④ Agent 生态 Skills/DSH，硬排除 AI 模型本体开发。类目用声明式 YAML、信源用声明式 JSON 注册，扩展不改代码。触发场景：AI 新闻/资讯/RSS 订阅、每日 AI 情报、AI 资讯翻译/中文摘要、找 RSS 信源/订阅源推荐/OPML 导入、AI 开源趋势、GitHub trending 分析、免费 API/免费 token/白嫖额度、AI 工具选型、Agent skills/DSH/Claude Code/MCP 生态。
---

# AI 资讯雷达（ai-git-radar）

## 它做什么

**v0.6 起主力是 RSS/Atom 资讯**：并发拉取一批零密钥 AI 资讯信源，清洗、分组、套用中文翻译，产出**可直接浏览器打开或转发的 HTML + Markdown + JSON 三份资讯速递**。相比封存的 GitHub 项目拉取（匿名受限流影响、单轮常需数分钟），资讯采集 8 路并发约 20 秒完成，零 API 额度。

GitHub 项目扫描能力**封存但保留可用**（`run` 子命令，下文标 legacy），需要时仍能跑四类目分类与六维评分。

**四个内置类目**（`categories/*.yaml`，声明式，可自行增删）：
1. `ai-tools` 热门 AI 工具——应用层：Agent、RAG、MCP、编程助手、生图音视频、工作流
2. `free-tokens` 免费与优惠 token 项目——免费额度 + 充值优惠/折扣/限时活动 + 聚合网关 + key 池/镜像 + 资源清单
3. `ai-tech` 最近 AI 技术——近 120 天新项目，新协议/新范式（MCP/A2A/computer use/多模态 agent 等）
4. `agent-skills` Agent 生态 · Skills / DSH——Agent 技能包、harness/运行时（DeepSeek Harness、Claude Code、Cursor）、规则与插件（严格 topic 模式，见下）

**明确不包括**：AI 模型本体开发。全局硬排除权重仓、训练/推理引擎、模型定义/训练框架（如 transformers）、纯论文复现（规则在 `categories/_global.yaml`，应用层框架如 dify/langflow/ollama 不在排除列）。

## 执行契约（Agent 按此操作）

所有命令在 `scripts/` 下执行，仅依赖 `requests` + `pyyaml`，Python 3.8+。

```bash
# ===== 主力：资讯采集与翻译（零 GitHub 额度）=====
python3 radar.py doctor                      # 环境自检：网络通路、信源/缓存、GitHub 类目
python3 radar.py news                        # ★ 并发拉取全部启用信源，出 md+html+json 三份并套用中文翻译
python3 radar.py news --per-source 5         # 每个信源取 5 条（默认 8）
python3 radar.py news --workers 4            # 并发数（默认 8，1 为串行；实测 14 源约 20 秒）
python3 radar.py news --only 学术研究         # 按 feeds.json 里的 id 或 group 过滤
python3 radar.py news --offline              # 只用 data/cache/feeds 缓存，不发网络请求
python3 radar.py news --out data/news.md     # 额外再写一份指定路径的资讯 Markdown

# ===== 信源自动发现（v0.8，全部进待审队列，采纳才写 feeds.json）=====
python3 radar.py discover                    # 通道1：扫 30 个种子站的 RSS 声明（link 标签 + 常见路径）
python3 radar.py discover --list             # 只看待审队列，不发网络请求
python3 radar.py discover --opml-catalog tidings-ai            # 通道2：内置社区目录（见下表）
python3 radar.py discover --opml-catalog tidings-ai,rsshub-routes  # 可逗号组合多个目录
python3 radar.py discover --opml https://…/xxx.opml            # 通道2b：任意 OPML（URL 或本地文件）
python3 radar.py discover --remote           # 通道3：同步远程开源清单（默认 AIHOT），也可传 URL
python3 radar.py discover --accept id1,id2   # 采纳指定条目，写回 feeds.json 并默认启用
python3 radar.py discover --accept-all       # 采纳全部待审
python3 radar.py discover --ignore id1       # 忽略，只改状态不写信源表

# 资讯中文翻译流水线（标题 + 摘要，按文章链接建库）
python3 radar.py translate --news --coverage # 看资讯标题翻译覆盖率（已译/待译/原文即中文）
python3 radar.py translate --news --todo     # 导出待译清单 data/todo_news_translate.json
#   Agent 逐条填 zh_title（必填）和 zh_summary（可选，空摘要可留空），然后：
python3 radar.py translate --news --apply    # 合并进 news_translations.json（已译不覆盖）并重渲染
python3 radar.py translate --news --auto     # ★ 免费机翻：批量英译中直接入库，无需人工填表
python3 radar.py translate --news --auto --limit 50   # 只翻 50 条（分批控量）
python3 radar.py news --translate            # 采集 + 机翻一条命令走完

# ===== 周报与关键词关注（v0.14）=====
python3 radar.py weekly                       # 近 7 天周报 → data/weekly-YYYYMMDD.md
python3 radar.py weekly --days 30 --per-topic 20   # 回溯 30 天、每主题最多 20 条
# 关键词配置在 data/sources/watch.json（改完即生效，无需重启；面板「关注」条与周报专区共用）

# ===== 信源体检（v0.15，纯本地不联网）=====
python3 radar.py source-check                 # 近 7 天静默源 + 连续故障源 + health 孤儿记录
python3 radar.py source-check --days 14       # 换静默窗口
python3 radar.py doctor --sources             # 环境自检后顺带跑体检

# ===== 代理、术语与资产备份（v0.17）=====
python3 radar.py backup                       # 打包翻译库/已读/关注词/DB → data/backups/*.zip
python3 radar.py backup --list               # 列出已有备份
python3 radar.py backup --restore            # 从最新备份恢复（可跟 zip 路径）
python3 radar.py translate --news --normalize # 用术语表归一化历史机翻（Agent/Token/Prompt）
# 代理在面板「🌐 网络」里配置，写 data/sources/proxy.json，无需命令行

# ===== 已封存 legacy：GitHub 项目扫描（代码保留可用）=====
# 说明见 NOTES-legacy.md：类目清单、代码构成、扩展方法与已知边界
python3 radar.py categories                  # 查看已注册 GitHub 类目与查询数
python3 radar.py run --quick                 # 只抓 trending，零搜索额度
python3 radar.py run                         # trending + Search 全量，默认深度分析前 50
python3 radar.py run --only free-tokens      # 只跑某类目
python3 radar.py run --offline               # 只用 data/cache，不发网络请求
python3 radar.py translate --todo            # 仓库简介翻译（不带 --news 的旧通道，按 owner/repo 建库）
python3 radar.py render                      # 用最新 GitHub run 数据+翻译库重渲染
```

### 资讯产物（主力，写到 `data/`）

每次 `news` 同时产出三份同一数据的文件：

- `news-时间戳.html`——**自包含单文件**（内联 CSS、零外部资源、零 JS），按 13 个分组分区、来源/日期/中文标题+原标题+中文摘要、失败信源标注、深浅色自适应，可直接双击打开或转发
- `news-时间戳.md`——Markdown 版，方便贴飞书/公众号/知识星球
- `news-时间戳.json`——结构化数据（`news`/`news_failures`/`news_translations`）
- 翻译资产 `data/news_translations.json`（按文章链接建 key，跨天复用，越用越全）；示例固化为 `data/sample-news.{md,html,json}`
- 信源配置 `data/sources/feeds.json`，feed 原始 XML 缓存 `data/cache/feeds/`（3 小时 TTL，离线回退）

### GitHub 产物（legacy）

`run` 仍产出 `report-时间戳.{html,md}` 与 `run-时间戳.json`（含 `news`/`news_failures`），仓库翻译在 `data/translations.json`，示例为 `data/sample-report.*`/`sample-run.json`。两份 GitHub 报告共用 `report.PRIORITY` 主归属规则，分类/排序/口径一致。

**长图导出（可选）**：`tools/screenshot.py` 调 `tools/lightpanda`（轻量无头浏览器单二进制，
无系统依赖）把 HTML 报告截成 1920 宽全页 PNG，默认截最新报告，`--port` 指定临时服务端口。
需要给用户图片产物或归档截图时用它；纯文本交付不需要。

### 通路与额度（重要）

- **无 token（默认）**：trending、仓库详情、README 走 github.com 网页 + raw.githubusercontent.com，**零额度**；Search API 匿名限 10 次/分钟，脚本自动每条间隔 8 秒（缓存命中不等待）。
- **有 token**：自动从 `GH_TOKEN/GITHUB_TOKEN/GITHUB_PAT` 环境变量 → `config.json` → gh CLI 配置发现，走 REST API，搜索 30 次/分钟，详情额度 5000/小时。
- **额度预检与整轮降级**：深度分析前查 `/rate_limit`，匿名 core 剩余不足（候选数+5）时整轮直接走网页/raw，不把时间浪费在注定 403 的 API 重试上；运行中撞限流立即降级（不 sleep 重试）。网页抓取同仓进程内只发一次请求。
- 所有网络结果缓存到 `data/cache/`（trending 3h、search 6h、repo/readme 24h），调试不重复请求。

### 候选截断与去重

- **分层配额截断**（`_stratified_select`）：每个类目先按搜索来源保底 `ceil(top/类目数)` 个名额，再按热度全局补齐。否则全局按星数取 top-N 会让老明星项目挤掉 `ai-tech` 的新项目（曾导致该 tab 为 0）。
- **主类目归属**：一个项目只进一个 tab，优先级 `free-tokens > agent-skills > ai-tech > ai-tools`（免费/优惠最稀缺，其次生态资产）；多类目命中在卡片注明"同时涉及"，信息不丢但不重复占榜。该优先级是 `report.py` 的模块常量 `PRIORITY`，Markdown 与 HTML 共用。
- **星数真值保护**：网页兜底的星数选择器可能失效给 0，合并详情时空值/0 不允许覆盖 search/trending 的真值，防止高星项目被"星数<30"误淘汰。
- **条数控制**：`--top N` 默认 50（早期 35），分层配额保证每个类目都有名额；想更多直接调大，配 token 走 API 时成本主要是时间，匿名网页通路下每仓约 20 秒。

### 中文翻译流水线（v0.3 新增）

脚本本身不调翻译 API（不引入额外密钥），翻译由 Agent/人完成，本地翻译库持久化：

1. `run` 后 `translate --todo`：把英文简介抽成 `data/todo_translate.json`，原文即中文、空简介自动跳过
2. Agent 逐条填 `zh` 字段（可只填一部分，空译不阻塞）
3. `translate --apply`：合并进 `data/translations.json`，**已存在的精译永不覆盖**，并自动重渲染报告
4. 报告卡片变为「中文简介 + 缩进英文原文」；报告头显示翻译覆盖率
5. 翻译库按 `owner/repo` 小写做 key，跨天复用，越用越全；`render` 可在不重新抓取时刷新报告

### AI 资讯信源与翻译（v0.6 主力，`scripts/feeds.py` + `i18n.py`）

参考 AIHOT 的信源清单，只接**零密钥**的 RSS 2.0 / Atom，不做需要付费 key 的 X 搜索、公众号、网页选择器等类型。配置在 `data/sources/feeds.json`（纯数据，不改代码即可加源）：

- 每条信源字段：`id/name/url/kind(rss|atom)/group/tags/enabled`，停用源保留配置并写 `disabled_reason`
- **13 个分组**（按内容属性归类，不再是笼统的「其他」）：厂商官方(15)、科技媒体(16)、技术博客(29，框架/公司工程博客，非 AI 垂直)、开源生态(13)、AI 媒体(12，机器之心/量子位/新智元/我爱计算机视觉/听说了吗等)、个人与社区(12)、学术研究(10)、开发者社区(10)、播客(6)、DSH 生态(2)、创业与商业(2)、安全(2)、硬件与芯片(2)。当前 **131 源 / 125 启用 / 6 停用**（Import AI、Google Research、Mistral、HuggingFace 本网络超时；BBC Technology、Gizmodo 连续失败被健康检查自动停用，恢复后把 `enabled` 改回 true 即可）
- **加一个源**：在 `sources` 数组追加一条，`kind` 按 feed 类型填 rss 或 atom，`doctor` 会自动纳入体检和重复 id 检查
- 采集特性：纯标准库（urllib + xml.etree + ThreadPoolExecutor）零新依赖；**默认 8 路并发**（`--workers 1` 退回串行），单源容错（一个挂只记进 `news_failures` 不影响其他），网络失败自动回退 `data/cache/feeds/` 缓存（过期也用，保证离线出报告）；自动处理强制 gzip 压缩（见 references 第 18 条）；每源默认取前 8 条，全部按时间倒序
- **摘要清洗**：先整块移除 `<style>/<script>` 与 HTML/CSS 注释，再去标签（实测 GitHub Blog 的字体版权、MS Research 的 `.yt-consent` 样式会在去标签后变成文本噪声，见 references 第 20 条）；正文中合法的 `{...}` 代码片段不误伤
- **资讯翻译流水线**（独立于仓库翻译，按文章 `link` 建 key，存 `data/news_translations.json`）：`translate --news --todo` 只抽英文标题（原文即中文自动跳过）→ Agent 填 `zh_title`/`zh_summary` → `--news --apply` 合并（已存在永不覆盖）并重渲染；报告显示中文标题+缩进原标题+中文摘要，报告头显示覆盖率
- **免费机翻通道（v0.10，`scripts/mt.py`）**：`translate --news --auto` 自动英译中，**无需 API key、无需付费**。主通道腾讯交互翻译（`transmart.qq.com/api/imt`，国内直连、批量、质量可用），失败降级 MyMemory 公共额度；实测 491 条 / 956 段文本 2.5 分钟全译完。要点：① 双预算切片——单批 ≤40 条且 ≤4000 字符（实测 6000 字符通过、12000 报 `outOfLimit`），批间 sleep 1s ② `outOfLimit` 是限流，退避 8s 再试，其他错误 1.5s×n ③ 译文入库带 `source: auto:transmart` 与 `translated_at`，人工精译（无该字段）永不被覆盖 ④ 单条失败只跳过该条，不污染其余 ⑤ 翻译后自动同步 `data/plugin-news.json`，面板刷新即见中文（`_rerender_news` 里的同步逻辑）
- **完整中文化现状**：当前 707 条资讯中 545 条英文标题 + 162 条原文即中文，机翻后覆盖率 100%

### 信源自动发现（v0.8，`scripts/discover.py`）

手维护信源表累人，四条通道把候选源喂进**待审队列**，验证通过后一键采纳（**不静默自动加**，避免脏源污染报告）：

| 通道 | 命令 | 机制 |
|---|---|---|
| 网页发现 | `discover` | 逐个抓 30 个种子站（`data/sources/discover-seeds.json`，只存首页），先解析 `<link rel=alternate type=application/rss+xml>`，没有则探测 `/feed`、`/rss.xml`、`/atom.xml` 等常见路径 |
| 社区目录 | `--opml-catalog <别名>` | 内置 7 个已核实目录（`data/sources/opml-catalog.json`）：`tidings-ai`(99源)、`tidings-chinese`、`tidings-tech-media`、`tidings-research`、`tidings-top200`、`rsshub-routes`(105条)、`awesome-tech`(28源) |
| 任意 OPML | `--opml <URL或文件>` | 正则提 `xmlUrl` + `title`，大小写/尾斜杠归一化去重 |
| 远程清单 | `--remote [URL]` | 拉 AIHOT 格式的 `sources[]`，只取 `kind=rss/atom` 的零密钥源 |

- **每个候选都真验证**：实际下载并 `feeds.parse_feed`，记 `item_count` / `latest_item_at` / feed 标题；下载即失败的判 `invalid` 不入队。所以一次网页发现要几十秒到几分钟（每站至少一次网络往返）
- **四态去重**：`added` 新入队 / `duplicate` 已在队列 / `exists` 已在信源表 / `invalid` 验证失败；URL 归一化（小写 host、去尾斜杠、去 fragment）避免同一个 feed 换写法混进来
- **评论 feed 自动剔除**：`/comments/feed/`、`/replies`、`comment-page` 这类 WordPress 噪音不进队列（实测 The Decoder 首页会暴露一个）
- 队列文件 `data/source-suggestions.json`：`{generated_at, suggestions:[{id,name,url,kind,group,tags,found_via,status,item_count,latest_item_at,…}]}`，`status` 为 `pending|accepted|ignored`，采纳/忽略都留 `decided_at` 便于回溯
- **健康检查自动停用**（`feeds.record_health`，只在**在线**采集时统计，离线失败不判失效）：连续 3 次失败把 `feeds.json` 里该源 `enabled=false` 并写 `disabled_reason`（含最近错误），成功一次即清零计数；带 `manual_disabled` 的手动停用源受保护，不会被自动逻辑改写

### 结构化采集器与正交分类（v0.11，`scripts/collectors.py` + `scripts/enrich.py`）

RSS/Atom 之外，借鉴 freebie-radar 的多类型采集器思路，接入**零 key、公开 JSON API** 的结构化信源，配置在 `data/sources/collectors.json`（与 feeds.json 同构的声明式注册，加源不改代码）：

- **已启用 2 路**（当前网络实测可达）：① `openrouter-free-models`——拉 `openrouter.ai/api/v1/models`，按 `:free` 后缀或 pricing 全 0 识别免费模型，只留近 14 天新增，产出「OpenRouter 新免费模型」福利条目 ② `hackernews-ai`——多关键词打 `hn.algolia.com` 搜索 API，objectID 去重 + 标题 AI 正则二次过滤，摘要带 HN 分数/评论数
- **预置停用 4 路**（`enabled:false` + `disabled_reason`，网络具备后改 true 并在 `_COLLECTOR_FUNCS` 注册处理函数即可）：bluesky（public.api.bsky.app）、v2ex、linux.do（Discourse JSON）、reddit；停用原因均为本环境连接超时
- 采集器与 feeds 输出**完全同构**的 entry（title/link/summary/published/source_id/source_name/group/kind），同一套缓存（`data/cache/collectors/`，TTL 3h，原子写）、同一套单源容错与离线回退、同一张 SQLite 表，按 link 去重合并
- **enrich.py 规则版正交分类**（零 AI 调用、渲染层可对历史数据重算）：每条资讯补四个字段——`form`（freebie 福利/deal 优惠/paper 论文/release 发布/tutorial 教程/opensource 开源/news 资讯，按精确度排序的正则规则）、`obtain`（仅福利/优惠有值：lottery 抽奖 > promo 推广 > trial 试用 > conditional 有条件 > paid 付费，兜底 free 直接领）、`topics`（**v0.12 起 29 个中文标签、每条最多 5 个，不再局限 AI**：15 个 AI/工程标签——模型/Agent/MCP/RAG/推理部署/多模态/训练微调/工具框架/评测榜单/编程开发/安全/云计算与基础设施/数据/硬件算力/开源；14 个通用领域——时政要闻/国际资讯/政策合规/商业融资/金融财经/消费电子/汽车出行/游戏/影音媒体/设计创意/产品与增长/职场商业/教育学习/生活方式。短英文词（ev/vr/ar/nft/ui/ux/ps5 等）统一加词边界，避免 ever 误命中 ev、regular 误命中 vr。时政/国际用「标题强信号 + 摘要需与标题共同佐证」的三元组规则，防止摘要里的 government/worldwide 泛词误判；模型词 deepseek 在 URL/产品名（r/deepseek、deepseek-ai、DeepSeek Harness）中排除）、`codes`（邀请码/兑换码，支持显式标注、4-4-4 分段、10-40 位长串，排除纯数字与常见英文词）。插件面板有独立的「主题」筛选条，卡片上的标签可点击直接筛选
- **翻译数据源选择（v0.12 修复）**：`translate --news --auto` 不再只看最新 `news-*.json`，改为 `_news_payload_for_translate()` 自动选条目最全的一份（优先插件固定文件 `plugin-news.json`，回退 news-*.json / sample）。否则插件日常只写 plugin-news.json、不产 news-*.json 时，最新 news 文件会停在很久以前，机翻永远「处理 0 条」而面板上仍有大量英文
- 插件卡片：form 六色徽章、obtain 获取方式、topics 彩色胶囊、codes 黄色胶囊一键复制；deals.json 的手工情报也补齐同构四字段，并按 link 与采集结果去重（合并函数 `mergeDeals`）
- **论坛类信源去噪（v0.13）**：论坛的「最新话题」RSS 混着二手交易、资费问询、求职闲聊帖，这类既不是资讯也归不进领域。`feeds.json` 里给源加 `"noise_filter": "forum"` 即启用（默认不启用，避免误伤正常资讯里含「出/收」的标题）；`enrich.noise_reason()` 按四类规则判定——交易帖（出售/转让/已出/「出V0 MAX」式开头）、求助问询帖（请教/老哥们/是不是…转好）、资费问询（实名了吗/转套餐）、闲聊帖（找工作/面试/吐槽）。**福利帖豁免**：命中「免费/领取/抽奖/迎新福利/送激活码」等白给信号时保留，`enrich.drop_noise()` 批量二分。目前 `forum-naixi-net-forum-php`（奶昔论坛）已标记，实测 20 条抓取→过滤 6 条，保留的都是免费 eSIM / 迎新福利 / 会员领取这类有价值的帖
- **摘要补译（v0.13）**：翻译库按「标题必译、摘要可选」设计，早期实现里只要条目进了库就整体跳过，导致「标题已译、摘要空缺」的条目永远补不上。现在 `build_news_todo` 对这类条目产出 `only_summary` 任务，`auto_translate_news` 只送摘要文本、写入时保留原译文并另记 `summary_source`/`summary_translated_at`
- **关键词关注（v0.14，`scripts/watch.py` + `data/sources/watch.json`）**：声明式配置 `{"keywords":[{"term":"mcp","enabled":true}]}`，改配置即时生效、零代码。纯 ASCII 词按整词匹配（`mcp` 不命中 `scmcp`，但也不匹配复数 `agents`，配词时注意单复数），中文走大小写不敏感子串。匹配范围是标题 + 摘要 + 中文译文（按 link 关联翻译库），命中条目带 `watch_hits` 列表，**纯渲染层计算、不入库**，历史数据可重算。面板有橙色「关注」筛选条（🔖 带计数），卡片上的命中词胶囊可点击直接筛选；配置缺失/损坏时功能静默关闭
- **周报导出（v0.14，`radar.py weekly`）**：从 SQLite 读近 N 天（默认 7）资讯，套用 enrich + watch 后生成 Markdown 周报——总览表（条数/信源/关注命中/形态分布）、关注词命中专区、按 29 个主题分区（每主题默认 10 条，可 `--per-topic` 调）、未归类兜底。参数 `--days/--per-topic/--limit/--out/--print-md`，默认产物 `data/weekly-YYYYMMDD.md`。插件工具栏「📰 周报」按钮走 `POST /ai-news/weekly`，弹窗内轻量 Markdown 渲染并支持下载 .md
- **跨源近似去重（v0.15，`enrich.cluster_duplicates`）**：同语言标题词元 Jaccard ≥ 0.62 且有效词 ≥ 4 时聚类，同事件多源只保留主条目（来源组优先级：厂商官方 > 学术 > 媒体 > 社区，其次时间新、标题长），被折叠条目标 `dup_of`、主条目录 `dup_count/dup_sources`，面板显示「🔗 另有 N 家」。纯渲染层不入库，跨语言不合并（有意取舍，见坑 41）
- **无标签补全（v0.15）**：新增「AI 综合」标签收编 AI 泛讨论（AI 时代/热潮/机器学习），并给强领域信源组（厂商官方/学术/AI 媒体/安全/硬件等）配分组兜底标签，开发者社区等杂烩组不兜底；无标签率从 29.8% 降到 11.0%，剩下的多为版本号、日文短标题与确实跨领域的社区帖
- **关注词面板管理（v0.15）**：`watch.py` 增 `add_keyword/remove_keyword/toggle_keyword/load_raw`（原子写、同名忽略大小写、64 字符上限），插件新增 `GET/POST /ai-news/watch`（op: add/remove/toggle），写入后自动离线重渲染让命中立即生效；面板「关注」条右侧「管理 ⚙」可直接增删启停，无需手改 JSON
- **信源体检（v0.15，`scripts/sourcecheck.py` + `radar.py source-check`）**：纯本地分析三项——近 N 天 0 条的静默源（"最近条目"取 30 天全量、静默判定看短窗口）、`source-health.json` 连续失败 ≥2 的故障源、配置已删但 health 残留的孤儿记录；只报告不自动停用（低频博客静默是正常的），周报末尾自动附静默/故障榜
- **代理出口（v0.17，`scripts/netcfg.py`）**：面板工具栏「🌐 网络」填入代理地址即可让全部外网请求走代理——RSS/Atom 采集、结构化采集器（OpenRouter/HN）、信源发现、腾讯 transmart 机翻共用同一个出口 `netcfg.open_url()`。配置存 `data/sources/proxy.json`（`{enabled,url,no_proxy}`，不入库），只支持 http/https（标准库无 socks 支持，保存时明确拒绝 socks 并提示）；`no_proxy` 逗号分隔白名单内主机直连；面板「测试连通」复用引擎同一套 `netcfg.test_proxy`（拉 `api.github.com/zen`），避免 Node 与 Python 两套代理行为不一致出现"测通了但采集不走"
- **术语归一化（v0.17，`scripts/glossary.py`）**：transmart 机翻把 Agent 译成「代理」、Token 译成「令牌/代币/标记」、Prompt 译成「提示」，与行业习惯不符。术语表在后处理阶段统一：代理→智能体、token→Token（仅 LLM 语境）、prompt→提示词。每条规则都带原文语境护栏（原文须含 agent/token/prompt 词根）与组合词护栏（代理服务器/代理人/代理商不替换），且**只改 `source=auto:*` 的机翻条目，人工精译一字不动**。新翻译在 `auto_translate_news` 落库前即时归一化，历史数据用 `translate --news --normalize` 回填（幂等，重复跑不改动）
- **资产备份（v0.17，`scripts/backup.py` + `radar.py backup`）**：翻译库、已读状态、关注词、源体检与发现结果、news.db 都在 .gitignore 里，误删即不可再生。`backup` 打成 `data/backups/backup-YYYYMMDD-HHMMSS.zip`（内含 `backup-manifest.json` 记录纳管/缺失清单），`--restore` 按原路径原子写回并做 zip-slip 路径校验；cache 与时间戳报告不纳入（可重抓/可重渲染）

### 工作台形态：@local/ai-news-panel 插件

同仓兄弟目录 `../ai-news-panel` 是 DSH 工作台插件，把本引擎包成侧边栏常驻面板（**资讯浏览 / 发现 / 信源维护** 三个页签，含一键在线刷新），引擎代码零改动：
- Host 半 `webServer` 注册 `/ai-news/*` 路由，用 subprocess 调 `python3 radar.py news --quiet --json-out data/plugin-news.json`；信源维护直接 fs 读写本仓 `data/sources/feeds.json`，与命令行共享同一份
- v0.8 新增路由：`GET /suggestions`（待审队列）、`GET /opml-catalog`（可选目录）、`POST /discover`（`mode=web|opml|catalog|remote` + `target`，内部拼 `radar.py discover` 参数）、`POST /suggestions`（`op=accept|ignore|accept-all` + `ids[]`）
- v0.13 新增路由：`POST /read`（`{links:[url…], read:true|false}`，标记已读/未读）、`POST /read-all`（`{}`，当前列表全部已读）。已读状态存在引擎目录的 `data/news-read.json`（`{updated_at, read:{link:iso}}`，**JS 侧单一真源**，不写入 SQLite——deals 条目不在 news 表里也能标记，且免去库结构迁移）；`GET /news` 返回的每条带 `read` 布尔。前端用「本地覆盖层 + 服务端初值」做乐观更新：点击卡片立即变半透明并后台 POST，失败不回滚（下次刷新以服务端为准）；工具栏有「只看未读 N」「全部已读」
- `--quiet` 是 news 子命令专为插件加的开关：不打印摘要/逐源日志、不写时间戳三件套，只出 `--json-out` 的固定 JSON
- Client 半用全局 `fetch` 同源调路由（持久化 ESM bundle 可用 fetch；动态沙箱插件的 `host.call` 此路不通，详见 references 第 22 条）
- 引擎位置探测：环境变量 `AI_GIT_RADAR_DIR` → 同仓 `../engine`（v0.13 起默认命中此条，**本仓库是唯一真源**）→ 历史布局 `../ai-git-radar` → cwd 兄弟目录兜底；插件 entryId 为 `include:ai-news-panel`，profile 里以 `link:` 软链到本仓 `plugin/`，改代码后只需 set_plugin 重载、不再 rsync
- v0.13 起运行时数据（`news.db`/`news_translations.json`/`plugin-news.json`/`news-read.json`/`source-health.json`/`cache/`）全部 gitignore，只留在本机 `engine/data/`；入库的只有 `sample-*` 示例、`sources/*.json` 配置、`deals.json`、`translations.json`。本地布局与回退步骤见仓库根 `NOTES.local.md`（不入库）

## 怎么扩展（核心设计）

**加一个类目 = 在 `categories/` 新建一个 yaml**，脚本启动自动发现，报告自动多一个分区，无需改代码。字段见现有四个类目文件，关键项：

- `topics` / `name_keywords`：GitHub 粗捞信号（topic 不支持 OR，每个单独查询）
- `core_keywords`：本地二次校验，支持 `{strong:[...], weak:[...]}` 两级——身份强词（ai/llm/agent/gpt/大模型…）命中即准入；协议强词（mcp/rag/a2a/multimodal…）需另有 AI 身份词佐证（非 AI 应用也可能接一个 MCP 接口，见 references 第 14 条）；弱词需两个。纯 ASCII 短词自动加词边界（`ai` 不会误命中 `main`）
- `readme_signals`：正则数组，配置后该类目改为"必须命中 README 信号"（免费/优惠类用这个）
- `keep_lists: true`：保留 awesome/清单类（默认全局排除清单，但 token 资源清单有高价值）
- `max_age_days`：限制项目年龄（技术趋势类用）
- `strict_topic_match: true`：严格 topic 模式——单个类目 topic + 泛 AI 身份词不再准入，必须命中 ≥2 个生态 topic 或本类目专属强词（生态类用这个，防止通用工具挂一个 `claude-code` 标签就混入）
- 全局排除规则集中在 `categories/_global.yaml`

**两个匹配通道严格分开**（v0.4 修复，曾导致 dify/JavaGuide 误进生态类）：强/弱关键词只在 **name/desc 文本**里匹配；topic 只走独立的 topic 交集通道。一个叫 `skills` 的 topic 不会再冒充 `skill` 关键词。新增类目时不要把通用标签（`mcp`/`ai-agent`/`mcp-server`）放进生态专属类目的 `topics`——非生态项目也会挂，放进来会稀释精度。

## 免费/优惠类目的检测口径

`scripts/detectors.py` 纯静态文本分析（不调用任何第三方 API、不要用户 key）：

- **免费额度**：正则抽 "多少 token/credit/次数 + 周期"，如 `20K tokens/day`、`1000万 Tokens`、`$5 free credits`
- **优惠活动**：折扣/促销码、优惠券、%off、加赠额度、返现、首充赠送、黑五/周年庆/双11 节点大促、限时活动、学生优惠；无 token/API 语境的优惠（如 VPN 折扣）自动排除
- **注册门槛**：信用卡（否定式优先，"no credit card required" 不会误判为需要）、手机验证、候补邀请、学生包、GitHub 登录
- **国内可用性**：国内厂商名/直连信号 vs 需代理声明
- **安全风险**：要求把官方 key 填入第三方服务（高，两种中文语序都覆盖）、非官方域名代理官方 API（中）、风险自负声明（低）；高风险项目评分强制不超过 B 级
- 报告所有额度信息带"信息截至日期"，提示以官方页面为准

## 评分（满分 100，六维）

热度与增速 25 / 项目健康度 20 / 技术前沿度 15 / 可上手性 15 / 国内与中文 15 / 风险与合规 10，映射 S/A/B/C。明细随卡片输出，分数可解释。硬淘汰（归档、fork、星数门槛、模型本体）在分类层先做。

## 已知边界

- **GitHub 项目扫描（run）已封存为 legacy**：匿名通路受 Search 10 次/分钟、core 60 次/小时限流，全量较慢；代码与文档完整保留，需要项目分类/评分时仍可运行。日常情报用 `news`
- 资讯只接零密钥 RSS/Atom；需要 key 的信源类型（X 搜索、公众号、网页选择器等）不做；个别源超时标进失败列表而非中断
- 资讯/仓库翻译支持两种方式：Agent/人工精译（进待译清单，已译内容跨天复用、永不被覆盖）与 v0.10 免费机翻（腾讯 transmart，零 key，见上）；新文章英文标题首次出现时可一键自动中文化
- 免费/优惠类只做 README 静态分析，不实测 API 可用性/额度真实性；优惠有时效，报告已显式提示
- HTML 报告无 JS、纯内联 CSS，交互只有锚点导航和 `<details>` 折叠；自动适配系统深浅色
- 无跨天查重、无定时任务（后续版本按需补）
- 抓层依赖各 feed 的 XML 格式与（legacy）GitHub 页面结构；feed 解析异常会记 FeedError，trending 解析若返回 0 条通常是改版，见 `references/数据源与已知坑.md`
