# @local/ai-news-panel — AI 资讯工作台插件

把 `ai-git-radar` 的 RSS/Atom 资讯能力做成 DSH 工作台常驻面板：侧边栏点开即看，
信源在面板里可视化增删/启停，不需要手编 JSON、不需要跑命令。

## 架构：插件是外壳，Python 是引擎

```
┌───────────────────────────── Web GUI（浏览器）────────────────────────────┐
│ client.js（Client 半，React 无 JSX）                                        │
│  · sidebar.panellist 图标（id=ai-news, order=15）                          │
│  · main 面板（key=ai-news）：资讯 tab + 信源维护 tab                        │
│  · 全局 fetch('/ai-news/*') 同源调用                                        │
└──────────────────────────────┬────────────────────────────────────────────┘
                               │ HTTP（同源，webServer 路由）
┌──────────────────────────────▼────────────── Host（Node）──────────────────┐
│ index.js（Host 半，ESM）                                                    │
│  · webServer.register prefix /ai-news                                       │
│  · subprocess.spawn → python3 radar.py news --quiet --json-out             │
│  · fs 读写引擎目录的 data/sources/feeds.json                                │
└──────────────────────────────┬────────────────────────────────────────────┘
                               │ subprocess
┌──────────────────────────────▼──────────── Python（零改动复用）────────────┐
│ ../ai-git-radar/scripts/radar.py + feeds.py + i18n.py ...                  │
│  data/sources/feeds.json（18 源）、data/cache/feeds/、news_translations.json│
└────────────────────────────────────────────────────────────────────────────┘
```

插件不重写任何采集/解析/翻译逻辑，只负责「常驻面板 + 可视化维护 + 进程编排」。

## HTTP 契约（/ai-news 前缀）

| 方法 | 路由 | 作用 |
|---|---|---|
| GET | `/status` | 引擎路径与在位自检 |
| GET | `/news` | 读 `plugin-news.json`；不存在时先离线跑一次；`?refresh=1` 在线采集，`&perSource=N&only=id` |
| GET | `/sources` | 读 feeds.json 全量信源 |
| POST | `/sources` | 信源维护，body `{op, ...}`：`add`/`update`/`toggle`/`remove` |
| GET | `/news/progress` | 采集进度（`stage/done/total/current`），前端每秒轮询 |
| GET | `/suggestions` | 待审信源队列（自动发现的候选） |
| GET | `/opml-catalog` | 内置 OPML 目录别名表 |
| POST | `/discover` | 触发发现，body `{mode:'web'\|'opml'\|'catalog'\|'remote', target}` |
| POST | `/suggestions` | 采纳/忽略，body `{op:'accept'\|'ignore'\|'accept-all', ids[]}` |
| POST | `/translate` | 免费机翻，body `{limit?}`；翻完回写 `plugin-news.json` 并返回最新列表 |
| POST | `/read` | 标记已读，body `{links:[url…], read:true\|false}`；状态存 `data/news-read.json` |
| POST | `/read-all` | 当前列表全部已读，body `{}` |
| POST | `/weekly` | 生成周报，body `{days?,perTopic?,limit?}`；跑 `radar.py weekly` 并返回 `{path, markdown}` |
| GET | `/watch` | 读关注词全量配置（含停用），返回 `{keywords:[{term,enabled}]}` |
| POST | `/watch` | 关注词管理，body `{op:'add'\|'remove'\|'toggle', term, enabled?}`；写入后自动离线重渲染 |
| GET | `/proxy` | 读代理配置，返回 `{enabled,url,no_proxy}` |
| POST | `/proxy` | 保存代理，body `{enabled,url,noProxy}`；启用时校验 http/https 地址并拒绝 socks |
| POST | `/proxy/test` | 实测代理连通，body `{url}`，返回 `{ok,elapsed_ms,error,sample}` |

所有响应 `{ok:true,...}` 或 `{ok:false,error}`，`cache-control: no-store`。

## 引擎位置解析（index.js 顶部）

按优先级探测，首个含 `scripts/radar.py` 的命中：
1. 环境变量 `AI_GIT_RADAR_DIR`（显式指定）
2. monorepo 布局：本包 `../engine`（本仓库 plugin/ 与 engine/ 同级）
3. 历史布局：本包 `../ai-git-radar`
4. 宿主 cwd 的兄弟/子目录兜底

独立部署插件时设 `AI_GIT_RADAR_DIR` 最稳。Python 可用 `AI_GIT_RADAR_PYTHON` 覆盖。

## 关键实现约定（踩坑记录）

- **持久化 bundle 能用全局 fetch，动态沙箱插件不能**：`host.call/harness.handle`
  只存在于 cordis_define 的字符串沙箱半；ESM bundle 的 Client 半走 `window.__ModuleLoader__`
  加载，没有 host 内建，但浏览器全局 `fetch` 可用（官方 hmr/file-actions 等包都这么用）。
  所以本插件数据桥选 webServer 路由 + 同源 fetch，而不是 Typert remote（@local 包无法自建）。
- **slot 联动**：`sidebar.panellist` 的 list `id` 与 `main` 的 keyed `key` 同名（都是 `ai-news`）
  即自动联动成面板；order=15 插在 schedules(10) 与 dsh-context(20) 之间。
- **宿主 cwd 不可靠**：插件宿主 `process.cwd()` 是 `/home` 而非包目录，相对路径会算错
  （实测解析成 `/home/ai-git-radar`），所以用探测链而非单一路径。
- **--quiet 模式**：插件调 Python 加 `--quiet --json-out 固定路径`，不产生时间戳三件套、
  不打印分组摘要（radar.py 的 news 子命令新增参数），插件数据文件固定为 `data/plugin-news.json`。
- 样式只用 `--dsw-alias-*` 主题 token，深浅色自动跟随；动态文本不经 React 转义的地方
  （href 等）均来自引擎 JSON，无手写 HTML 拼接。

## 安装/重载

```bash
# 安装（workspace 内）
# 通过 plugin_manager install_bundle，target 为本目录绝对路径
# 改代码后重载：set_plugin 禁用再启用 include:ai-news-panel
```

entryId：`include:ai-news-panel`；包名：`@local/ai-news-panel`。
Client 半改动需要浏览器刷新页面；Host 半改动禁用/启用插件即生效。

## 与 skill 的分工

| | skill（ai-git-radar） | 本插件（ai-news-panel） |
|---|---|---|
| 形态 | Agent 工作流，命令行触发 | 常驻工作台面板 |
| 信源维护 | 编 feeds.json | 面板表单 |
| 深度能力 | GitHub 项目雷达（封存）、评分、翻译流水线、md/html 报告 | 资讯浏览 + 信源 CRUD + 一键刷新 |
| 数据 | 同一套 feeds.json / 缓存 / 翻译库，两边共享 | 同左 |
