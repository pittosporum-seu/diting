/**
 * 路由 — 谛听 v0.7.1
 * URL hash → page handler 映射 + 页面切换逻辑
 */
import { renderDashboard } from './pages/dashboard.js';
import { renderStockSearch, renderStock } from './pages/stock.js';
import { renderOpportunities } from './pages/opportunities.js';
import { renderWatchlist } from './pages/watchlist.js';
import { renderSettings } from './pages/settings.js';
import { state, updateState, showStatus, disposePage } from './core.js';

/* ── 路由表 ── */
const ROUTE_MAP = {
  'dashboard':     { re: /^#\/dashboard$/,                     render: renderDashboard },
  'stock_landing': { re: /^#\/stock\/?$/,                      render: renderStockSearch },
  'stock':         { re: /^#\/stock\/(\d{6})$/,                render: (m) => renderStock(m[1]) },
  'opportunities': { re: /^#\/opportunities$/,                 render: renderOpportunities },
  'watchlist':     { re: /^#\/watchlist$/,                     render: renderWatchlist },
  'settings':      { re: /^#\/settings$/,                      render: renderSettings },
};

function resolveRoute(hash) {
  if (!hash || hash === '#' || hash === '#/') {
    return ['dashboard', () => renderDashboard()];
  }
  for (const [name, { re, render }] of Object.entries(ROUTE_MAP)) {
    const m = hash.match(re);
    if (m) return [name, () => render(m)];
  }
  return ['404', () => render404()];
}

/* ── 导航 highlighter ── */
function setActiveNav(name) {
  document.querySelectorAll('#navbar .nav-link').forEach(el => {
    const route = el.dataset.route;
    const active = route === name || (route === 'stock_landing' && name === 'stock');
    el.classList.toggle('active', active);
  });
}

/* ── 页面渲染入口 ── */
function renderPage() {
  const hash = window.location.hash;
  const [name, fn] = resolveRoute(hash);
  updateState({ currentPage: name, currentStock: name === 'stock' ? state.currentStock : null });
  setActiveNav(name);
  disposePage();
  showStatus("");

  const root = document.getElementById('app-root');
  root.innerHTML = '';
  fn();

  const titleMap = {
    'dashboard': '谛听 · A股多模型AI投资分析',
    'stock_landing': '个股分析 - 谛听',
    'stock': `${state.currentStock || '个股分析'} - 谛听`,
    'opportunities': '选股机会 - 谛听',
    'watchlist': '自选股 - 谛听',
    'settings': '设置 - 谛听',
  };
  document.title = titleMap[name] || '谛听';

  window.scrollTo(0, 0);
}

/* ── 404 页面 ── */
function render404() {
  const root = document.getElementById('app-root');
  root.innerHTML = `
    <div class="page-404">
      <div class="icon">🔍</div>
      <h2>页面未找到</h2>
      <p><a href="#/dashboard">← 返回仪表盘</a></p>
    </div>
  `;
  console.log('[谛听] 404 页面加载完成');
}

export { ROUTE_MAP, resolveRoute, setActiveNav, renderPage, render404 };
window.__loaded = window.__loaded || []; window.__loaded.push('router');
