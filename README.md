# ai-news-radar

AI 资讯工作台：并发聚合一批零密钥 RSS/Atom AI 资讯信源，清洗、分组、套用中文翻译，
既可作为 **DSH 工作台插件**常驻侧边栏（资讯浏览 + 信源自动发现 + 可视化维护），也可作为
**Agent Skill / 命令行工具**独立运行。

## 仓库结构（monorepo）

```
ai-news-radar/
├── engine/                  # Python 引擎（同时是一个 DSH Skill，零第三方网络依赖）
│   ├── SKILL.md             # Skill 执行契约
│   ├── scripts/             # radar.py 入口 + feeds/gh_client/classify/scorer/i18n ...
│   ├── categories/          # GitHub 项目雷达的声明式类目（legacy，YAML 扩展）
│   ├── data/
│   │   ├── sources/feeds.json   # ★ 资讯信源表（插件与 CLI 共享，加源改这里）
│   │   ├── sources/discover-seeds.json  # 网页发现的种子站（30 个首页）
│   │   ├── sources/opml-catalog.json    # 内置 OPML 社区目录（7 个别名）
│   │   ├── source-suggestions.json      # 待审队列（发现结果，采纳后才写 feeds.json）
│   │   ├── source-health.json           # 信源健康记录（连续失败计数）
│   │   ├── news_translations.json  # 资讯中文翻译库（按文章 link 建 key）
│   │   └── sample-*             # 示例产物（md/html/json/png）
│   └── references/          # 数据源与已知坑、评分方法论
└── plugin/                  # DSH 工作台插件（@local/ai-news-panel）
    ├── index.js             # Host 半：webServer 路由 + subprocess 调引擎
    ├── client.js            # Client 半：资讯 / 发现 / 信源维护三页签（React，无 JSX 构建）
    ├── cordis.patch.yml
    ├── icon.svg
    └── locale/
```

## 两种用法

### 1. 工作台插件（推荐日常使用）

DSH（DeepSeek Harness）中以本地 bundle 安装 `plugin/`（package.json 声明了
`dsh.bundle.patch` 与 `dsh.client`）。安装后侧栏出现「AI 资讯」面板：

- 资讯 tab：按分组浏览，中文标题优先，一键在线刷新
- 资讯 tab 顶部：「在线刷新」采集、「自动翻译」把英文标题/摘要走免费机翻通道翻成中文
- 发现 tab：四条通道（网页种子发现 / 内置 OPML 目录 / 自定义 OPML / AIHOT 远程清单）把候选源
  喂进待审队列，每张卡片显示条目数与最近更新，**逐条「采纳 / 忽略」**，也可「全部采纳」；
  采纳即写回 `feeds.json` 并启用，忽略只留记录
- 信源 tab：增删/启停 RSS/Atom 信源，改动直接写回 `engine/data/sources/feeds.json`

插件通过 subprocess 调用引擎，引擎位置按顺序探测：环境变量 `AI_GIT_RADAR_DIR`
→ 同仓 `../engine`（本 monorepo 布局）→ 同级 `../ai-git-radar` → cwd 兜底。

### 2. 命令行 / Skill

```bash
cd engine/scripts
python3 radar.py news                 # 并发采集（默认 8 路），出 md+html+json
python3 radar.py news --offline       # 只用本地缓存
python3 radar.py doctor               # 环境与信源体检
python3 radar.py translate --news --auto   # ★ 免费机翻：批量英译中直接入库（无需 API key）
python3 radar.py translate --news --todo   # 导出英文标题待译清单（人工精译用）
python3 radar.py news --translate          # 采集 + 机翻一条命令走完
python3 radar.py discover             # 网页自动发现：扫 30 个种子站的 RSS 声明
python3 radar.py discover --opml-catalog tidings-ai   # 导入社区 OPML 目录（99 源）
python3 radar.py discover --remote    # 同步 AIHOT 远程开源清单
python3 radar.py discover --list      # 查看待审队列
python3 radar.py discover --accept-all  # 采纳全部（验证通过的才写 feeds.json）
python3 radar.py selftest             # 离线回归（16 组断言）
```

Python 3.8+，资讯采集纯标准库；GitHub 项目雷达（legacy）额外需要 `requests` + `pyyaml`。

## 信源维护

信源表是声明式 JSON（`engine/data/sources/feeds.json`），每条含
`id/name/url/kind(rss|atom)/group/tags/enabled`，停用源保留配置并写 `disabled_reason`。
插件面板与手编 JSON 两种方式等价；新增源只需追加一条，`doctor` 自动纳入体检与重复 id 检查。

**不想手维护**就用自动发现（`discover` 子命令或面板「发现」页签）：

```bash
python3 radar.py discover                              # 扫 30 个种子站的 RSS 声明
python3 radar.py discover --opml-catalog tidings-ai   # 内置社区目录：tidings-{ai,chinese,tech-media,research,top200}
python3 radar.py discover --opml <URL或文件>          # 任意 OPML 订阅清单
python3 radar.py discover --remote                    # AIHOT 远程开源清单
python3 radar.py discover --list                      # 看队列（pending/accepted/ignored）
python3 radar.py discover --accept id1,id2            # 采纳 → 写回 feeds.json 并启用
```

设计要点：**每个候选都真实下载并解析一遍**（RSS 2.0 / Atom 都试），记条目数与最近更新时间；
下载失败判 `invalid` 不入队；URL 归一化（小写 host、去尾斜杠）去重；WordPress 评论 feed
（`/comments/feed/`）自动剔除。发现结果全部落 `data/source-suggestions.json` 等人工决策，
**绝不静默改写 feeds.json**。连续 3 次在线采集失败的信源会自动停用并写明原因（`source-health.json`），
成功一次即重置；手动停用（`manual_disabled`）的源受保护。

## 设计要点

- 零 API 密钥：RSS/Atom 直连，单源容错、失败回退缓存、自动处理强制 gzip
- 信源自动发现四通道 + 待审队列人工决策，健康检查自动停用失效源
- 翻译双通道：**免费机翻**（腾讯交互翻译，无需 key，失败降级 MyMemory）+ 人工精译，
  按文章链接建库、机翻不覆盖精译；面板有「自动翻译」按钮
- GitHub 项目扫描（四类目 + 六维评分）已封存为 legacy，代码保留可用
- 插件 Client 半走同源 `fetch` + Host 半 `webServer` 路由，不使用动态沙箱 RPC

详见 `engine/SKILL.md`、`engine/references/数据源与已知坑.md`、`plugin/README.md`。

## License

MIT
