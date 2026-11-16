// @local/ai-news-panel — Host 半
// 职责：
//   1. webServer 注册 /ai-news/* HTTP 路由（Client 半用同源 fetch 调用）
//   2. subprocess 调 ai-git-radar 的 python3 radar.py news 采集资讯
//   3. fs 读写 data/sources/feeds.json 做信源可视化维护
// 数据引擎（Python/feeds.py）零改动复用；本文件只是工作台外壳。

import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import path from 'node:path';

export const inject = ['webServer', 'subprocess'];

// 引擎位置解析（按优先级）：
//   1. 环境变量 AI_GIT_RADAR_DIR（显式指定，最高优先）
//   2. monorepo 布局：本包 ../engine（仓库内 plugin/ 与 engine/ 同级）
//   3. 历史开发布局：与本包同级的 ../ai-git-radar
//   4. 宿主 cwd 的兄弟/子目录兜底
import { fileURLToPath } from 'node:url';

const PLUGIN_DIR = path.dirname(fileURLToPath(import.meta.url));
const CANDIDATE_DIRS = [
  process.env.AI_GIT_RADAR_DIR,
  path.resolve(PLUGIN_DIR, '..', 'engine'),
  path.resolve(PLUGIN_DIR, '..', 'ai-git-radar'),
  path.resolve(process.cwd(), '..', 'ai-git-radar'),
  path.resolve(process.cwd(), 'ai-git-radar'),
].filter(Boolean);
const ENGINE_DIR = CANDIDATE_DIRS.find((p) => existsSync(path.join(p, 'scripts', 'radar.py')))
  || CANDIDATE_DIRS[0];
const RADAR_PY = path.join(ENGINE_DIR, 'scripts', 'radar.py');
const FEEDS_JSON = path.join(ENGINE_DIR, 'data', 'sources', 'feeds.json');
const OPML_CATALOG_JSON = path.join(ENGINE_DIR, 'data', 'sources', 'opml-catalog.json');
const SUGGESTIONS_JSON = path.join(ENGINE_DIR, 'data', 'source-suggestions.json');
const NEWS_PROGRESS_JSON = path.join(ENGINE_DIR, 'data', 'news-progress.json');
const PLUGIN_NEWS_JSON = path.join(ENGINE_DIR, 'data', 'plugin-news.json');
// 内存缓存：切 tab 不再每次重读 6MB+ JSON，5 分钟内复用
let newsCache = null;
let newsCacheAt = 0;
const NEWS_CACHE_TTL_MS = 5 * 60 * 1000;
const DEALS_JSON = path.join(ENGINE_DIR, 'data', 'deals.json');
let dealsCache = null;
let dealsCacheAt = 0;
const DEALS_CACHE_TTL_MS = 10 * 60 * 1000;   // 情报类低频变化，10 分钟
const PYTHON = process.env.AI_GIT_RADAR_PYTHON || 'python3';

const ROUTE_PREFIX = '/ai-news';

function sendJson(res, status, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
  });
  res.end(body);
}

async function readFeeds() {
  const raw = await readFile(FEEDS_JSON, 'utf-8');
  const parsed = JSON.parse(raw);
  if (!Array.isArray(parsed.sources)) throw new Error('feeds.json 缺少 sources 数组');
  return parsed;
}

function writeFeeds(doc) {
  return writeFile(FEEDS_JSON, `${JSON.stringify(doc, null, 2)}\n`, 'utf-8');
}

// 调 Python 引擎采集；offline=true 只读数缓存，秒级返回。
async function readDeals() {
  const now = Date.now();
  if (dealsCache && (now - dealsCacheAt) < DEALS_CACHE_TTL_MS) return dealsCache;
  if (!existsSync(DEALS_JSON)) return [];
  try {
    const doc = JSON.parse(await readFile(DEALS_JSON, 'utf-8'));
    dealsCache = doc.deals || [];
    dealsCacheAt = now;
    return dealsCache;
  } catch (e) { return []; }
}

function dealsAsNewsItems(deals) {
  // 转成 news item 格式，混入 RSS 列表；_kind='deal' 供前端样式区分
  // 补 enrich 四字段（form/obtain/topics/codes）与 kind，保证与采集条目同构
  return deals.map(d => ({
    title: d.title,
    link: d.link,
    summary: d.summary || '',
    published: d.expires ? d.expires : null,
    source_id: d.id,
    source_name: d.source_name || d.link,
    group: d.group || '模型优惠与福利',
    _kind: 'deal',
    kind: 'deal',
    form: 'deal',
    obtain: 'promo',
    topics: d.tags || [],
    codes: [],
    _tags: d.tags || [],
  }));
}

function mergeDeals(deals, news) {
  // deals 置顶；按 link 去重，避免 deals.json 与采集到的同链接条目重复出现
  const seen = new Set();
  const out = [];
  for (const it of [...deals, ...(news || [])]) {
    const key = it.link || `#${it.source_id}:${it.title}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(it);
  }
  return out;
}

function runRadarNews({ offline = true, perSource = 8, only = '' } = {}) {
  return new Promise((resolve, reject) => {
    const argv = [PYTHON, RADAR_PY, 'news',
      '--per-source', String(perSource),
      '--workers', '8',
      '--quiet',
      '--json-out', PLUGIN_NEWS_JSON];
    if (offline) argv.push('--offline');
    if (only) argv.push('--only', only);

    let handle;
    try {
      handle = subprocess.spawn({
        argv,
        cwd: ENGINE_DIR,
        stdio: {
          stdin: 'ignore',
          stdout: { maxBytes: 64 * 1024 },
          stderr: { maxBytes: 64 * 1024 },
        },
        graceMs: 120_000,
      });
    } catch (err) {
      reject(err);
      return;
    }
    handle.done.then(({ exitCode }) => {
      if (exitCode === 0) {
        resolve(exitCode);
      } else {
        const errText = handle.collected.stderr?.readFrom(0).text || '';
        reject(new Error(`radar.py news 退出码 ${exitCode}: ${errText.slice(-500)}`));
      }
    }).catch(reject);
  });
}

// 通用 radar.py 子进程（discover 等命令复用），返回 stdout/stderr 文本。
function runRadar(argv, { graceMs = 300_000 } = {}) {
  return new Promise((resolve, reject) => {
    let handle;
    try {
      handle = subprocess.spawn({
        argv: [PYTHON, RADAR_PY, ...argv],
        cwd: ENGINE_DIR,
        stdio: {
          stdin: 'ignore',
          stdout: { maxBytes: 256 * 1024 },
          stderr: { maxBytes: 64 * 1024 },
        },
        graceMs,
      });
    } catch (err) {
      reject(err);
      return;
    }
    handle.done.then(({ exitCode }) => {
      const stdout = handle.collected.stdout?.readFrom(0).text || '';
      const stderr = handle.collected.stderr?.readFrom(0).text || '';
      if (exitCode === 0) resolve({ stdout, stderr });
      else reject(new Error(`radar.py ${argv.join(' ')} 退出码 ${exitCode}: ${stderr.slice(-500) || stdout.slice(-500)}`));
    }).catch(reject);
  });
}

async function readSuggestions() {
  if (!existsSync(SUGGESTIONS_JSON)) return { generated_at: null, suggestions: [] };
  return JSON.parse(await readFile(SUGGESTIONS_JSON, 'utf-8'));
}

async function readOpmlCatalog() {
  if (!existsSync(OPML_CATALOG_JSON)) return { catalogs: [] };
  return JSON.parse(await readFile(OPML_CATALOG_JSON, 'utf-8'));
}

// 闭包内引用 subprocess 服务（apply 时绑定）。
let subprocess;

export async function apply(ctx) {
  subprocess = ctx.subprocess;

  // 启动时自检引擎是否在位（不阻断注册，只在状态接口报告）。
  const enginePresent = existsSync(RADAR_PY) && existsSync(FEEDS_JSON);

  const handler = async (req, res) => {
    const url = new URL(req.url, 'http://local');
    const route = url.pathname.slice(ROUTE_PREFIX.length); // 去掉前缀
    try {
      // ---- 状态自检 ----
      if (req.method === 'GET' && route === '/status') {
        sendJson(res, 200, {
          ok: true,
          engineDir: ENGINE_DIR,
          enginePresent,
          python: PYTHON,
          feedsJson: FEEDS_JSON,
        });
        return;
      }

      // ---- 资讯采集进度（前端轮询用）----
      if (req.method === 'GET' && route === '/news/progress') {
        try {
          if (!existsSync(NEWS_PROGRESS_JSON)) {
            sendJson(res, 200, { ok: true, stage: 'idle' });
            return;
          }
          const doc = JSON.parse(await readFile(NEWS_PROGRESS_JSON, 'utf-8'));
          sendJson(res, 200, { ok: true, ...doc });
        } catch (e) {
          sendJson(res, 200, { ok: true, stage: 'idle', read_error: String(e.message || e) });
        }
        return;
      }

      // ---- 自动机翻（免费通道，翻译英文标题/摘要后同步固定文件）----
      if (req.method === 'POST' && route === '/translate') {
        if (!enginePresent) {
          sendJson(res, 503, { ok: false, error: `引擎目录不存在: ${ENGINE_DIR}` });
          return;
        }
        const body = await readJsonBody(req);
        const limit = Number(body && body.limit) || 0;
        const argv = ['translate', '--news', '--auto'];
        if (limit > 0) argv.push('--limit', String(limit));
        try {
          // runRadar 成功才 resolve（失败会 reject），这里不再判 exitCode
          await runRadar(argv, { graceMs: 600000 });
          newsCache = null;                      // 译文变了，让下次 /news 重读
          newsCacheAt = 0;
          const payload = JSON.parse(await readFile(PLUGIN_NEWS_JSON, 'utf-8'));
          const deals = await readDeals();
          sendJson(res, 200, { ok: true,
            translated: Object.keys(payload.news_translations || {}).length,
            news: mergeDeals(dealsAsNewsItems(deals), payload.news || []),
            news_translations: payload.news_translations || {} });
        } catch (e) {
          sendJson(res, 500, { ok: false, error: String(e.message || e) });
        }
        return;
      }

      // ---- 资讯列表（默认离线读缓存；?refresh=1 在线采集）----
      if (req.method === 'GET' && route === '/news') {
        if (!enginePresent) {
          sendJson(res, 503, { ok: false, error: `引擎目录不存在: ${ENGINE_DIR}` });
          return;
        }
        const refresh = url.searchParams.get('refresh') === '1';
        const perSource = Number(url.searchParams.get('perSource') || '8');
        const only = url.searchParams.get('only') || '';
        if (refresh) {
          await runRadarNews({ offline: false, perSource, only });
          newsCache = JSON.parse(await readFile(PLUGIN_NEWS_JSON, 'utf-8'));
          newsCacheAt = Date.now();
        } else if (!existsSync(PLUGIN_NEWS_JSON)) {
          // 首次：先用缓存快速产出一份
          await runRadarNews({ offline: true, perSource, only });
          newsCache = JSON.parse(await readFile(PLUGIN_NEWS_JSON, 'utf-8'));
          newsCacheAt = Date.now();
        }
        const deals = await readDeals();
        const dealItems = dealsAsNewsItems(deals);
        // 内存缓存命中：跳过磁盘读+JSON 解析
        const now = Date.now();
        if (!refresh && newsCache && (now - newsCacheAt) < NEWS_CACHE_TTL_MS) {
          sendJson(res, 200, { ok: true, ...newsCache,
            news: mergeDeals(dealItems, newsCache.news || []) });
          return;
        }
        const payload = JSON.parse(await readFile(PLUGIN_NEWS_JSON, 'utf-8'));
        payload.news = mergeDeals(dealItems, payload.news || []);
        newsCache = payload;
        newsCacheAt = now;
        sendJson(res, 200, { ok: true, ...payload });
        return;
      }

      // ---- 信源列表 ----
      if (req.method === 'GET' && route === '/sources') {
        const doc = await readFeeds();
        sendJson(res, 200, { ok: true, ...doc });
        return;
      }

      // ---- 信源维护：新增 / 更新 / 启停 / 删除 ----
      if (req.method === 'POST' && route === '/sources') {
        const body = await readJsonBody(req);
        const doc = await readFeeds();
        const op = body.op;

        if (op === 'add') {
          const s = body.source || {};
          if (!s.id || !s.name || !s.url) {
            sendJson(res, 400, { ok: false, error: 'id/name/url 必填' });
            return;
          }
          if (doc.sources.some((x) => x.id === s.id)) {
            sendJson(res, 409, { ok: false, error: `id 已存在: ${s.id}` });
            return;
          }
          doc.sources.push({
            id: String(s.id),
            name: String(s.name),
            url: String(s.url),
            kind: s.kind === 'atom' ? 'atom' : 'rss',
            group: s.group || '个人与社区',
            tags: Array.isArray(s.tags) ? s.tags.map(String) : [],
            enabled: s.enabled !== false,
          });
        } else if (op === 'update') {
          const row = doc.sources.find((x) => x.id === body.id);
          if (!row) {
            sendJson(res, 404, { ok: false, error: `未找到信源: ${body.id}` });
            return;
          }
          for (const k of ['name', 'url', 'group', 'kind']) {
            if (body.patch && body.patch[k] !== undefined) row[k] = String(body.patch[k]);
          }
          if (body.patch && Array.isArray(body.patch.tags)) {
            row.tags = body.patch.tags.map(String);
          }
          if (body.patch && body.patch.enabled !== undefined) {
            row.enabled = !!body.patch.enabled;
            if (row.enabled) delete row.disabled_reason;
          }
        } else if (op === 'toggle') {
          const row = doc.sources.find((x) => x.id === body.id);
          if (!row) {
            sendJson(res, 404, { ok: false, error: `未找到信源: ${body.id}` });
            return;
          }
          row.enabled = !!body.enabled;
          if (row.enabled) delete row.disabled_reason;
          else if (body.reason) row.disabled_reason = String(body.reason);
        } else if (op === 'remove') {
          const before = doc.sources.length;
          doc.sources = doc.sources.filter((x) => x.id !== body.id);
          if (doc.sources.length === before) {
            sendJson(res, 404, { ok: false, error: `未找到信源: ${body.id}` });
            return;
          }
        } else {
          sendJson(res, 400, { ok: false, error: `未知 op: ${op}` });
          return;
        }

        await mkdir(path.dirname(FEEDS_JSON), { recursive: true });
        await writeFeeds(doc);
        sendJson(res, 200, { ok: true, count: doc.sources.length, sources: doc.sources });
        return;
      }

      // ---- 待审信源队列 ----
      if (req.method === 'GET' && route === '/suggestions') {
        const doc = await readSuggestions();
        sendJson(res, 200, { ok: true, ...doc });
        return;
      }

      // ---- 可选 OPML 目录（面板「发现」页的快捷导入按钮）----
      if (req.method === 'GET' && route === '/opml-catalog') {
        const doc = await readOpmlCatalog();
        sendJson(res, 200, { ok: true, ...doc });
        return;
      }

      // ---- 触发自动发现（网页 / OPML / 目录 / 远程清单）----
      if (req.method === 'POST' && route === '/discover') {
        if (!enginePresent) {
          sendJson(res, 503, { ok: false, error: `引擎目录不存在: ${ENGINE_DIR}` });
          return;
        }
        const body = await readJsonBody(req);
        const argv = ['discover'];
        if (body.mode === 'opml') {
          if (!body.target) {
            sendJson(res, 400, { ok: false, error: 'opml 模式需要 target（URL 或文件路径）' });
            return;
          }
          argv.push('--opml', String(body.target));
        } else if (body.mode === 'catalog') {
          if (!body.target) {
            sendJson(res, 400, { ok: false, error: 'catalog 模式需要 target（目录别名，逗号分隔）' });
            return;
          }
          argv.push('--opml-catalog', String(body.target));
        } else if (body.mode === 'remote') {
          argv.push('--remote');
          if (body.target) argv.push(String(body.target));
        } else {
          // 默认网页发现（body.mode === 'web' 或缺省）
        }
        const { stdout, stderr } = await runRadar(argv);
        const doc = await readSuggestions();
        sendJson(res, 200, { ok: true, log: `${stdout}\n${stderr}`.trim(), ...doc });
        return;
      }

      // ---- 待审队列决策：采纳（写回 feeds.json）/ 忽略 / 全部采纳 ----
      if (req.method === 'POST' && route === '/suggestions') {
        const body = await readJsonBody(req);
        const ids = Array.isArray(body.ids) ? body.ids.map(String) : [];
        let argv;
        if (body.op === 'accept-all') {
          const cur = await readSuggestions();
          if (!(cur.suggestions || []).some((s) => s.status === 'pending')) {
            const feeds = await readFeeds();
            sendJson(res, 200, {
              ok: true, log: '待审队列为空，无需处理',
              suggestions: cur.suggestions, sources: feeds.sources,
            });
            return;
          }
          argv = ['discover', '--accept-all'];
        } else if (body.op === 'accept' && ids.length) {
          argv = ['discover', '--accept', ids.join(',')];
        } else if (body.op === 'ignore' && ids.length) {
          argv = ['discover', '--ignore', ids.join(',')];
        } else {
          sendJson(res, 400, { ok: false, error: '需要 op=accept/ignore/accept-all 及对应 ids' });
          return;
        }
        const { stdout, stderr } = await runRadar(argv);
        const [suggestions, feeds] = await Promise.all([readSuggestions(), readFeeds()]);
        sendJson(res, 200, {
          ok: true, log: `${stdout}\n${stderr}`.trim(),
          suggestions: suggestions.suggestions, sources: feeds.sources,
        });
        return;
      }

      sendJson(res, 404, { ok: false, error: `no route: ${req.method} ${route}` });
    } catch (err) {
      sendJson(res, 500, { ok: false, error: String(err && err.message || err) });
    }
  };

  ctx.effect(() => ctx.webServer.register({
    kind: 'prefix',
    path: ROUTE_PREFIX,
    handler,
  }), 'ai-news-panel: /ai-news API');
}

function readJsonBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on('data', (c) => chunks.push(c));
    req.on('end', () => {
      try {
        resolve(chunks.length ? JSON.parse(Buffer.concat(chunks).toString('utf-8')) : {});
      } catch (err) {
        reject(err);
      }
    });
    req.on('error', reject);
  });
}
