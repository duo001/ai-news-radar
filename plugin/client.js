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
    // 构建标记：白屏排查用。硬刷新后标题应显示该标记；看不到 = 浏览器仍在跑旧缓存 bundle
    const BUILD_TAG = 'v0.18.5';

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

    // 卡片底部的领域标签 + 兑换码胶囊（两种视图共用，模块级纯渲染；
    // activeTopic 由组件内的 makeEnrichChips 注入，这里只负责无状态展示）
    function enrichChips(it, gc, topicState) {
      const out = [];
      const [activeTopic, setActiveTopic] = topicState || ['', () => {}];
      const topics = Array.isArray(it.topics) ? it.topics
        : (Array.isArray(it._tags) ? it._tags : []);
      if (topics.length) {
        out.push(h('div', { className: 'ain-topics', key: 'tp' },
          topics.map(t => h('button', {
            className: 'ain-topic' + (activeTopic === t ? ' active' : ''), key: t,
            style: { '--group-color': gc },
            title: `只看「${t}」主题`,
            onClick: (ev) => {
              ev.preventDefault(); ev.stopPropagation();
              setActiveTopic(activeTopic === t ? '' : t);
            },
          }, t))));
      }
      if (Array.isArray(it.codes) && it.codes.length) {
        out.push(h('div', { className: 'ain-codes', key: 'cd' },
          it.codes.map(c => h('span', { className: 'ain-code', key: c,
            title: '点击复制', onClick: (ev) => copyCode(ev, c) }, c))));
      }
      return out;
    }

    // 卡片上的近似去重徽章（🔗 另有 N 家）；模块级纯渲染，masonry/list 两视图共用
    // 曾只在 masonry 分支定义、list 分支引用导致 ReferenceError 整面板崩（坑 51）
    function dupBadgeOf(it) {
      if (it._kind === 'deal' || !(it.dup_count > 0)) return null;
      return h('span', {
        className: 'ain-dup-badge',
        title: `同事件另有 ${it.dup_count} 家报道：${(it.dup_sources || []).join('、')}`,
      }, `🔗 另有 ${it.dup_count} 家`);
    }

    // 卡片上的关键词关注胶囊（🔖 标记，点击可按该词筛选）；模块级纯渲染
    function watchChips(it, watchState) {
      const hits = Array.isArray(it.watch_hits) ? it.watch_hits : [];
      if (!hits.length) return [];
      const [activeWatch, setActiveWatch] = watchState || ['', () => {}];
      return [h('div', { className: 'ain-watch', key: 'wa' },
        hits.map(t => h('button', {
          className: 'ain-watch-chip' + (activeWatch === t ? ' active' : ''), key: t,
          title: `关注词「${t}」命中，点击只看该词`,
          onClick: (ev) => {
            ev.preventDefault(); ev.stopPropagation();
            setActiveWatch(activeWatch === t ? '' : t);
          },
        }, `🔖 ${t}`)))];
    }

    function todayCount(news) {
      const today = new Date(); today.setHours(0,0,0,0);
      return news.filter(it => it.published && new Date(it.published) >= today).length;
    }

    const CSS = `
.ain-wrap { display:flex; flex-direction:column; flex:1 1 auto; min-height:0; height:auto; padding:16px 20px 24px; overflow-y:auto;
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
/* 已读：整体降到半透明，hover 时恢复，避免干扰浏览但保留可回看 */
.ain-item.ain-read { opacity:.5; }
.ain-item.ain-read:hover { opacity:1; }
.ain-item.ain-read .t { font-weight:500; }
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
.ain-dup-badge { padding:2px 8px; border-radius:4px; font-size:10px; font-weight:600;
  background:#f5f5f5; color:#595959; border:1px solid #d9d9d9; cursor:help; }
.ain-obtain { font-size:10px; color:var(--dsw-alias-label-secondary); margin-left:6px; }
.ain-topics { display:flex; flex-wrap:wrap; gap:4px; margin-top:6px; }
.ain-topic { padding:1px 7px; border-radius:10px; font-size:10px; border:none; cursor:pointer;
  font-family:inherit; line-height:1.6;
  background:color-mix(in srgb, var(--group-color, var(--dsw-alias-brand-primary)) 10%, transparent);
  color:var(--dsw-alias-label-secondary); }
.ain-topic:hover { background:color-mix(in srgb, var(--group-color, var(--dsw-alias-brand-primary)) 22%, transparent); }
.ain-topic.active { background:var(--group-color, var(--dsw-alias-brand-primary)); color:#fff; }
.ain-topics-bar { display:flex; flex-wrap:wrap; gap:5px; align-items:center; margin:-4px 0 12px; }
.ain-topics-label { font-size:11px; color:var(--dsw-alias-label-tertiary); margin-right:2px; }
.ain-topic-chip { padding:2px 9px; border-radius:11px; font-size:11px; cursor:pointer;
  border:1px solid var(--dsw-alias-border-l2); background:transparent; color:var(--dsw-alias-label-secondary);
  font-family:inherit; }
.ain-topic-chip:hover { border-color:var(--dsw-alias-brand-primary); }
.ain-topic-chip.active { background:var(--dsw-alias-brand-primary); border-color:var(--dsw-alias-brand-primary); color:#fff; }
.ain-codes { display:flex; flex-wrap:wrap; gap:6px; margin-top:6px; }
.ain-code { padding:2px 8px; border-radius:5px; font-size:11px; font-weight:700; font-family:monospace;
  background:#fffbe6; color:#ad6800; border:1px solid #ffe58f; cursor:pointer; user-select:none; }
.ain-code:hover { background:#fff1b8; }
.ain-code.copied { background:#f6ffed; color:#389e0d; border-color:#b7eb8f; }
.ain-watch { display:flex; flex-wrap:wrap; gap:6px; margin-top:6px; }
.ain-watch-chip { padding:1px 7px; border-radius:10px; font-size:10px; border:1px solid #ffd591;
  cursor:pointer; font-family:inherit; line-height:1.6; background:#fff7e6; color:#d46b08; }
.ain-watch-chip:hover { background:#ffe7ba; }
.ain-watch-chip.active { background:#d46b08; color:#fff; border-color:#d46b08; }
.ain-watch-bar { margin-top:-6px; }
.ain-watch-chip-bar { padding:2px 9px; border-radius:11px; font-size:11px; cursor:pointer;
  border:1px solid #ffd591; background:#fff7e6; color:#d46b08; font-family:inherit; }
.ain-watch-chip-bar:hover { border-color:#d46b08; }
.ain-watch-chip-bar.active { background:#d46b08; border-color:#d46b08; color:#fff; }
.ain-watch-manage { padding:2px 9px; border-radius:11px; font-size:11px; cursor:pointer;
  border:1px solid #d9d9d9; background:#fafafa; color:#595959; font-family:inherit; margin-left:4px; }
.ain-watch-manage:hover, .ain-watch-manage.active { border-color:#d46b08; color:#d46b08; }
.ain-watch-editor { border:1px solid #ffd591; background:#fffaf2; border-radius:10px;
  padding:10px 12px; margin:-4px 0 8px; display:flex; flex-direction:column; gap:8px; }
.ain-watch-add { display:flex; gap:8px; }
.ain-watch-add input { flex:1; padding:5px 10px; border:1px solid #d9d9d9; border-radius:7px;
  font-size:12px; font-family:inherit; min-width:0; }
.ain-watch-add input:focus { outline:none; border-color:#d46b08; }
.ain-watch-conf-list { display:flex; flex-wrap:wrap; gap:6px; }
.ain-watch-empty { font-size:11px; color:#8c8c8c; }
.ain-watch-conf { display:inline-flex; align-items:center; gap:5px; border:1px solid #ffd591;
  background:#fff7e6; border-radius:9px; padding:1px 4px 1px 8px; font-size:11px; color:#d46b08; }
.ain-watch-conf.off { opacity:.45; border-style:dashed; }
.ain-watch-conf-term { max-width:180px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.ain-watch-conf-btn { border:none; background:transparent; color:#8c8c8c; cursor:pointer;
  font-size:10px; padding:1px 4px; border-radius:5px; font-family:inherit; }
.ain-watch-conf-btn:hover { background:#ffe7ba; color:#d46b08; }
.ain-watch-conf-btn.danger:hover { background:#fff1f0; color:#cf1322; }
/* 代理配置面板 */
.ain-proxy-editor { border:1px solid #91caff; background:#f0f8ff; border-radius:10px;
  padding:10px 12px; margin:-4px 0 8px; display:flex; flex-direction:column; gap:8px; }
.ain-proxy-row { display:flex; align-items:center; gap:8px; }
.ain-proxy-label { font-size:11px; color:#666; min-width:56px; flex-shrink:0; }
.ain-proxy-row input { flex:1; padding:5px 10px; border:1px solid #d9d9d9; border-radius:7px;
  font-size:12px; font-family:inherit; min-width:0; }
.ain-proxy-row input:focus { outline:none; border-color:#0958d9; }
.ain-proxy-actions { display:flex; gap:8px; flex-wrap:wrap; }
.ain-proxy-result { font-size:11px; padding:5px 9px; border-radius:6px; }
.ain-proxy-result.ok { background:#f6ffed; color:#389e0d; border:1px solid #b7eb8f; }
.ain-proxy-result.fail { background:#fff1f0; color:#cf1322; border:1px solid #ffa39e; }
.ain-proxy-hint { font-size:11px; color:#8c8c8c; line-height:1.6; }
.ain-proxy-on { border-color:#0958d9 !important; color:#0958d9 !important; }
.ain-modal-mask { position:fixed; inset:0; background:rgba(0,0,0,.45); z-index:1000;
  display:flex; align-items:center; justify-content:center; padding:24px; }
.ain-modal { width:min(820px, 94vw); max-height:86vh; display:flex; flex-direction:column;
  background:var(--dsw-alias-bg-base); border:1px solid var(--dsw-alias-border-l2);
  border-radius:10px; box-shadow:0 12px 40px rgba(0,0,0,.28); overflow:hidden; }
.ain-modal-head { display:flex; align-items:center; justify-content:space-between;
  padding:12px 16px; border-bottom:1px solid var(--dsw-alias-border-l1); }
.ain-modal-actions { display:flex; gap:8px; }
.ain-modal-body { padding:16px 20px; overflow:auto; line-height:1.7; }
/* 错误日志弹窗 */
.ain-log-list { display:flex; flex-direction:column; gap:8px; }
.ain-log-line { border:1px solid #d9d9d9; border-radius:8px; padding:8px 10px; font-size:12px;
  background:#fafafa; }
.ain-log-line.ain-log-error { border-color:#ffa39e; background:#fff1f0; }
.ain-log-line.ain-log-warn { border-color:#ffd591; background:#fff7e6; }
.ain-log-head { display:flex; gap:8px; align-items:center; margin-bottom:3px; }
.ain-log-level { font-weight:700; font-size:10px; padding:1px 6px; border-radius:4px;
  text-transform:uppercase; background:#d9d9d9; color:#fff; }
.ain-log-error .ain-log-level { background:#cf1322; }
.ain-log-warn .ain-log-level { background:#d46b08; }
.ain-log-ts { color:#8c8c8c; font-size:10px; }
.ain-log-msg { word-break:break-word; }
.ain-log-extra { margin:4px 0 0; padding:6px 8px; background:rgba(0,0,0,.04); border-radius:5px;
  font-size:11px; white-space:pre-wrap; word-break:break-word; max-height:180px; overflow:auto; }
.ain-modal-body h2 { font-size:18px; margin:6px 0 10px; }
.ain-modal-body h3 { font-size:15px; margin:16px 0 8px; color:var(--dsw-alias-brand-primary); }
.ain-modal-body h4 { font-size:13px; margin:12px 0 6px; }
.ain-modal-body ul { margin:4px 0 8px; padding-left:20px; }
.ain-modal-body li { margin:3px 0; font-size:12.5px; }
.ain-modal-body blockquote { margin:6px 0; padding:6px 10px; border-left:3px solid var(--dsw-alias-brand-primary);
  background:var(--dsw-alias-bg-layer-1); color:var(--dsw-alias-label-secondary); font-size:12px; border-radius:0 4px 4px 0; }
.ain-modal-body table { border-collapse:collapse; margin:8px 0; font-size:12px; }
.ain-modal-body td { border:1px solid var(--dsw-alias-border-l2); padding:4px 12px; }
.ain-modal-body code { background:var(--dsw-alias-bg-layer-1); padding:1px 5px; border-radius:4px;
  font-family:monospace; font-size:11px; color:#d46b08; }
.ain-modal-body a { color:var(--dsw-alias-brand-primary); }

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

    // ===== 前端错误日志（v0.18）=====
    // 本地环形缓冲（最多 50 条），同时批量/失焦时上报后端落盘 data/client-errors.log
    const LOG_MAX = 50;
    const clientLog = [];
    let logFlushTimer = null;
    function pushClientLog(level, message, extra) {
      const entry = {
        ts: new Date().toISOString(),
        level,
        message: String(message || '').slice(0, 2000),
        url: (typeof location !== 'undefined' && location.href) || '',
        ...(extra ? { extra: String(extra).slice(0, 2000) } : {}),
      };
      clientLog.push(entry);
      if (clientLog.length > LOG_MAX) clientLog.shift();
      scheduleFlush();
      // 同时打到浏览器控制台，便于 F12 实时查看
      try { (console[level] || console.log).call(console, '[ai-news]', entry.message, extra || ''); } catch { /* noop */ }
    }
    function scheduleFlush() {
      if (logFlushTimer) return;
      logFlushTimer = setTimeout(flushClientLog, 3000);
    }
    async function flushClientLog() {
      if (logFlushTimer) { clearTimeout(logFlushTimer); logFlushTimer = null; }
      if (!clientLog.length) return;
      const batch = clientLog.splice(0, clientLog.length);
      try {
        await fetch(API + '/logs', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ entries: batch }),
        });
      } catch {
        // 上报失败把日志放回缓冲，等下一轮；超量时丢弃最旧的
        clientLog.unshift(...batch);
        while (clientLog.length > LOG_MAX) clientLog.shift();
      }
    }
    if (typeof window !== 'undefined') {
      window.addEventListener('error', (ev) => {
        pushClientLog('error', ev.message || 'window error',
          `${ev.filename || ''}:${ev.lineno || 0}:${ev.colno || 0}`);
      });
      window.addEventListener('unhandledrejection', (ev) => {
        const r = ev.reason;
        pushClientLog('error', (r && r.message) ? r.message : 'unhandled promise rejection',
          (r && r.stack) ? String(r.stack).slice(0, 1500) : String(r));
      });
      window.addEventListener('pagehide', () => { try { flushClientLog(); } catch { /* noop */ } });
    }

    // React 错误边界：子树渲染抛错时兜底显示，而不是整个面板白屏
    class ErrorBoundary extends React.Component {
      constructor(props) {
        super(props);
        this.state = { error: null };
      }
      static getDerivedStateFromError(error) { return { error }; }
      componentDidCatch(error, info) {
        pushClientLog('error', `渲染崩溃: ${(error && error.message) || error}`,
          (info && info.componentStack) || (error && error.stack) || '');
      }
      render() {
        if (this.state.error) {
          return h('div', { className: 'ain-wrap' },
            h('div', { className: 'ain-err', style: { whiteSpace: 'pre-wrap', margin: '12px 0' } },
              h('strong', null, '面板渲染出错（已记录到错误日志）'),
              h('div', { style: { marginTop: 6, fontSize: 12, opacity: 0.85 } },
                String(this.state.error.message || this.state.error))),
            h('div', { style: { display: 'flex', gap: 8 } },
              h('button', { className: 'ain-btn primary', onClick: () => this.setState({ error: null }) }, '重试渲染'),
              h('button', { className: 'ain-btn', onClick: () => location.reload() }, '刷新页面')));
        }
        return this.props.children;
      }
    }

    async function api(path, opts) {
      const res = await fetch(API + path, {
        headers: { 'content-type': 'application/json' },
        ...opts,
      });
      const data = await res.json().catch(() => ({ ok: false, error: `HTTP ${res.status}` }));
      if (!res.ok || data.ok === false) {
        const msg = data.error || `HTTP ${res.status}`;
        pushClientLog('warn', `接口失败 ${(opts && opts.method) || 'GET'} ${path}：${msg}`);
        throw new Error(msg);
      }
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
      const [activeTopic, setActiveTopic] = useState(''); // 领域主题筛选（enrich.topics，空=不限）
      const [activeWatch, setActiveWatch] = useState(''); // 关键词关注筛选（watch_hits，空=不限）
      const [translating, setTranslating] = useState(false); // 自动机翻进行中
      const [unreadOnly, setUnreadOnly] = useState(false);    // 只看未读
      const [weekly, setWeekly] = useState(null);  // 周报 Markdown（null=未打开）
      const [weeklyBusy, setWeeklyBusy] = useState(false);
      const [watchConf, setWatchConf] = useState([]); // watch.json 全量关键词（含停用）
      const [watchInput, setWatchInput] = useState('');
      const [watchBusy, setWatchBusy] = useState(false);
      const [watchEditorOpen, setWatchEditorOpen] = useState(false);
      // 代理配置：proxy.json 决定全部外网请求出口
      const [proxyOpen, setProxyOpen] = useState(false);
      const [proxyConf, setProxyConf] = useState({ enabled: false, url: '', no_proxy: '' });
      const [proxyInput, setProxyInput] = useState('');
      const [proxyNoProxy, setProxyNoProxy] = useState('');
      const [proxyBusy, setProxyBusy] = useState(false);
      const [proxyTest, setProxyTest] = useState(null); // {ok,error,elapsed_ms,sample} | null
      const [logOpen, setLogOpen] = useState(false);      // 错误日志弹窗
      const [logEntries, setLogEntries] = useState([]);
      const [logBusy, setLogBusy] = useState(false);
      // 已读状态本地覆盖层：{link: true/false}，服务端返回值作为初值
      const [readMap, setReadMap] = useState({});

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

      // 载入关注词配置（面板管理用）
      useEffect(() => {
        api('/watch').then((d) => setWatchConf(d.keywords || [])).catch(() => {});
      }, []);

      // 载入代理配置
      useEffect(() => {
        api('/proxy').then((d) => {
          setProxyConf({ enabled: !!d.enabled, url: d.url || '', no_proxy: d.no_proxy || '' });
          setProxyInput(d.url || '');
          setProxyNoProxy(d.no_proxy || '');
        }).catch(() => {});
      }, []);

      // 保存代理配置（enabled=true 时服务端会校验地址格式）
      const saveProxy = useCallback(async (enabled) => {
        setProxyBusy(true);
        setError('');
        try {
          const d = await api('/proxy', {
            method: 'POST',
            body: JSON.stringify({ enabled, url: proxyInput.trim(), noProxy: proxyNoProxy.trim() }),
          });
          setProxyConf({ enabled: !!d.enabled, url: d.url || '', no_proxy: d.no_proxy || '' });
        } catch (err) {
          setError(err.message);
        } finally {
          setProxyBusy(false);
        }
      }, [proxyInput, proxyNoProxy]);

      // 测试代理连通性（走引擎同一套 netcfg 实现）
      const testProxyConn = useCallback(async () => {
        const url = proxyInput.trim();
        if (!url) { setProxyTest({ ok: false, error: '请先填写代理地址' }); return; }
        setProxyBusy(true);
        setProxyTest(null);
        try {
          setProxyTest(await api('/proxy/test', {
            method: 'POST', body: JSON.stringify({ url }),
          }));
        } catch (err) {
          setProxyTest({ ok: false, error: err.message });
        } finally {
          setProxyBusy(false);
        }
      }, [proxyInput]);

      // 错误日志：拉取后端落盘的 client-errors.log 查看
      const openLogs = useCallback(async () => {
        setLogBusy(true);
        setError('');
        try {
          const d = await api('/logs?limit=200');
          setLogEntries(d.logs || []);
          setLogOpen(true);
        } catch (err) {
          setError(err.message);
        } finally {
          setLogBusy(false);
        }
      }, []);
      const clearLogs = useCallback(async () => {
        try {
          await api('/logs', { method: 'DELETE' });
          setLogEntries([]);
        } catch (err) {
          setError(err.message);
        }
      }, []);

      // 关注词增删/启停：写服务端后重拉配置与资讯（服务端会离线重渲染 watch_hits）
      const watchOp = useCallback(async (op, term, extra) => {
        setWatchBusy(true);
        setError('');
        try {
          const d = await api('/watch', {
            method: 'POST',
            body: JSON.stringify({ op, term, ...(extra || {}) }),
          });
          setWatchConf(d.keywords || []);
          await load(false);
        } catch (err) {
          setError(err.message);
        } finally {
          setWatchBusy(false);
        }
      }, [load]);

      const addWatch = useCallback(async () => {
        const term = watchInput.trim();
        if (!term) return;
        await watchOp('add', term);
        setWatchInput('');
      }, [watchInput, watchOp]);

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

      // 周报：后端跑 radar.py weekly，返回 Markdown 文本在弹窗中展示
      // 注意：useCallback 是 Hook，必须放在下面 loading/error 的条件 return 之前，
      // 否则条件返回会改变 Hook 调用次数导致 React 抛错白屏
      const runWeekly = useCallback(async () => {
        setWeeklyBusy(true);
        setError('');
        try {
          const d = await api('/weekly', { method: 'POST', body: '{}' });
          setWeekly(d.markdown || '（周报为空）');
        } catch (err) {
          setError(err.message);
        } finally {
          setWeeklyBusy(false);
        }
      }, []);

      if (loading) return h('div', { className: 'ain-empty' }, '正在读取资讯缓存…');
      if (error) return h('div', { className: 'ain-wrap' },
        h('div', { className: 'ain-err' }, `加载失败：${error}`),
        h('button', { className: 'ain-btn', onClick: () => load(false) }, '重试'));

      const news = (data && data.news) || [];
      const trans = (data && data.news_translations) || {};
      const failures = (data && data.news_failures) || [];
      // 把组件的主题/关注词筛选状态注入模块级纯渲染函数
      const chipsOf = (it, gc) => enrichChips(it, gc, [activeTopic, setActiveTopic]);
      const watchOf = (it) => watchChips(it, [activeWatch, setActiveWatch]);

      // 已读：本地覆盖层优先，其次服务端下发的 it.read
      const isRead = (it) => (readMap[it.link] !== undefined
        ? readMap[it.link] : !!it.read);
      const unreadCount = news.filter((it) => !isRead(it)).length;

      // 点击卡片标记已读（乐观更新 + 后台落盘，失败不回滚只影响下次刷新）
      const markRead = (it) => {
        if (!it || !it.link || isRead(it)) return;
        setReadMap((m) => ({ ...m, [it.link]: true }));
        api('/read', { method: 'POST', body: JSON.stringify({ links: [it.link], read: true }) })
          .catch(() => { /* 网络抖动忽略，下次刷新以服务端为准 */ });
      };
      const markAllRead = async () => {
        const links = news.map((it) => it.link).filter(Boolean);
        setReadMap((m) => {
          const next = { ...m };
          for (const l of links) next[l] = true;
          return next;
        });
        try { await api('/read-all', { method: 'POST', body: '{}' }); }
        catch (_) { /* 忽略 */ }
      };

      // 搜索关键字：命中标题/摘要/中文译文任一即保留（大小写不敏感）
      const q = query.trim().toLowerCase();
      const matchQuery = (it) => {
        if (!q) return true;
        const tr = trans[it.link] || {};
        const zh = (tr.zh_title || '') + ' ' + (tr.zh_summary || '');
        return (it.title || '').toLowerCase().includes(q)
          || (it.summary || '').toLowerCase().includes(q)
          || zh.toLowerCase().includes(q);
      };
      const matchTopic = (it) => !activeTopic
        || (Array.isArray(it.topics) && it.topics.includes(activeTopic));
      const matchWatch = (it) => !activeWatch
        || (Array.isArray(it.watch_hits) && it.watch_hits.includes(activeWatch));
      // 分组为主：按激活标签过滤 + 领域主题筛选 + 时间范围筛选 + 搜索
      let filtered = (activeTag !== '全部')
        ? news.filter((it) => it.group === activeTag)
        : news;
      filtered = filtered
        .filter((it) => inTimeRange(it.published, timeRange))
        .filter(matchTopic)
        .filter(matchWatch)
        .filter(matchQuery)
        .filter((it) => !unreadOnly || !isRead(it));
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
      const searchedPool = pool.filter(matchQuery);
      const tagCounts = {};
      for (const it of searchedPool) tagCounts[it.group] = (tagCounts[it.group] || 0) + 1;
      const tagList = Object.entries(tagCounts).sort((a, b) => b[1] - a[1]);
      // 领域主题计数（跟随时间+搜索+当前分组，不含主题维度，避免选了主题后选项消失）
      const topicPool = searchedPool
        .filter((it) => activeTag === '全部' || it.group === activeTag);
      const topicCounts = {};
      for (const it of topicPool) {
        for (const t of (Array.isArray(it.topics) ? it.topics : [])) {
          topicCounts[t] = (topicCounts[t] || 0) + 1;
        }
      }
      const topicList = Object.entries(topicCounts).sort((a, b) => b[1] - a[1]);
      // 关键词关注计数（同主题口径：跟随时间+搜索+当前分组，不含关注词维度）
      const watchCounts = {};
      for (const it of topicPool) {
        for (const t of (Array.isArray(it.watch_hits) ? it.watch_hits : [])) {
          watchCounts[t] = (watchCounts[t] || 0) + 1;
        }
      }
      const watchList = Object.entries(watchCounts).sort((a, b) => b[1] - a[1]);
      // 分组按组内最新一条时间倒序输出（活跃分组排前面）
      const orderedGroups = Object.entries(groups)
        .map(([g, items]) => [g, items, items[0] && items[0].published ? new Date(items[0].published).getTime() : -1])
        .sort((a, b) => b[2] - a[2])
        .map(([g, items]) => [g, items]);

      // 采集进度百分比
      const pct = progress && progress.total
        ? Math.round((progress.done / progress.total) * 100)
        : 0;

      let __out;
      try {
      __out = h('div', { className: 'ain-wrap' },
        h('div', { className: 'ain-head' },
          h('h2', { className: 'ain-title', 'data-build': BUILD_TAG }, `AI 资讯 · ${BUILD_TAG}`),
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
          }, translating ? '翻译中…' : '自动翻译'),
          h('button', {
            className: 'ain-btn' + (unreadOnly ? ' primary' : ''),
            onClick: () => setUnreadOnly(!unreadOnly),
            title: '只显示还没点开过的资讯',
          }, `只看未读 ${unreadCount}`),
          unreadCount > 0 && h('button', {
            className: 'ain-btn',
            onClick: markAllRead,
            title: '把当前列表全部标记为已读',
          }, '全部已读'),
          h('button', {
            className: 'ain-btn', disabled: weeklyBusy || refreshing,
            onClick: () => runWeekly(),
            title: '把近 7 天资讯按主题汇总成 Markdown 周报（含关注词专区）',
          }, weeklyBusy ? '生成中…' : '📰 周报'),
          h('button', {
            className: 'ain-btn' + (proxyOpen ? ' primary' : '')
              + (proxyConf.enabled ? ' ain-proxy-on' : ''),
            onClick: () => setProxyOpen(!proxyOpen),
            title: proxyConf.enabled
              ? `当前通过代理 ${proxyConf.url} 拉取资讯，点击管理`
              : '配置代理：填入代理地址后所有信源与机翻请求都走代理',
          }, proxyConf.enabled ? '🌐 代理已开' : '🌐 网络'),
          h('button', {
            className: 'ain-btn', disabled: logBusy,
            onClick: openLogs,
            title: '查看前端错误日志（渲染崩溃、接口失败等，落盘在引擎 data/client-errors.log）',
          }, logBusy ? '读取中…' : '🐞 日志')),
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
        // 领域主题筛选（enrich.topics，跨信源的内容分类）
        !refreshing && topicList.length > 1 && h('div', { className: 'ain-topics-bar' },
          h('span', { className: 'ain-topics-label' }, '主题'),
          h('button', {
            className: 'ain-topic-chip' + (!activeTopic ? ' active' : ''),
            onClick: () => setActiveTopic(''),
          }, '不限'),
          topicList.slice(0, 24).map(([t, n]) => h('button', {
            key: t,
            className: 'ain-topic-chip' + (activeTopic === t ? ' active' : ''),
            title: `${t}（${n} 条）`,
            onClick: () => setActiveTopic(activeTopic === t ? '' : t),
          }, `${t} ${n}`))),
        // 关键词关注筛选（watch_hits，由 watch.json 配置驱动）
        !refreshing && (watchList.length > 0 || watchEditorOpen) && h('div', { className: 'ain-topics-bar ain-watch-bar' },
          h('span', { className: 'ain-topics-label' }, '关注'),
          watchList.map(([t, n]) => h('button', {
            key: t,
            className: 'ain-watch-chip-bar' + (activeWatch === t ? ' active' : ''),
            title: `只看命中关注词「${t}」的资讯（${n} 条）`,
            onClick: () => setActiveWatch(activeWatch === t ? '' : t),
          }, `🔖 ${t} ${n}`)),
          h('button', {
            key: 'manage',
            className: 'ain-watch-manage' + (watchEditorOpen ? ' active' : ''),
            title: '管理关注关键词',
            onClick: () => setWatchEditorOpen(!watchEditorOpen),
          }, watchEditorOpen ? '收起管理 ✕' : '管理 ⚙')),
        // 关注词管理面板：输入添加，列表可停用/启用/删除
        watchEditorOpen && h('div', { className: 'ain-watch-editor', key: 'watch-editor' },
          h('div', { className: 'ain-watch-add' },
            h('input', {
              value: watchInput,
              placeholder: '输入关键词，回车添加（英文按整词匹配，中文按子串）',
              maxLength: 64,
              disabled: watchBusy,
              onChange: (ev) => setWatchInput(ev.target.value),
              onKeyDown: (ev) => { if (ev.key === 'Enter') addWatch(); },
            }),
            h('button', {
              className: 'ain-btn primary',
              disabled: watchBusy || !watchInput.trim(),
              onClick: addWatch,
            }, '添加')),
          h('div', { className: 'ain-watch-conf-list' },
            watchConf.length === 0
              ? h('span', { className: 'ain-watch-empty' }, '还没有关注词，添加一个试试（如 mcp、免费额度）')
              : watchConf.map((k) => h('span', {
                  key: k.term,
                  className: 'ain-watch-conf' + (k.enabled === false ? ' off' : ''),
                },
                h('span', { className: 'ain-watch-conf-term', title: k.term }, `🔖 ${k.term}`),
                h('button', {
                  className: 'ain-watch-conf-btn',
                  disabled: watchBusy,
                  title: k.enabled === false ? '启用' : '停用',
                  onClick: () => watchOp('toggle', k.term, { enabled: k.enabled === false }),
                }, k.enabled === false ? '启用' : '停用'),
                h('button', {
                  className: 'ain-watch-conf-btn danger',
                  disabled: watchBusy,
                  title: '删除',
                  onClick: () => watchOp('remove', k.term),
                }, '删除'))))),
        // 代理配置面板：填地址 → 测试 → 启用，之后所有采集/机翻都走该出口
        proxyOpen && h('div', { className: 'ain-proxy-editor', key: 'proxy-editor' },
          h('div', { className: 'ain-proxy-row' },
            h('span', { className: 'ain-proxy-label' }, '代理地址'),
            h('input', {
              value: proxyInput,
              placeholder: 'http://127.0.0.1:7890（仅支持 http/https，不支持 socks）',
              disabled: proxyBusy,
              onChange: (ev) => setProxyInput(ev.target.value),
            })),
          h('div', { className: 'ain-proxy-row' },
            h('span', { className: 'ain-proxy-label' }, '直连白名单'),
            h('input', {
              value: proxyNoProxy,
              placeholder: '可选：不走代理的主机，逗号分隔，如 localhost,127.0.0.1',
              disabled: proxyBusy,
              onChange: (ev) => setProxyNoProxy(ev.target.value),
            })),
          h('div', { className: 'ain-proxy-actions' },
            h('button', {
              className: 'ain-btn', disabled: proxyBusy || !proxyInput.trim(),
              onClick: testProxyConn,
            }, proxyBusy ? '测试中…' : '测试连通'),
            h('button', {
              className: 'ain-btn primary',
              disabled: proxyBusy || (proxyInput.trim() === '' && !proxyConf.enabled),
              onClick: () => saveProxy(true),
            }, '启用并保存'),
            proxyConf.enabled && h('button', {
              className: 'ain-btn', disabled: proxyBusy,
              onClick: () => saveProxy(false),
            }, '关闭代理')),
          proxyTest && h('div', {
            className: 'ain-proxy-result ' + (proxyTest.ok ? 'ok' : 'fail'),
          }, proxyTest.ok
            ? `✅ 连通（${proxyTest.elapsed_ms} ms）${proxyTest.sample ? ` · ${proxyTest.sample}` : ''}`
            : `❌ ${proxyTest.error || '连接失败'}`),
          h('div', { className: 'ain-proxy-hint' },
            proxyConf.enabled
              ? `当前：已启用，出口 ${proxyConf.url}。若不生效请重启插件或点「在线刷新」重试。`
              : '当前：直连。启用后 RSS 采集、结构化采集器、信源发现与机翻全部走该代理。')),
        failures.length > 0 && h('div', { className: 'ain-err' },
          `失败信源 ${failures.length} 个：${failures.map((f) => f.name).join('、')}`),        news.length === 0 ? h('div', { className: 'ain-empty' }, '暂无资讯，点「在线刷新」采集')
          : filtered.length === 0 ? h('div', { className: 'ain-empty' },
              q ? `没有匹配「${query.trim()}」的资讯`
                : unreadOnly ? '没有未读资讯了，点「只看未读」切回来'
                : activeWatch ? `当前筛选下没有命中关注词「${activeWatch}」的资讯`
                : activeTopic ? `当前筛选下没有「${activeTopic}」主题的资讯`
                : '当前筛选条件下暂无资讯')
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
              const dupBadge = dupBadgeOf(it);
              const obtainTxt = (!isDeal && it.obtain && OBTAIN_LABEL[it.obtain])
                ? h('span', { className: 'ain-obtain' }, `· ${OBTAIN_LABEL[it.obtain]}`) : null;
              return h('a', {
                className: 'ain-item' + (isDeal ? ' deal' : '') + (isRead(it) ? ' ain-read' : ''),
                key: it.link,
                href: it.link, target: '_blank', rel: 'noreferrer',
                style: { '--group-color': gc },
                onClick: () => markRead(it),
              },
                h('div', { className: 'meta-row' },
                  h('div', { className: 'ain-avatar' }, isDeal ? '🎁' : srcInitial(it.source_name)),
                  h('span', { className: 'ain-src' }, it.source_name),
                  h('span', { className: 'ain-gtag' }, it.group),
                  isDeal && h('span', { className: 'ain-deal-badge' }, '情报'),
                  formBadge, dupBadge, obtainTxt,
                  h('span', { className: 'ain-time' }, fmtDate(it.published))),
                h('div', { className: 't' }, title),
                showOrig && h('div', { className: 'orig' }, it.title),
                summary && h('div', { className: 's' }, summary),
                isDeal && (it._tags || []).length > 0 && h('div', { className: 'ain-deal-tags' },
                  it._tags.map(t => h('span', { key: t }, t))),
                ...(isDeal ? [] : chipsOf(it, gc)),
                ...watchOf(it));
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
                const dupBadge = dupBadgeOf(it);
                const obtainTxt = (!isDeal && it.obtain && OBTAIN_LABEL[it.obtain])
                  ? h('span', { className: 'ain-obtain' }, `· ${OBTAIN_LABEL[it.obtain]}`) : null;
                return h('a', {
                  className: 'ain-item' + (isDeal ? ' deal' : '') + (isRead(it) ? ' ain-read' : ''),
                  key: it.link,
                  href: it.link, target: '_blank', rel: 'noreferrer',
                  style: { '--group-color': gc },
                  onClick: () => markRead(it),
                },
                  h('div', { className: 'meta-row' },
                    h('div', { className: 'ain-avatar' }, isDeal ? '🎁' : srcInitial(it.source_name)),
                    h('span', { className: 'ain-src' }, it.source_name),
                    h('span', { className: 'ain-gtag' }, it.group),
                    isDeal && h('span', { className: 'ain-deal-badge' }, '情报'),
                    formBadge, dupBadge, obtainTxt,
                    h('span', { className: 'ain-time' }, fmtDate(it.published))),
                  h('div', { className: 't' }, title),
                  showOrig && h('div', { className: 'orig' }, it.title),
                  summary && h('div', { className: 's' }, summary),
                  isDeal && (it._tags || []).length > 0 && h('div', { className: 'ain-deal-tags' },
                    it._tags.map(t => h('span', { key: t }, t))),
                  ...(isDeal ? [] : chipsOf(it, gc)),
                  ...watchOf(it));
              })))),
        // 周报弹窗：轻量 Markdown 渲染（标题/列表/引用/表格/代码，够看即可）
        weekly && h('div', { className: 'ain-modal-mask', onClick: () => setWeekly(null) },
          h('div', { className: 'ain-modal', onClick: (e) => e.stopPropagation() },
            h('div', { className: 'ain-modal-head' },
              h('strong', null, 'AI 资讯周报（近 7 天）'),
              h('div', { className: 'ain-modal-actions' },
                h('button', {
                  className: 'ain-btn',
                  onClick: () => {
                    const blob = new Blob([weekly], { type: 'text/markdown;charset=utf-8' });
                    const a = document.createElement('a');
                    a.href = URL.createObjectURL(blob);
                    a.download = `weekly-${new Date().toISOString().slice(0, 10)}.md`;
                    a.click();
                    URL.revokeObjectURL(a.href);
                  },
                }, '下载 .md'),
                h('button', { className: 'ain-btn primary', onClick: () => setWeekly(null) }, '关闭'))),
            h('div', { className: 'ain-modal-body', innerHTML: renderMd(weekly) }))),

        // 错误日志弹窗：倒序展示，error 红、warn 橙，可复制可清空
        logOpen && h('div', { className: 'ain-modal-mask', onClick: () => setLogOpen(false) },
          h('div', { className: 'ain-modal', onClick: (e) => e.stopPropagation() },
            h('div', { className: 'ain-modal-head' },
              h('strong', null, `前端错误日志（${logEntries.length} 条，最多保留 500 条）`),
              h('div', { className: 'ain-modal-actions' },
                h('button', {
                  className: 'ain-btn',
                  onClick: () => {
                    const text = logEntries.map((e) =>
                      `${e.ts} [${e.level}] ${e.message}${e.extra ? `\n    ${e.extra}` : ''}`).join('\n');
                    navigator.clipboard?.writeText(text).catch(() => {});
                  },
                }, '复制全部'),
                h('button', { className: 'ain-btn', onClick: clearLogs }, '清空'),
                h('button', { className: 'ain-btn primary', onClick: () => setLogOpen(false) }, '关闭'))),
            h('div', { className: 'ain-modal-body' },
              logEntries.length === 0
                ? h('div', { className: 'ain-empty' }, '暂无错误日志 🎉')
                : h('div', { className: 'ain-log-list' },
                  [...logEntries].reverse().map((e, i) =>
                    h('div', { key: i, className: `ain-log-line ain-log-${e.level || 'info'}` },
                      h('div', { className: 'ain-log-head' },
                        h('span', { className: 'ain-log-level' }, e.level || 'info'),
                        h('span', { className: 'ain-log-ts' }, (e.ts || '').replace('T', ' ').slice(0, 19))),
                      h('div', { className: 'ain-log-msg' }, e.message),
                      e.extra && h('pre', { className: 'ain-log-extra' }, e.extra)))))));
      } catch (e) {
        __out = h('div', { className: 'ain-wrap' },
          h('div', { className: 'ain-err', style: { whiteSpace: 'pre-wrap' } },
            '资讯渲染异常：' + ((e && e.message) || e)));
      }
      if (!__out) {
        __out = h('div', { className: 'ain-wrap' },
          h('div', { className: 'ain-err' }, '资讯渲染返回空值：' + String(__out)));
      }
      return __out;
    }

    // 极简单列 Markdown → HTML（仅周报用，输入来自本地生成的可信文本，仍做转义）
    function renderMd(md) {
      const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
      const inline = (s) => esc(s)
        .replace(/`([^`]+)`/g, '<code>$1</code>')
        .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>')
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
      const lines = md.split('\n');
      const html = [];
      let inUl = false, inTable = false;
      const closeUl = () => { if (inUl) { html.push('</ul>'); inUl = false; } };
      const closeTable = () => { if (inTable) { html.push('</table>'); inTable = false; } };
      for (const raw of lines) {
        const line = raw.trimEnd();
        if (!line.trim()) { closeUl(); closeTable(); continue; }
        if (/^###\s/.test(line)) { closeUl(); closeTable(); html.push(`<h4>${inline(line.slice(4))}</h4>`); }
        else if (/^##\s/.test(line)) { closeUl(); closeTable(); html.push(`<h3>${inline(line.slice(3))}</h3>`); }
        else if (/^#\s/.test(line)) { closeUl(); closeTable(); html.push(`<h2>${inline(line.slice(2))}</h2>`); }
        else if (/^>\s?/.test(line)) { closeUl(); closeTable(); html.push(`<blockquote>${inline(line.replace(/^>\s?/, ''))}</blockquote>`); }
        else if (/^\|\s/.test(line)) {
          if (/^[\s|:-]+$/.test(line.replace(/\|/g, '|').trim())) continue; // 分隔行
          if (!inTable) { html.push('<table>'); inTable = true; }
          const cells = line.split('|').slice(1, -1).map((c) => `<td>${inline(c.trim())}</td>`).join('');
          html.push(`<tr>${cells}</tr>`);
        }
        else if (/^[-*]\s/.test(line)) { closeTable(); if (!inUl) { html.push('<ul>'); inUl = true; } html.push(`<li>${inline(line.slice(2))}</li>`); }
        else { closeUl(); closeTable(); html.push(`<p>${inline(line)}</p>`); }
      }
      closeUl(); closeTable();
      return html.join('\n');
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
      return h(ErrorBoundary, null,
        h(React.Fragment, null,
          h('div', { className: 'ain-tabs' },
            h('button', { className: `ain-tab ${tab === 'news' ? 'active' : ''}`, onClick: () => setTab('news') }, '资讯'),
            h('button', { className: `ain-tab ${tab === 'discover' ? 'active' : ''}`, onClick: () => setTab('discover') }, '发现'),
            h('button', { className: `ain-tab ${tab === 'sources' ? 'active' : ''}`, onClick: () => setTab('sources') }, '信源维护')),
          tab === 'news' ? h(NewsPanel)
            : tab === 'discover' ? h(DiscoverPanel) : h(SourcePanel)));
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
