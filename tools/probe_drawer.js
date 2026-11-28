// 浮层真机验证（jsdom + React 真实挂载）—— 查「元素构造了但没挂到树上」
//
// 为什么需要它：v0.18.20 发现详情抽屉 / 周报弹窗 / 错误日志弹窗从加入起从未渲染过，
// 根因是 `try` 块里的逗号序列表达式（`__out = h(...), weekly && h(...), logOpen && h(...);`
// 中间值全被丢弃），而 client-errors.log 一条报错都没有。静态字符串断言（"ain-drawer-mask" in src）
// 对这类 bug 完全无效，必须真挂载 React 组件再点一遍。
//
// 装依赖（只用一次性临时目录，别污染项目）：
//   npm i --prefix /tmp/jsx-probe --registry https://registry.npmjs.org \
//         --cache /tmp/npmcache-probe react@18 react-dom@18 jsdom acorn
// 运行：
//   node tools/probe_drawer.js
//   PROBE_CLIENT=/tmp/client_old.js node tools/probe_drawer.js   # 对比任意历史版本
//   PROBE_MODULES=/tmp/jsx-probe/node_modules                   # 默认即此路径
//
// 断言：点卡片 → 抽屉进 DOM、且不在 .ain-wrap 内（不被滚动容器裁）、Esc 能关；
//       点「周报」/「错误日志」→ 弹窗进 DOM（这条正是序列表达式 bug 的回归护栏）。
const path = require('path');
const fs = require('fs');

const PROBE = process.env.PROBE_MODULES || '/tmp/jsx-probe/node_modules';
const { JSDOM } = require(path.join(PROBE, 'jsdom'));

const dom = new JSDOM('<!doctype html><html><body></body></html>', { pretendToBeVisual: true });
global.window = dom.window;
global.document = dom.window.document;
global.navigator = dom.window.navigator;
global.HTMLElement = dom.window.HTMLElement;
global.Element = dom.window.Element;
global.Node = dom.window.Node;
global.getComputedStyle = dom.window.getComputedStyle.bind(dom.window);
global.requestAnimationFrame = (cb) => setTimeout(cb, 0);
global.cancelAnimationFrame = (id) => clearTimeout(id);
global.act = null;

const React = require(path.join(PROBE, 'react'));
const ReactDOM = require(path.join(PROBE, 'react-dom'));
const { act } = require(path.join(PROBE, 'react-dom/test-utils'));
global.IS_REACT_ACT_ENVIRONMENT = true;
dom.window.IS_REACT_ACT_ENVIRONMENT = true;

// 真实资讯数据：直接用引擎落盘的 plugin-news.json
const newsFile = path.join(__dirname, '..', 'engine', 'data', 'plugin-news.json');
const payload = JSON.parse(fs.readFileSync(newsFile, 'utf8'));
payload.news = (payload.news || []).slice(0, 40);
console.log('探针数据：', payload.news.length, '条');

const fetchStub = async (url) => {
  let body = { ok: true };
  if (String(url).includes('/news')) body = payload;
  else if (String(url).includes('/logs')) body = { ok: true, entries: [] };
  else if (String(url).includes('/watch')) body = { ok: true, terms: [] };
  else if (String(url).includes('/progress')) body = { ok: true, running: false };
  else if (String(url).includes('/sources')) body = { ok: true, sources: [] };
  return { ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body) };
};
global.fetch = fetchStub;
dom.window.fetch = fetchStub;

// 加载插件 client 半
const target = process.env.PROBE_CLIENT || path.join(__dirname, '..', 'plugin', 'client.js');
const src = fs.readFileSync(target, 'utf8');
console.log('探针目标:', target);
let registration = null;
dom.window.__ModuleLoader__ = { load: (mod) => { dom.window.__reg = mod; } };
const mod = new Function('window', 'document', 'React', 'require', 'globalThis', src)(dom.window, dom.window.document, React, (name) => {
  if (name === 'react') return React;
  return undefined;
}, global);
registration = dom.window.__reg;
if (!registration) throw new Error('模块没注册');

const half = registration.factory((name) => {
  if (name === 'react') return React;
  if (name === 'react-dom') return ReactDOM;
  if (name === 'react-dom/client') return ReactDOM;
  throw new Error('unexpected require ' + name);
});
console.log('模块 id:', registration.id);

// 拿到 Panel 组件
const slots = { inject: (_n, cb) => cb(), register: (_n, comp) => comp, effect: () => () => {} };
const ctx = {
  slots,
  effect: () => () => {},
  get: () => null,
};
let Panel = null;
const origRegister = slots.register;
slots.register = (name, comp) => {
  if (name && name.name === 'main') Panel = comp;
  return comp;
};
half.apply(ctx);
if (!Panel) throw new Error('没拿到 Panel 组件');

const root = document.createElement('div');
document.body.appendChild(root);
const reactRoot = ReactDOM.createRoot(root);

(async () => {
  await act(async () => { reactRoot.render(React.createElement(Panel)); });
  await act(async () => { await new Promise((r) => setTimeout(r, 120)); });

  const cards = root.querySelectorAll('.ain-item');
  console.log('渲染出卡片数:', cards.length);
  if (!cards.length) { console.log('❌ 没有卡片，探针中止'); process.exit(1); }

  if (root.querySelector('.ain-drawer-mask')) { console.log('❌ 初始就有抽屉，异常'); process.exit(1); }
  console.log('✓ 初始无抽屉');

  // 点第一张卡片
  await act(async () => { cards[0].dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true, cancelable: true })); });
  await act(async () => { await new Promise((r) => setTimeout(r, 50)); });

  const mask = root.querySelector('.ain-drawer-mask');
  const drawer = root.querySelector('.ain-drawer');
  console.log('点击后遮罩存在:', !!mask, '抽屉存在:', !!drawer);
  if (!mask) {
    // 诊断：直接看组件内部 state 有没有变
    console.log('  wrap 内是否出现 drawer 类:', !!root.querySelector('.ain-wrap .ain-drawer-mask'));
    console.log('  页面中出现 drawer 任何痕迹:', root.innerHTML.includes('ain-drawer'));
    console.log('  已读卡片数:', root.querySelectorAll('.ain-item.ain-read').length);
  }
  if (!mask || !drawer) {
    console.log('点击后根节点 HTML 片段:', root.innerHTML.slice(0, 600));
    console.log('是否渲染成错误块:', !!root.querySelector('.ain-err'));
    console.log('❌ 点击后抽屉没出现');
    console.log('  卡片 role:', cards[0].getAttribute('role'));
    process.exit(1);
  }

  // 关键：抽屉不能被放进 .ain-wrap
  const wrap = root.querySelector('.ain-wrap');
  const insideWrap = wrap ? wrap.contains(mask) : null;
  console.log('遮罩在 .ain-wrap 内:', insideWrap, '(必须为 false)');
  console.log('遮罩父级链:', (() => { const out = []; let n = mask; while (n && n !== root) { out.push(n.className || n.tagName); n = n.parentNode; } return out.join(' < '); })());
  const frag = mask.parentNode;
  console.log('包裹层 display:', frag && frag.style ? frag.style.display : '(无)');

  // 抽查抽屉内容
  const title = root.querySelector('.ain-drawer-title');
  const origBtn = Array.from(root.querySelectorAll('.ain-drawer-foot a')).map((a) => a.textContent);
  console.log('抽屉标题:', title && title.textContent.slice(0, 50));
  console.log('底部按钮:', Array.from(root.querySelectorAll('.ain-drawer-foot button')).map((b) => b.textContent), '链接:', origBtn);
  console.log('查看原文 href:', (root.querySelector('.ain-drawer-foot a') || {}).href);
  console.log('原文标题存在:', !!root.querySelector('.ain-drawer-orig'));

  // Esc 关闭
  await act(async () => { dom.window.dispatchEvent(new dom.window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); });
  await act(async () => { await new Promise((r) => setTimeout(r, 50)); });
  console.log('Esc 后抽屉还在:', !!root.querySelector('.ain-drawer-mask'));

  // ---- 另外两个浮层：周报 / 错误日志（逗号序列表达式 bug 的直接受害者）----
  const clickByText = async (re) => {
    const btn = Array.from(root.querySelectorAll('button')).find((b) => re.test(b.textContent || ''));
    if (!btn) return null;
    await act(async () => { btn.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true, cancelable: true })); });
    await act(async () => { await new Promise((r) => setTimeout(r, 200)); });
    return btn;
  };

  let modalPass = true;
  const logBtn = await clickByText(/日志|错误/);
  const logShown = !!root.querySelector('.ain-modal-mask');
  console.log('错误日志弹窗出现:', logShown, logBtn ? '' : '(没找到按钮)');
  if (!logShown) modalPass = false;
  if (logShown) {
    await act(async () => { root.querySelector('.ain-modal-mask').dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true })); });
    await act(async () => { await new Promise((r) => setTimeout(r, 100)); });
  }

  const weekBtn = await clickByText(/周报/);
  const weekShown = !!root.querySelector('.ain-modal-mask');
  console.log('周报弹窗出现:', weekShown, weekBtn ? '' : '(没找到按钮)');
  if (!weekShown) modalPass = false;

  const drawerPass = !!drawer && insideWrap === false && !root.querySelector('.ain-drawer-mask');
  const pass = drawerPass && modalPass;
  if (!drawerPass) console.log('抽屉断言失败：drawer=%s insideWrap=%s', !!drawer, insideWrap);
  if (!modalPass) console.log('浮层断言失败：抽屉/周报/日志里至少一个没进 DOM（查逗号序列表达式，坑 64）');
  console.log(pass ? '\n✅ 浮层探针通过（抽屉 + 周报 + 日志）' : '\n❌ 浮层探针失败');
  process.exit(pass ? 0 : 1);
})().catch((e) => { console.error('探针异常:', e); process.exit(1); });