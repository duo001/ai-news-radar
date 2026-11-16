// @local/ai-news-panel — Client 半
// 注册 sidebar.panellist 图标 + main 面板（同 PANEL_ID 联动）。
// 取数走同源 fetch /ai-news/*（Host 半的 webServer 路由）。无 JSX，全用 React.createElement。

window.__ModuleLoader__.load({
  id: '@local/ai-news-panel',
  factory(require) {
    const React = require('react');
    const h = React.createElement;
    const { useState, useEffect, useCallback } = React;

    const PANEL_ID = 'ai-news';
    const API = '/ai-news';

    function groupColor(name) {
      let h = 0;
      for (let i = 0; i < (name || '').length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
      const hue = h % 360;
      return `hsl(${hue} 60% 48%)`;
    }
    function srcInitial(name) {
      return (name || '?').trim().charAt(0).toUpperCase();
    }
    function fmtCount(n) {
      return n >= 10000 ? (n/10000).toFixed(1) + 'w' : n >= 1000 ? (n/1000).toFixed(1) + 'k' : String(n);
    }

    // 时间范围筛选：it.published 是否落在范围内。range: 'all'|'today'|'3d'|'7d'
    function inTimeRange(published, range) {
      if (range === 'all') return true;
      if (!published) return false;
      const d = new Date(published);
      if (isNaN(d)) return false;
      const now = new Date();
      if (range === 'today') {
        const t0 = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        return d >= t0;
      }
      const days = range === '3d' ? 3 : 7;
      return (now - d) <= days * 86400000;
    }
    const TIME_RANGE_LABEL = { all: '全部', today: '今日', '3d': '近 3 天', '7d': '近 7 天' };

    // 规则增强（enrich.py）的展示映射
    const FORM_LABEL = { freebie: '福利', deal: '优惠', release: '发布', paper: '论文',
      tutorial: '教程', opensource: '开源', news: '资讯' };
    const OBTAIN_LABEL = { free: '直接领', conditional: '需互动', lottery: '抽奖',
      trial: '试用', promo: '推广', paid: '付费' };

    function copyCode(ev, code) {
      ev.preventDefault(); ev.stopPropagation();
      const done = () => {
        const el = ev.currentTarget;
        const old = el.textContent;
        el.textContent = '已复制 ✓'; el.classList.add('copied');
        setTimeout(() => { el.textContent = old; el.classList.remove('copied'); }, 1200);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(code).then(done).catch(() => {});
      } else {
        const ta = document.createElement('textarea');
        ta.value = code; document.body.appendChild(ta); ta.select();
        try { document.execCommand('copy'); done(); } catch (e) {}
        document.body.removeChild(ta);
      }
    }

    // 卡片底部的领域标签 + 兑换码胶囊（两种视图共用）
    function enrichChips(it, gc) {
      const out = [];
      const topics = Array.isArray(it.topics) ? it.topics
        : (Array.isArray(it._tags) ? it._tags : []);
      if (topics.length) {
        out.push(h('div', { className: 'ain-topics', key: 'tp' },
          topics.map(t => h('span', { className: 'ain-topic', key: t,
            style: { '--group-color': gc } }, t))));
      }
      if (Array.isArray(it.codes) && it.codes.length) {
        out.push(h('div', { className: 'ain-codes', key: 'cd' },
          it.codes.map(c => h('span', { className: 'ain-code', key: c,
            title: '点击复制', onClick: (ev) => copyCode(ev, c) }, c))));
      }
      return out;
    }

    function todayCount(news) {
      const today = new Date(); today.setHours(0,0,0,0);
      return news.filter(it => it.published && new Date(it.published) >= today).length;
    }

    const CSS = `
.ain-wrap { display:flex; flex-direction:column; height:100%; padding:16px 20px 24px; overflow:auto;
  color:var(--dsw-alias-label-primary); background:var(--dsw-alias-bg-base); font-size:13px; }
.ain-head { display:flex; align-items:center; gap:10px; margin-bottom:12px; flex-wrap:wrap; }
.ain-title { font-size:16px; font-weight:600; margin:0; }
.ain-btn { border:1px solid var(--dsw-alias-border-l2); background:var(--dsw-alias-bg-layer-1);
  color:var(--dsw-alias-label-primary); border-radius:6px; padding:4px 12px; font-size:12px;
  cursor:pointer; line-height:1.4; }
.ain-btn:hover { border-color:var(--dsw-alias-brand-primary); color:var(--dsw-alias-brand-primary); }
.ain-btn:disabled { opacity:.5; cursor:default; }
.ain-btn.primary { background:var(--dsw-alias-brand-primary); border-color:var(--dsw-alias-brand-primary); color:#fff; }
.ain-tabs { display:flex; gap:4px; border-bottom:1px solid var(--dsw-alias-border-l1); margin-bottom:14px; }
.ain-tab { padding:7px 14px; cursor:pointer; border:none; background:none; font-size:13px;
  color:var(--dsw-alias-label-secondary); border-bottom:2px solid transparent; }
.ain-tab.active { color:var(--dsw-alias-brand-primary); border-bottom-color:var(--dsw-alias-brand-primary); font-weight:600; }
.ain-meta { color:var(--dsw-alias-label-secondary); font-size:12px; margin-bottom:10px; }
.ain-group { margin-bottom:18px; }
.ain-progress { margin:10px 0 6px; padding:8px 12px; background:var(--dsw-alias-bg-layer-1);
  border:1px solid var(--dsw-alias-border-l1); border-radius:6px; }
.ain-progress .row { display:flex; align-items:center; gap:10px; margin-bottom:6px; font-size:12px; }
.ain-progress .track { height:4px; background:var(--dsw-alias-border-l1); border-radius:2px; overflow:hidden; }
.ain-progress .fill { height:100%; background:var(--dsw-alias-brand-primary); transition:width .3s ease; }
.ain-progress .current { color:var(--dsw-alias-label-secondary); font-size:11px; }
.ain-tags { display:flex; flex-wrap:wrap; gap:6px; margin-bottom:14px; }
.ain-search { position:relative; display:flex; align-items:center; gap:8px; margin-bottom:14px; }
.ain-search-input { flex:1; padding:8px 74px 8px 12px; border-radius:8px; border:1px solid var(--dsw-alias-color-border);
  background:var(--dsw-alias-color-background); color:var(--dsw-alias-color-foreground); font-size:13px; outline:none; }
.ain-search-input:focus { border-color:var(--dsw-alias-color-primary); }
.ain-search-clear { position:absolute; right:64px; border:none; background:none; color:var(--dsw-alias-label-secondary);
  cursor:pointer; font-size:14px; padding:2px 6px; border-radius:4px; }
.ain-search-clear:hover { color:var(--dsw-alias-color-foreground); background:var(--dsw-alias-color-border); }
.ain-search-count { position:absolute; right:12px; font-size:12px; color:var(--dsw-alias-label-secondary); min-width:36px; text-align:right; }
.ain-tag { padding:3px 10px; border:1px solid var(--dsw-alias-border-l2); border-radius:12px;
  font-size:11px; background:var(--dsw-alias-bg-layer-1); cursor:pointer;
  color:var(--dsw-alias-label-secondary); }
.ain-tag:hover { border-color:var(--dsw-alias-brand-primary); color:var(--dsw-alias-brand-primary); }
.ain-tag.active { background:var(--dsw-alias-brand-primary); color:#fff; border-color:var(--dsw-alias-brand-primary); }
.ain-tag .count { margin-left:4px; opacity:.7; }
.ain-viewtoggle { display:flex; gap:0; border:1px solid var(--dsw-alias-border-l2); border-radius:6px; overflow:hidden; margin-left:auto; }
.ain-vt { padding:6px 14px; font-size:12px; background:var(--dsw-alias-bg-layer-1);
  color:var(--dsw-alias-label-secondary); border:none; cursor:pointer; }
.ain-vt.active { background:var(--dsw-alias-brand-primary); color:#fff; }
.ain-dup { color:var(--dsw-alias-label-secondary); font-size:11px; margin-left:8px; }
.ain-list { display:flex; flex-direction:column; }
.ain-masonry { column-count:2; column-gap:12px; }
@media(min-width:900px){ .ain-masonry{ column-count:3; } }
@media(min-width:1200px){ .ain-masonry{ column-count:4; } }
.ain-masonry .ain-item { break-inside:avoid; margin-bottom:12px; display:block; }
.ain-masonry .ain-item .t { font-size:13px; line-height:1.5; -webkit-line-clamp:3; }
.ain-masonry .ain-item .s { font-size:12px; -webkit-line-clamp:4; margin-top:6px; }
.ain-stats { display:grid; grid-template-columns:repeat(auto-fit, minmax(140px,1fr)); gap:12px; margin-bottom:20px; }
.ain-stat { padding:14px 16px; background:var(--dsw-alias-bg-layer-1); border:1px solid var(--dsw-alias-border-l1);
  border-radius:12px; display:flex; flex-direction:column; gap:4px; }
.ain-stat .n { font-size:24px; font-weight:700; color:var(--dsw-alias-brand-primary); line-height:1; }
.ain-stat .l { font-size:11px; color:var(--dsw-alias-label-secondary); letter-spacing:.3px; text-transform:uppercase; }
.ain-stat.accent .n { color:var(--dsw-alias-label-primary); }
.ain-item { position:relative; overflow:hidden; padding:14px 16px 14px 18px; border:1px solid var(--dsw-alias-border-l1);
  border-radius:12px; margin-bottom:12px; text-decoration:none; color:inherit; background:var(--dsw-alias-bg-layer-1);
  transition:box-shadow .15s ease, transform .15s ease, border-color .15s ease; }
.ain-item::before { content:''; position:absolute; left:0; top:0; bottom:0; width:3px; background:var(--group-color, var(--dsw-alias-border-l2)); }
.ain-item:hover { border-color:var(--dsw-alias-brand-primary); box-shadow:0 4px 16px rgba(0,0,0,.08); transform:translateY(-1px); }
.ain-item .meta-row { display:flex; align-items:center; gap:8px; margin-bottom:8px; }
.ain-avatar { width:22px; height:22px; border-radius:6px; background:var(--group-color, var(--dsw-alias-brand-primary));
  color:#fff; display:flex; align-items:center; justify-content:center; font-size:11px; font-weight:700; flex-shrink:0; }
.ain-src { font-size:11px; color:var(--dsw-alias-label-secondary); font-weight:600; }
.ain-gtag { padding:2px 8px; border-radius:4px; font-size:10px; background:color-mix(in srgb, var(--group-color, var(--dsw-alias-brand-primary)) 12%, transparent);
  color:var(--group-color, var(--dsw-alias-brand-primary)); font-weight:600; }
.ain-time { margin-left:auto; font-size:10px; color:var(--dsw-alias-label-secondary); }
.ain-item .t { font-size:14px; font-weight:600; line-height:1.5; display:-webkit-box; -webkit-line-clamp:2;
  -webkit-box-orient:vertical; overflow:hidden; margin-bottom:6px; }
.ain-item .s { font-size:12px; color:var(--dsw-alias-label-secondary); line-height:1.55; display:-webkit-box; -webkit-line-clamp:3;
  -webkit-box-orient:vertical; overflow:hidden; margin-top:0; }
.ain-masonry .ain-item .t { -webkit-line-clamp:3; font-size:13.5px; }
.ain-masonry .ain-item .s { -webkit-line-clamp:5; font-size:11.5px; }
.ain-item.deal { border-color:var(--dsw-alias-brand-primary); background:
  linear-gradient(135deg, color-mix(in srgb, var(--dsw-alias-brand-primary) 6%, var(--dsw-alias-bg-layer-1)),
  var(--dsw-alias-bg-layer-1)); }
.ain-item.deal::before { width:4px; }
.ain-item.deal .t { font-weight:700; }
.ain-deal-badge { padding:2px 8px; border-radius:4px; font-size:10px; font-weight:700;
  background:var(--dsw-alias-brand-primary); color:#fff; margin-left:8px; }
.ain-deal-tags { display:flex; flex-wrap:wrap; gap:4px; margin-top:8px; }
.ain-deal-tags span { padding:2px 6px; border-radius:4px; font-size:10px;
  background:var(--dsw-alias-bg-layer-2); color:var(--dsw-alias-label-secondary); }

/* 形态徽章 / 领域标签 / 兑换码胶囊（规则增强 enrich.py） */
.ain-form-badge { padding:2px 8px; border-radius:4px; font-size:10px; font-weight:700;
  margin-left:8px; border:1px solid transparent; white-space:nowrap; }
.ain-form-badge.freebie { background:#fff7e6; color:#d46b08; border-color:#ffd591; }
.ain-form-badge.deal { background:#f6ffed; color:#389e0d; border-color:#b7eb8f; }
.ain-form-badge.release { background:#e6f4ff; color:#0958d9; border-color:#91caff; }
.ain-form-badge.paper { background:#f9f0ff; color:#722ed1; border-color:#d3adf7; }
.ain-form-badge.tutorial { background:#e6fffb; color:#08979c; border-color:#87e8de; }
.ain-form-badge.opensource { background:#f0f5ff; color:#2f54eb; border-color:#adc6ff; }
.ain-obtain { font-size:10px; color:var(--dsw-alias-label-secondary); margin-left:6px; }
.ain-topics { display:flex; flex-wrap:wrap; gap:4px; margin-top:6px; }
.ain-topic { padding:1px 7px; border-radius:10px; font-size:10px;
  background:color-mix(in srgb, var(--group-color, var(--dsw-alias-brand-primary)) 10%, transparent);
  color:var(--dsw-alias-label-secondary); }
.ain-codes { display:flex; flex-wrap:wrap; gap:6px; margin-top:6px; }
.ain-code { padding:2px 8px; border-radius:5px; font-size:11px; font-weight:700; font-family:monospace;
  background:#fffbe6; color:#ad6800; border:1px solid #ffe58f; cursor:pointer; user-select:none; }
.ain-code:hover { background:#fff1b8; }
.ain-code.copied { background:#f6ffed; color:#389e0d; border-color:#b7eb8f; }

.ain-group h3 { font-size:13px; margin:0 0 8px; color:var(--dsw-alias-label-secondary); font-weight:600; }
.ain-group h3.time { color:var(--dsw-alias-brand-primary); }
.ain-item { display:block; padding:10px 12px; border:1px solid var(--dsw-alias-border-l1);
  border-radius:8px; margin-bottom:8px; text-decoration:none; color:inherit;
  background:var(--dsw-alias-bg-layer-1); }
.ain-item:hover { border-color:var(--dsw-alias-brand-primary); }
.ain-item .t { font-weight:600; line-height:1.45; display:-webkit-box; -webkit-line-clamp:2;
  -webkit-box-orient:vertical; overflow:hidden; }
.ain-item .orig { color:var(--dsw-alias-label-secondary); font-size:11px; margin-top:3px;
  display:-webkit-box; -webkit-line-clamp:1; -webkit-box-orient:vertical; overflow:hidden; }
.ain-item .s { color:var(--dsw-alias-label-secondary); font-size:12px; margin-top:5px;
  display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; line-height:1.5; }
.ain-item .m { display:flex; gap:8px; margin-top:6px; font-size:11px; color:var(--dsw-alias-label-secondary); }
.ain-err { color:var(--dsw-alias-state-error-primary); font-size:12px; margin:8px 0; }
.ain-empty { color:var(--dsw-alias-label-secondary); padding:30px 0; text-align:center; }
.ain-src { border:1px solid var(--dsw-alias-border-l1); border-radius:8px; padding:10px 12px;
  margin-bottom:8px; background:var(--dsw-alias-bg-layer-1); }
.ain-src .row1 { display:flex; align-items:center; gap:8px; }
.ain-src .nm { font-weight:600; flex:1; }
.ain-src .url { font-size:11px; color:var(--dsw-alias-label-secondary); word-break:break-all; margin:5px 0; }
.ain-src .tags { font-size:11px; color:var(--dsw-alias-label-secondary); }
.ain-badge { font-size:10px; padding:1px 7px; border-radius:10px; border:1px solid var(--dsw-alias-border-l2); }
.ain-badge.on { color:var(--dsw-alias-state-success-primary); border-color:var(--dsw-alias-state-success-primary); }
.ain-badge.off { color:var(--dsw-alias-state-idle-primary); }
.ain-src button { margin-left:6px; }
.ain-form { border:1px dashed var(--dsw-alias-border-l2); border-radius:8px; padding:12px; margin-bottom:16px; }
.ain-form input, .ain-form select { width:100%; box-sizing:border-box; margin-bottom:8px; padding:6px 9px;
  border:1px solid var(--dsw-alias-border-l2); border-radius:6px; font-size:12px;
  background:var(--dsw-alias-bg-base); color:var(--dsw-alias-label-primary); }
.ain-form label { font-size:11px; color:var(--dsw-alias-label-secondary); display:block; margin-bottom:3px; }
.ain-spin { opacity:.6; }
`;

    async function api(path, opts) {
      const res = await fetch(API + path, {
        headers: { 'content-type': 'application/json' },
        ...opts,
      });
      const data = await res.json().catch(() => ({ ok: false, error: `HTTP ${res.status}` }));
      if (!res.ok || data.ok === false) throw new Error(data.error || `HTTP ${res.status}`);
      return data;
    }

    function fmtDate(published) {
      if (!published) return '';
      const d = new Date(published);
      if (Number.isNaN(d.getTime())) return String(published).slice(5, 10);
      return `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    }

    // ---------- 资讯面板 ----------
    function NewsPanel() {
      const [data, setData] = useState(null);
      const [loading, setLoading] = useState(true);
      const [refreshing, setRefreshing] = useState(false);
      const [error, setError] = useState('');
      const [progress, setProgress] = useState(null);
      const [activeTag, setActiveTag] = useState('全部');
  const [viewMode, setViewMode] = useState('list');   // 'list' | 'masonry'
  const [timeRange, setTimeRange] = useState('all');   // 'all' | 'today' | '3d' | '7d'
      const [query, setQuery] = useState('');            // 搜索关键字（过滤标题/摘要，含中文译文）
      const [translating, setTranslating] = useState(false); // 自动机翻进行中

      const load = useCallback(async (refresh) => {
        if (refresh) setRefreshing(true); else setLoading(true);
        setError('');
        try {
          const d = await api(refresh ? '/news?refresh=1' : '/news');
          setData(d);
        } catch (err) {
          setError(err.message);
        } finally {
          setLoading(false);
          setRefreshing(false);
        }
      }, []);

      // 自动机翻：把英文标题/摘要走免费通道翻成中文
      const runTranslate = useCallback(async () => {
        setTranslating(true);
        setError('');
        try {
          await api('/translate', { method: 'POST', body: '{}' });
          await load(false);
        } catch (err) {
          setError(err.message);
        } finally {
          setTranslating(false);
        }
      }, [load]);

      // 采集期间每秒轮询进度；完成后关定时器并 reload
      useEffect(() => {
        if (!refreshing) return;
        let stopped = false;
        const tick = async () => {
          try {
            const p = await api('/news/progress');
            if (stopped) return;
            setProgress(p.stage === 'idle' ? null : p);
            if (p.stage === 'done') {
              setProgress(null);
              load(false);
            }
          } catch (_) { /* 单次轮询失败忽略 */ }
        };
        const timer = setInterval(tick, 1000);
        tick();
        return () => { stopped = true; clearInterval(timer); };
      }, [refreshing, load]);

      useEffect(() => { load(false); }, [load]);

      if (loading) return h('div', { className: 'ain-empty' }, '正在读取资讯缓存…');
      if (error) return h('div', { className: 'ain-wrap' },
        h('div', { className: 'ain-err' }, `加载失败：${error}`),
        h('button', { className: 'ain-btn', onClick: () => load(false) }, '重试'));

      const news = (data && data.news) || [];
      const trans = (data && data.news_translations) || {};
      const failures = (data && data.news_failures) || [];

      // 搜索关键字：命中标题/摘要/中文译文任一即保留（大小写不敏感）
      const q = query.trim().toLowerCase();
      // 分组为主：按激活标签过滤 + 时间范围筛选 + 搜索
      let filtered = (activeTag !== '全部')
        ? news.filter((it) => it.group === activeTag)
        : news;
      filtered = filtered.filter((it) => inTimeRange(it.published, timeRange));
      if (q) {
        filtered = filtered.filter((it) => {
          const tr = trans[it.link] || {};
          const zh = (tr.zh_title || '') + ' ' + (tr.zh_summary || '');
          return (it.title || '').toLowerCase().includes(q)
            || (it.summary || '').toLowerCase().includes(q)
            || zh.toLowerCase().includes(q);
        });
      }
      // 按分组分桶，组内按最新发布时间倒序（无日期放最后）
      const groups = {};
      for (const it of filtered) {
        (groups[it.group] = groups[it.group] || []).push(it);
      }
      const sortNewest = (a, b) => {
        const ta = a.published ? new Date(a.published).getTime() : -1;
        const tb = b.published ? new Date(b.published).getTime() : -1;
        return tb - ta;
      };
      for (const k of Object.keys(groups)) groups[k].sort(sortNewest);
      // 标签计数：跟随时间范围+搜索（不含分组维度），切换日期后各分组数量同步更新
      const pool = (timeRange === 'all') ? news : news.filter((it) => inTimeRange(it.published, timeRange));
      const searchedPool = q
        ? pool.filter((it) => {
            const tr = trans[it.link] || {};
            const zh = (tr.zh_title || '') + ' ' + (tr.zh_summary || '');
            return (it.title || '').toLowerCase().includes(q)
              || (it.summary || '').toLowerCase().includes(q)
              || zh.toLowerCase().includes(q);
          })
        : pool;
      const tagCounts = {};
      for (const it of searchedPool) tagCounts[it.group] = (tagCounts[it.group] || 0) + 1;
      const tagList = Object.entries(tagCounts).sort((a, b) => b[1] - a[1]);
      // 分组按组内最新一条时间倒序输出（活跃分组排前面）
      const orderedGroups = Object.entries(groups)
        .map(([g, items]) => [g, items, items[0] && items[0].published ? new Date(items[0].published).getTime() : -1])
        .sort((a, b) => b[2] - a[2])
        .map(([g, items]) => [g, items]);

      // 采集进度百分比
      const pct = progress && progress.total
        ? Math.round((progress.done / progress.total) * 100)
        : 0;

      return h('div', { className: 'ain-wrap' },
        h('div', { className: 'ain-head' },
          h('h2', { className: 'ain-title' }, 'AI 资讯'),
          h('span', { className: 'ain-meta', style: { margin: 0 } }, `${news.length} 条`),
          (data && data.news_dup > 0) && h('span', { className: 'ain-dup' },
            `去重 ${data.news_dup} 条`),
          h('div', { className: 'ain-viewtoggle' },
            h('button', {
              className: 'ain-vt' + (viewMode === 'list' ? ' active' : ''),
              onClick: () => setViewMode('list'),
            }, '☰ 列表'),
            h('button', {
              className: 'ain-vt' + (viewMode === 'masonry' ? ' active' : ''),
              onClick: () => setViewMode('masonry'),
            }, '▦ 瀑布流')),
          h('div', { className: 'ain-viewtoggle' },
            ['all', 'today', '3d', '7d'].map((rg) =>
              h('button', {
                className: 'ain-vt' + (timeRange === rg ? ' active' : ''),
                onClick: () => setTimeRange(rg),
              }, TIME_RANGE_LABEL[rg]))),
          h('button', {
            className: 'ain-btn primary', disabled: refreshing || translating,
            onClick: () => load(true),
          }, refreshing ? '采集中…' : '在线刷新'),
          h('button', {
            className: 'ain-btn', disabled: translating || refreshing,
            onClick: () => runTranslate(),
            title: '把英文标题和摘要自动翻译成中文（免费通道，无需 API key）',
          }, translating ? '翻译中…' : '自动翻译')),
        // 搜索框：过滤标题/摘要/中文译文
        h('div', { className: 'ain-search' },
          h('input', {
            type: 'text', className: 'ain-search-input',
            placeholder: '搜索标题、摘要或中文译文…',
            value: query,
            onInput: (e) => setQuery(e.target.value),
          }),
          query && h('button', {
            className: 'ain-search-clear', title: '清空',
            onClick: () => setQuery(''),
          }, '✕'),
          query && h('span', { className: 'ain-search-count' }, `${filtered.length} 条`)),
        data && data.generated_at && h('div', { className: 'ain-meta' },
          `更新于 ${new Date(data.generated_at).toLocaleString()}`),
        // 进度条（采集期间显示）
        refreshing && h('div', { className: 'ain-progress' },
          h('div', { className: 'row' },
            h('span', null, progress ? `采集中 ${progress.done}/${progress.total}` : '正在启动…'),
            h('span', { className: 'current' }, progress && progress.current
              ? `当前：${progress.current}` : '')),
          h('div', { className: 'track' },
            h('div', { className: 'fill', style: { width: pct + '%' } }))),
        !refreshing && news.length > 0 && h('div', { className: 'ain-stats' },
          h('div', { className: 'ain-stat accent' },
            h('div', { className: 'n' }, String(todayCount(news))),
            h('div', { className: 'l' }, '今日新增')),
          h('div', { className: 'ain-stat' },
            h('div', { className: 'n' }, String(news.length)),
            h('div', { className: 'l' }, '资讯总数')),
          h('div', { className: 'ain-stat' },
            h('div', { className: 'n' }, String((data && data.news_dup) || 0)),
            h('div', { className: 'l' }, '已去重')),
          h('div', { className: 'ain-stat accent' },
            h('div', { className: 'n' }, String(news.filter(x => x._kind === 'deal').length)),
            h('div', { className: 'l' }, '情报福利')),
          h('div', { className: 'ain-stat' },
            h('div', { className: 'n' }, String(new Set(news.map(x => x.source_id || x.source_name)).size)),
            h('div', { className: 'l' }, '活跃信源'))),
        // 标签过滤（有资讯且不止一个分组时显示）
        !refreshing && news.length > 0 && tagList.length > 0 && h('div', { className: 'ain-tags' },
          h('button', {
            className: 'ain-tag' + (activeTag === '全部' ? ' active' : ''),
            onClick: () => setActiveTag('全部'),
          }, `全部 ${news.length}`),
          tagList.map(([g, n]) => h('button', {
            key: g,
            className: 'ain-tag' + (activeTag === g ? ' active' : ''),
            onClick: () => setActiveTag(g),
          }, `${g} ${n}`))),
        failures.length > 0 && h('div', { className: 'ain-err' },
          `失败信源 ${failures.length} 个：${failures.map((f) => f.name).join('、')}`),
        news.length === 0 ? h('div', { className: 'ain-empty' }, '暂无资讯，点「在线刷新」采集')
          : filtered.length === 0 && q ? h('div', { className: 'ain-empty' }, `没有匹配「${query.trim()}」的资讯`)
          : viewMode === 'masonry'
          ? h('div', { className: 'ain-masonry' },
            filtered.map((it) => {
              const tr = trans[it.link] || {};
              const title = tr.zh_title || it.title;
              const showOrig = tr.zh_title && tr.zh_title !== it.title;
              const summary = tr.zh_summary || it.summary || '';
              const gc = groupColor(it.group);
              const isDeal = it._kind === 'deal';
              const formBadge = (!isDeal && it.form && it.form !== 'news')
                ? h('span', { className: `ain-form-badge ${it.form}` }, FORM_LABEL[it.form] || it.form)
                : null;
              const obtainTxt = (!isDeal && it.obtain && OBTAIN_LABEL[it.obtain])
                ? h('span', { className: 'ain-obtain' }, `· ${OBTAIN_LABEL[it.obtain]}`) : null;
              return h('a', {
                className: 'ain-item' + (isDeal ? ' deal' : ''), key: it.link,
                href: it.link, target: '_blank', rel: 'noreferrer',
                style: { '--group-color': gc },
              },
                h('div', { className: 'meta-row' },
                  h('div', { className: 'ain-avatar' }, isDeal ? '🎁' : srcInitial(it.source_name)),
                  h('span', { className: 'ain-src' }, it.source_name),
                  h('span', { className: 'ain-gtag' }, it.group),
                  isDeal && h('span', { className: 'ain-deal-badge' }, '情报'),
                  formBadge, obtainTxt,
                  h('span', { className: 'ain-time' }, fmtDate(it.published))),
                h('div', { className: 't' }, title),
                showOrig && h('div', { className: 'orig' }, it.title),
                summary && h('div', { className: 's' }, summary),
                isDeal && (it._tags || []).length > 0 && h('div', { className: 'ain-deal-tags' },
                  it._tags.map(t => h('span', { key: t }, t))),
                ...(isDeal ? [] : enrichChips(it, gc)));
            }))
          : orderedGroups.map(([gname, items]) =>
            h('div', { className: 'ain-group', key: gname },
              h('h3', null, `${gname}（${items.length}）`),
              items.map((it) => {
                const tr = trans[it.link] || {};
                const title = tr.zh_title || it.title;
                const showOrig = tr.zh_title && tr.zh_title !== it.title;
                const summary = tr.zh_summary || it.summary || '';
                const gc = groupColor(it.group);
                const isDeal = it._kind === 'deal';
                const formBadge = (!isDeal && it.form && it.form !== 'news')
                  ? h('span', { className: `ain-form-badge ${it.form}` }, FORM_LABEL[it.form] || it.form)
                  : null;
                const obtainTxt = (!isDeal && it.obtain && OBTAIN_LABEL[it.obtain])
                  ? h('span', { className: 'ain-obtain' }, `· ${OBTAIN_LABEL[it.obtain]}`) : null;
                return h('a', {
                  className: 'ain-item' + (isDeal ? ' deal' : ''), key: it.link,
                  href: it.link, target: '_blank', rel: 'noreferrer',
                  style: { '--group-color': gc },
                },
                  h('div', { className: 'meta-row' },
                    h('div', { className: 'ain-avatar' }, isDeal ? '🎁' : srcInitial(it.source_name)),
                    h('span', { className: 'ain-src' }, it.source_name),
                    h('span', { className: 'ain-gtag' }, it.group),
                    isDeal && h('span', { className: 'ain-deal-badge' }, '情报'),
                    formBadge, obtainTxt,
                    h('span', { className: 'ain-time' }, fmtDate(it.published))),
                  h('div', { className: 't' }, title),
                  showOrig && h('div', { className: 'orig' }, it.title),
                  summary && h('div', { className: 's' }, summary),
                  isDeal && (it._tags || []).length > 0 && h('div', { className: 'ain-deal-tags' },
                    it._tags.map(t => h('span', { key: t }, t))),
                  ...(isDeal ? [] : enrichChips(it, gc)));
              }))));
    }

    // ---------- 信源维护面板 ----------
    const GROUPS = ['厂商官方', '开源生态', '学术研究', '科技媒体', '个人与社区'];

    function SourcePanel() {
      const [doc, setDoc] = useState(null);
      const [error, setError] = useState('');
      const [busyId, setBusyId] = useState('');
      const [form, setForm] = useState({ id: '', name: '', url: '', group: GROUPS[0], kind: 'rss' });

      const reload = useCallback(async () => {
        setError('');
        try { setDoc(await api('/sources')); } catch (err) { setError(err.message); }
      }, []);
      useEffect(() => { reload(); }, [reload]);

      const post = async (body, id) => {
        setBusyId(id || 'form');
        setError('');
        try {
          const d = await api('/sources', { method: 'POST', body: JSON.stringify(body) });
          setDoc({ ...doc, sources: d.sources });
        } catch (err) { setError(err.message); } finally { setBusyId(''); }
      };

      if (!doc) return h('div', { className: 'ain-empty' }, error ? `加载失败：${error}` : '加载中…');

      const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

      return h('div', { className: 'ain-wrap' },
        h('div', { className: 'ain-head' },
          h('h2', { className: 'ain-title' }, '信源维护'),
          h('span', { className: 'ain-meta', style: { margin: 0 } },
            `${doc.sources.filter((s) => s.enabled).length} 启用 / ${doc.sources.length} 总数`)),
        error && h('div', { className: 'ain-err' }, error),

        h('div', { className: 'ain-form' },
          h('label', null, '新增信源（id 用小写字母/数字/连字符）'),
          h('input', { placeholder: 'id，如 my-ai-blog', value: form.id, onChange: set('id') }),
          h('input', { placeholder: '名称', value: form.name, onChange: set('name') }),
          h('input', { placeholder: 'RSS/Atom 地址 https://…', value: form.url, onChange: set('url') }),
          h('select', { value: form.group, onChange: set('group') },
            GROUPS.map((g) => h('option', { key: g, value: g }, g))),
          h('select', { value: form.kind, onChange: set('kind') },
            h('option', { value: 'rss' }, 'RSS'),
            h('option', { value: 'atom' }, 'Atom')),
          h('button', {
            className: 'ain-btn primary', disabled: busyId === 'form',
            onClick: () => {
              post({ op: 'add', source: form }, 'form')
                .then(() => setForm({ id: '', name: '', url: '', group: GROUPS[0], kind: 'rss' }));
            },
          }, busyId === 'form' ? '提交中…' : '添加信源')),

        doc.sources.map((s) => h('div', { className: 'ain-src', key: s.id },
          h('div', { className: 'row1' },
            h('span', { className: 'nm' }, s.name),
            h('span', { className: `ain-badge ${s.enabled ? 'on' : 'off'}` },
              s.enabled ? '启用' : '停用'),
            h('span', { className: 'ain-badge' }, s.kind)),
          h('div', { className: 'url' }, s.url),
          h('div', { className: 'tags' },
            `${s.id} · ${s.group}${s.tags && s.tags.length ? ' · ' + s.tags.join('/') : ''}${s.disabled_reason ? ' · ' + s.disabled_reason : ''}`),
          h('div', { style: { marginTop: 8 } },
            h('button', {
              className: 'ain-btn', disabled: busyId === s.id,
              onClick: () => post({ op: 'toggle', id: s.id, enabled: !s.enabled }, s.id),
            }, busyId === s.id ? '…' : (s.enabled ? '停用' : '启用')),
            h('button', {
              className: 'ain-btn', disabled: busyId === s.id,
              onClick: () => {
                if (window.confirm(`确认删除信源「${s.name}」？`)) {
                  post({ op: 'remove', id: s.id }, s.id);
                }
              },
            }, '删除')))));
    }

    // ---------- 信源发现面板（自动发现 → 待审队列 → 一键采纳）----------
    function DiscoverPanel() {
      const [doc, setDoc] = useState(null);
      const [catalog, setCatalog] = useState({ catalogs: [] });
      const [error, setError] = useState('');
      const [busy, setBusy] = useState('');
      const [log, setLog] = useState('');
      const [opmlUrl, setOpmlUrl] = useState('');
      const [catalogAlias, setCatalogAlias] = useState('');

      const reload = useCallback(async () => {
        setError('');
        try {
          const [s, c] = await Promise.all([api('/suggestions'), api('/opml-catalog')]);
          setDoc(s);
          setCatalog(c);
          if (!catalogAlias && c.catalogs && c.catalogs.length) setCatalogAlias(c.catalogs[0].alias);
        } catch (err) { setError(err.message); }
      }, [catalogAlias]);
      useEffect(() => { reload(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

      const runDiscover = async (mode, target, key) => {
        setBusy(key); setError(''); setLog('发现中，每个候选需实际验证 feed，可能要几十秒…');
        try {
          const d = await api('/discover', {
            method: 'POST', body: JSON.stringify({ mode, target }),
          });
          setDoc(d);
          setLog((d.log || '').split('\n').slice(-6).join('\n'));
        } catch (err) {
          setError(err.message); setLog('');
        } finally { setBusy(''); }
      };

      const decide = async (op, ids) => {
        setBusy(op + (ids && ids.length ? ':' + ids[0] : '')); setError('');
        try {
          const d = await api('/suggestions', {
            method: 'POST', body: JSON.stringify({ op, ids: ids || [] }),
          });
          setDoc({ ...doc, suggestions: d.suggestions });
          setLog(d.log || '');
        } catch (err) { setError(err.message); } finally { setBusy(''); }
      };

      if (!doc) return h('div', { className: 'ain-empty' }, error ? `加载失败：${error}` : '加载中…');
      const pending = (doc.suggestions || []).filter((s) => s.status === 'pending');
      const decided = (doc.suggestions || []).filter((s) => s.status !== 'pending');

      return h('div', { className: 'ain-wrap' },
        h('div', { className: 'ain-head' },
          h('h2', { className: 'ain-title' }, '信源发现'),
          h('span', { className: 'ain-meta', style: { margin: 0 } },
            `待审 ${pending.length} · 已处理 ${decided.length}`)),
        error && h('div', { className: 'ain-err' }, error),

        h('div', { className: 'ain-form' },
          h('label', null, '① 网页自动发现（解析种子站点的 RSS 声明，30 个种子站）'),
          h('button', {
            className: 'ain-btn primary', disabled: !!busy,
            onClick: () => runDiscover('web', '', 'web'),
          }, busy === 'web' ? '发现中…' : '开始网页发现'),

          h('label', { style: { marginTop: 10 } }, '② 精选 OPML 目录（已验证可下载的社区清单）'),
          h('select', { value: catalogAlias, onChange: (e) => setCatalogAlias(e.target.value) },
            (catalog.catalogs || []).map((c) =>
              h('option', { key: c.alias, value: c.alias }, c.name))),
          h('button', {
            className: 'ain-btn', disabled: !!busy, style: { marginTop: 6 },
            onClick: () => runDiscover('catalog', catalogAlias, 'catalog'),
          }, busy === 'catalog' ? '导入中…' : '导入该目录'),

          h('label', { style: { marginTop: 10 } }, '③ 自定义 OPML 地址'),
          h('input', {
            placeholder: 'https://…/xxx.opml', value: opmlUrl,
            onChange: (e) => setOpmlUrl(e.target.value),
          }),
          h('button', {
            className: 'ain-btn', disabled: !!busy || !opmlUrl,
            onClick: () => runDiscover('opml', opmlUrl, 'opml'),
          }, busy === 'opml' ? '导入中…' : '导入 OPML'),

          h('label', { style: { marginTop: 10 } }, '④ 同步远程开源信源表（AIHOT）'),
          h('button', {
            className: 'ain-btn', disabled: !!busy,
            onClick: () => runDiscover('remote', '', 'remote'),
          }, busy === 'remote' ? '同步中…' : '远程清单同步')),

        log && h('pre', {
          className: 'ain-meta',
          style: { whiteSpace: 'pre-wrap', background: 'var(--dsw-alias-bg-layer-1)',
            padding: 8, borderRadius: 6, border: '1px solid var(--dsw-alias-border-l1)' },
        }, log),

        pending.length > 0 && h('div', { className: 'ain-head', style: { marginTop: 8 } },
          h('strong', null, `待审队列（${pending.length}）`),
          h('button', {
            className: 'ain-btn primary', disabled: !!busy,
            onClick: () => decide('accept-all'),
          }, busy === 'accept-all' ? '采纳中…' : '全部采纳')),

        pending.length === 0
          ? h('div', { className: 'ain-empty' }, '待审队列为空。点上方任一发现通道，验证通过的信源会出现在这里。')
          : pending.map((s) => h('div', { className: 'ain-src', key: s.id },
              h('div', { className: 'row1' },
                h('span', { className: 'nm' }, s.name || s.id),
                h('span', { className: 'ain-badge' }, s.group || '其他'),
                h('span', { className: 'ain-badge' }, s.kind || 'rss')),
              h('div', { className: 'url' }, s.url),
              h('div', { className: 'tags' },
                `条目 ${s.item_count ?? '?'} · 最近更新 ${(s.latest_item_at || '--').slice(0, 10)} · 来源：${s.found_via || ''}`),
              h('div', { style: { marginTop: 8 } },
                h('button', {
                  className: 'ain-btn primary', disabled: !!busy,
                  onClick: () => decide('accept', [s.id]),
                }, busy === 'accept:' + s.id ? '…' : '采纳'),
                h('button', {
                  className: 'ain-btn', disabled: !!busy,
                  onClick: () => decide('ignore', [s.id]),
                }, busy === 'ignore:' + s.id ? '…' : '忽略')))),

        decided.length > 0 && h('details', { style: { marginTop: 16 } },
          h('summary', { className: 'ain-meta', style: { cursor: 'pointer' } },
            `已处理 ${decided.length} 个（采纳/忽略历史）`),
          decided.slice(-20).map((s) => h('div', { className: 'ain-meta', key: s.id, style: { marginTop: 4 } },
            `${s.status === 'accepted' ? '✓' : '✗'} ${s.name || s.id} — ${s.url}`))));
    }

    // ---------- 主面板（含 tab 切换）----------
    function Panel() {
      const [tab, setTab] = useState('news');
      return h(React.Fragment, null,
        h('div', { className: 'ain-tabs' },
          h('button', { className: `ain-tab ${tab === 'news' ? 'active' : ''}`, onClick: () => setTab('news') }, '资讯'),
          h('button', { className: `ain-tab ${tab === 'discover' ? 'active' : ''}`, onClick: () => setTab('discover') }, '发现'),
          h('button', { className: `ain-tab ${tab === 'sources' ? 'active' : ''}`, onClick: () => setTab('sources') }, '信源维护')),
        tab === 'news' ? h(NewsPanel)
          : tab === 'discover' ? h(DiscoverPanel) : h(SourcePanel));
    }

    // 侧边栏图标（ownerProps 提供 size/active）
    function PanelIcon(props) {
      const size = (props && props.size) || 20;
      const active = !!(props && props.active);
      return h('svg', {
        width: size, height: size, viewBox: '0 0 24 24', fill: 'none',
        stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round',
        strokeLinejoin: 'round', style: { opacity: active ? 1 : 0.75 },
        'aria-label': 'AI 资讯',
      },
        h('path', { d: 'M4 5h16v11H4z' }),
        h('path', { d: 'M7 8h10M7 11h7' }),
        h('circle', { cx: 17.5, cy: 17.5, r: 4.2, fill: 'var(--dsw-alias-brand-primary)', stroke: 'none' }),
        h('path', { d: 'M16 17.5l1 1 2-2', stroke: '#fff', strokeWidth: 1.4 }));
    }

    return {
      inject: ['slots'],
      apply(ctx) {
        const disposeCss = safeStyles(ctx);
        const d1 = ctx.slots.inject('main', () => ctx.slots.register({
          name: 'main', key: PANEL_ID,
        }, Panel));
        const d2 = ctx.slots.inject('sidebar.panellist', () => ctx.slots.register({
          name: 'sidebar.panellist', id: PANEL_ID, order: 15,
          label: 'AI 资讯',
        }, PanelIcon));
        ctx.effect(() => () => { d1(); d2(); disposeCss(); }, 'ai-news-panel: slots');
      },
    };

    // styles 是动态 client 半内建；ESM bundle 里兜底用 <style> 注入。
    function safeStyles(ctx) {
      try {
        const styles = ctx.get('styles');
        if (styles && typeof styles.insert === 'function') return styles.insert(CSS);
      } catch { /* fall through */ }
      const el = document.createElement('style');
      el.textContent = CSS;
      document.head.appendChild(el);
      return () => el.remove();
    }
  },
});
