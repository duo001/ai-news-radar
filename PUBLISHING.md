# 插件市场上架指南（备查，当前不发布）

> 调研时间：2026-11-23。依据：市场官方仓库 `losebird/dsh-plugin-market` 的
> `docs/SUBMIT.md`、`docs/REGISTRY.md`、`scripts/validate.mjs` 及 curated 真实条目。
> 市场网站 https://www.dsh-plugin.shop/ 只是该仓库静态 JSON 的前端，无后端。

## 一、市场机制（先理解再动手）

- 数据全是 GitHub 仓库里的静态 JSON：作者向 `registry/curated/<id>.json` 提 PR，
  `validate.mjs` 校验通过、维护者合并后，`merge-curated` 工作流数秒内 overlay 进
  `registry/all.json` 即上架；每日 `collect` 全量采集 GitHub，curated 条目始终覆盖同键 auto 条目。
- 上架流程：仓库推 GitHub → 发 Release（tag 即版本号）→ 市场网站上传页填表生成条目 JSON
  → 点「发起 PR」落到 `registry/curated/<id>.json` → 合并后 DSH 插件市场弹窗可见。
- 条目去重键 = npm 包名或规范化 repo URL；fork 一律排除；下架靠 `registry/blocklist.json`。
- `verified`（可一键安装判据）= package.json 声明了 `dsh.bundle.patch`。本插件已声明（`plugin/package.json` 的 `dsh.bundle.patch: ./cordis.patch.yml`）。
- git 托管（`github:`/`git+` spec）安装时会跑 prepare 脚本、被 pnpm 拦截——**构建产物必须直接提交进仓库**，一键安装只认 npm 包名或 Release 的 `https://…tgz`。

## 二、条目 JSON 字段（validate.mjs 硬性规则）

| 字段 | 必填 | 规则 |
|---|---|---|
| `id` | ✅ | 正则 `^[a-z0-9][a-z0-9._-]*$`，全局唯一，建议 `ai-news-panel` |
| `name` | ✅ | 显示名 |
| `type` | ✅ | 固定 `bundle`（pack 是 skill/preset 的 zip 合集，不适用） |
| `repo` | ✅ | `owner/name` 形式，即 `duo001/ai-news-radar` |
| `spec` | ✅ | bundle：npm 包名 / `https://…tgz` / `github:owner/repo#tag` / `git+https…#tag` |
| `description` | ✅ | 一句话简介（卡片显示） |
| `license` | ✅ | SPDX id，本仓是 `MIT`（LICENSE 已在） |
| `author.name` | ✅ | 作者名；`author.url` 可选但必须 `https://` 开头 |
| `category` | ⬜ | 白名单 11 选 1：`ui`/`session`/`agent`/`tools`/`dev`/`comm`/`auth`/`skills`/`market`/`fun`/`other`。本插件建议 `tools` |
| `tags` | ⬜ | 最多 8 个；**dsh、deepseek、claude-code 等生态噪声词会被过滤**，写功能词：`rss`、`资讯聚合`、`新闻`、`机器翻译`、`信源管理`、`agent` |
| `longDescription` | ⬜ | markdown 详情，写三页签能力、526 信源/15 分组、零 key 机翻、7 天窗口、Python 前置条件 |
| `source` | — | curated 条目填 `"curated"` |

参考真实条目：`dsh-github`（npm spec `@perrylink/dsh-github`）、
`agent-interactive-terminal`（tgz spec）、`dsh-dafeiyu-chan`（github: spec，仅展示）。

## 三、当前仓库的两个结构性阻塞（不解决则「装上也跑不起来」）

### 阻塞 1：tgz 不含 Python 引擎（最致命）

实测 `npm pack --dry-run`（在 `plugin/` 下）产物仅 8 个文件、35.4 kB（解包 126 kB）：

```
client.js  index.js  cordis.patch.yml  icon.svg  locale/{en,zh}.json  README.md  package.json
```

整个 `engine/`（21 个 py、7000+ 行、526 信源的 feeds.json）不在包里。
而 `plugin/index.js:367` 的 `enginePresent = existsSync(RADAR_PY) && existsSync(FEEDS_JSON)`
为 false 时所有 `/ai-news/*` 接口返 503。市场用户全局安装后，
`index.js:22-27` 的 `CANDIDATE_DIRS` 里 `path.resolve(PLUGIN_DIR, '..', 'engine')` 不存在，
面板能渲染但永远报「引擎目录不存在」。
注意 npm `files` 字段不能引用包目录外路径，不能简单写 `"../engine/**"`。

### 阻塞 2：包名是私有占位名

`plugin/package.json` 当前 `"name": "@local/ai-news-panel"`、`"private": true`、`version: "1.0.0"`：
`@local` scope 无法发布到 npm，private 禁止 publish；且 `plugin/cordis.patch.yml` 挂载名
写死 `@local/ai-news-panel`，改名必须同步改 patch 与 package.json。

### 其他前置缺口

- 无 `engine/requirements.txt`：引擎第三方依赖仅 `requests`、`PyYAML`（其余全标准库），需补文件并在 README 写明 Python 3.10+ 前置
- 仓库**没有任何 git tag**，首个 Release 需补 `v0.18.14`（与当前代码版本对齐）
- README 需要「安装/快速开始」章节：采集器只在该类章节内识别安装方式，否则条目被标 `manual`

## 四、三套方案（将来选其一）

### 方案 A：自包含 tgz + GitHub Release（推荐，无需 npm 账号）

市场先例最多（`agent-interactive-terminal`、`dsh-3d-model-viewer`、`dsh-api-probe`）。

1. 包名改 `ai-news-panel`，去掉 `private`；`cordis.patch.yml` 挂载名同步改
2. 新增 `scripts/release.sh`：组装临时打包目录（plugin 文件 + 复制进来的 `engine/`，
   布局为包根下 `engine/scripts/`、`engine/data/sources/`、`engine/data/deals.json` 等），
   在临时目录内 `npm pack`，产出 tgz 作为 GitHub Release 资产
3. `plugin/index.js` 的 `CANDIDATE_DIRS` 增加 `path.resolve(PLUGIN_DIR, 'engine')`
   （tgz 解包后的标准布局），保留现有探测顺序兜底
4. 补 `engine/requirements.txt`（两行：`requests`、`PyYAML`）
5. 发 Release（tag `v0.18.14`），spec 填
   `https://github.com/duo001/ai-news-radar/releases/download/v0.18.14/ai-news-panel-0.18.14.tgz`
6. selftest 加回归：tgz 解包后 `existsSync(engine/scripts/radar.py)` 为 true、引擎路径探测命中

### 方案 B：发布 npm（安装体验最好，需注册 npm 账号）

改造内容同方案 A 的 1-4，分发换成 `npm publish`；spec 直接填包名，升级走语义化版本。
市场先例：`dsh-github`（spec `@perrylink/dsh-github`）。

### 方案 C：仅展示条目（最快，不推荐）

spec 用 `github:duo001/ai-news-radar`，能过 validate、卡片出现在市场，但一键安装禁用、
标「手动安装」，用户需自行 clone 整仓 + 配软链 + 装 Python 依赖，等于现在的开发态装法。

## 五、上架检查清单（执行方案 A/B 时逐项勾）

- [ ] 包名去 `@local`/`private`，cordis.patch.yml 挂载名同步
- [ ] tgz 自包含引擎（解包后 enginePresent=true 有自测断言）
- [ ] CANDIDATE_DIRS 支持包内 `engine/` 布局
- [ ] requirements.txt + README 写明 Python 3.10+ 与两个 pip 依赖
- [ ] 构建产物入库，不依赖安装时 prepare
- [ ] git tag 与 Release 资产齐备，tag 与 spec 版本一致
- [ ] README 有「安装」章节（争取 dsh-plugin-add 标记而非 manual）
- [ ] 条目 JSON 过 `scripts/validate.mjs`（可 clone 市场仓库本地先跑）
- [ ] tags 只用功能词（生态词会被过滤），category=tools，license=MIT
- [ ] PR 路径 `registry/curated/ai-news-panel.json`

## 六、条目 JSON 草稿（方案 A，发布时按实际版本改）

```json
{
  "id": "ai-news-panel",
  "name": "AI 资讯雷达",
  "type": "bundle",
  "repo": "duo001/ai-news-radar",
  "spec": "https://github.com/duo001/ai-news-radar/releases/download/v0.18.14/ai-news-panel-0.18.14.tgz",
  "description": "侧边栏 AI 资讯工作台：526 个 RSS/Atom 信源聚合、多语种零 key 机翻、近似去重、关注词周报与信源治理。",
  "longDescription": "详见仓库 README：资讯/发现/信源维护三页签，英文日文韩文自动译中文，SQLite 30 天保留 + 面板 7 天窗口，需本机 Python 3.10+ 与 requests/PyYAML。",
  "category": "tools",
  "tags": ["rss", "资讯聚合", "新闻", "机器翻译", "信源管理", "agent"],
  "license": "MIT",
  "author": { "name": "duo001", "url": "https://github.com/duo001" },
  "source": "curated"
}
```
