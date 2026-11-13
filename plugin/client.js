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
.ain-group h3 { font-size:13px; margin:0 0 8px; color:var(--dsw-alias-label-secondary); font-weight:600; }
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

      useEffect(() => { load(false); }, [load]);

      if (loading) return h('div', { className: 'ain-empty' }, '正在读取资讯缓存…');
      if (error) return h('div', { className: 'ain-wrap' },
        h('div', { className: 'ain-err' }, `加载失败：${error}`),
        h('button', { className: 'ain-btn', onClick: () => load(false) }, '重试'));

      const news = (data && data.news) || [];
      const trans = (data && data.news_translations) || {};
      const groups = {};
      for (const it of news) (groups[it.group] = groups[it.group] || []).push(it);
      const failures = (data && data.news_failures) || [];

      return h('div', { className: 'ain-wrap' },
        h('div', { className: 'ain-head' },
          h('h2', { className: 'ain-title' }, 'AI 资讯'),
          h('span', { className: 'ain-meta', style: { margin: 0 } }, `${news.length} 条`),
          h('button', {
            className: 'ain-btn primary', disabled: refreshing,
            onClick: () => load(true),
          }, refreshing ? '采集中…' : '在线刷新')),
        data && data.generated_at && h('div', { className: 'ain-meta' },
          `更新于 ${new Date(data.generated_at).toLocaleString()}`),
        failures.length > 0 && h('div', { className: 'ain-err' },
          `失败信源 ${failures.length} 个：${failures.map((f) => f.name).join('、')}`),
        news.length === 0 ? h('div', { className: 'ain-empty' }, '暂无资讯，点「在线刷新」采集')
          : Object.entries(groups).map(([gname, items]) =>
            h('div', { className: 'ain-group', key: gname },
              h('h3', null, `${gname}（${items.length}）`),
              items.map((it) => {
                const tr = trans[it.link] || {};
                const title = tr.zh_title || it.title;
                const showOrig = tr.zh_title && tr.zh_title !== it.title;
                const summary = tr.zh_summary || it.summary || '';
                return h('a', {
                  className: 'ain-item', key: it.link,
                  href: it.link, target: '_blank', rel: 'noreferrer',
                },
                  h('div', { className: 't' }, title),
                  showOrig && h('div', { className: 'orig' }, it.title),
                  summary && h('div', { className: 's' }, summary),
                  h('div', { className: 'm' },
                    h('span', null, it.source_name),
                    h('span', null, fmtDate(it.published))));
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

    // ---------- 主面板（含 tab 切换）----------
    function Panel() {
      const [tab, setTab] = useState('news');
      return h(React.Fragment, null,
        h('div', { className: 'ain-tabs' },
          h('button', { className: `ain-tab ${tab === 'news' ? 'active' : ''}`, onClick: () => setTab('news') }, '资讯'),
          h('button', { className: `ain-tab ${tab === 'sources' ? 'active' : ''}`, onClick: () => setTab('sources') }, '信源维护')),
        tab === 'news' ? h(NewsPanel) : h(SourcePanel));
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
