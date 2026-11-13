# ai-news-radar

AI 资讯工作台：并发聚合一批零密钥 RSS/Atom AI 资讯信源，清洗、分组、套用中文翻译，
既可作为 **DSH 工作台插件**常驻侧边栏（资讯浏览 + 信源可视化维护），也可作为
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
│   │   ├── news_translations.json  # 资讯中文翻译库（按文章 link 建 key）
│   │   └── sample-*             # 示例产物（md/html/json/png）
│   └── references/          # 数据源与已知坑、评分方法论
└── plugin/                  # DSH 工作台插件（@local/ai-news-panel）
    ├── index.js             # Host 半：webServer 路由 + subprocess 调引擎
    ├── client.js            # Client 半：资讯面板 + 信源维护（React，无 JSX 构建）
    ├── cordis.patch.yml
    ├── icon.svg
    └── locale/
```

## 两种用法

### 1. 工作台插件（推荐日常使用）

DSH（DeepSeek Harness）中以本地 bundle 安装 `plugin/`（package.json 声明了
`dsh.bundle.patch` 与 `dsh.client`）。安装后侧栏出现「AI 资讯」面板：

- 资讯 tab：按分组浏览，中文标题优先，一键在线刷新
- 信源 tab：增删/启停 RSS/Atom 信源，改动直接写回 `engine/data/sources/feeds.json`

插件通过 subprocess 调用引擎，引擎位置按顺序探测：环境变量 `AI_GIT_RADAR_DIR`
→ 同仓 `../engine`（本 monorepo 布局）→ 同级 `../ai-git-radar` → cwd 兜底。

### 2. 命令行 / Skill

```bash
cd engine/scripts
python3 radar.py news                 # 并发采集（默认 8 路），出 md+html+json
python3 radar.py news --offline       # 只用本地缓存
python3 radar.py doctor               # 环境与信源体检
python3 radar.py translate --news --todo   # 导出英文标题待译清单
python3 radar.py selftest             # 离线回归（13 组断言）
```

Python 3.8+，资讯采集纯标准库；GitHub 项目雷达（legacy）额外需要 `requests` + `pyyaml`。

## 信源维护

信源表是声明式 JSON（`engine/data/sources/feeds.json`），每条含
`id/name/url/kind(rss|atom)/group/tags/enabled`，停用源保留配置并写 `disabled_reason`。
插件面板与手编 JSON 两种方式等价；新增源只需追加一条，`doctor` 自动纳入体检与重复 id 检查。

## 设计要点

- 零 API 密钥：RSS/Atom 直连，单源容错、失败回退缓存、自动处理强制 gzip
- 翻译流水线本地持久化，按文章链接建库、已译不覆盖，不依赖任何翻译服务
- GitHub 项目扫描（四类目 + 六维评分）已封存为 legacy，代码保留可用
- 插件 Client 半走同源 `fetch` + Host 半 `webServer` 路由，不使用动态沙箱 RPC

详见 `engine/SKILL.md`、`engine/references/数据源与已知坑.md`、`plugin/README.md`。

## License

MIT
