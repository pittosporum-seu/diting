/**
 * 谛听 · v0.7.1 — SPA 入口 + 共享基础设施
 * 纯 JS，无依赖框架。
 * v0.7.1 P1-4: 前端拆分为多文件模块
 *   - router.js: 路由表 + 页面切换
 *   - ui.js: UI 组件库 + 辅助函数
 *   - pages/*.js: 各页面渲染逻辑
 *   - cache.js: localStorage 缓存管理（P1-2）
 *   - api.js: 后端 API 封装（P1-2）
 *   - charts.js: ECharts 图表封装
 */
import { api } from './api.js';
import { cacheManager } from './cache.js';
import { charts } from './charts.js';
import { ui } from './ui.js';
import { renderPage } from './router.js';

/* ── 全局状态 ── */
const state = {
  currentPage: 'dashboard',
  currentStock: null,
  dashboardData: null,
  watchlist: [],
  loading: false,
  error: null,
};

function updateState(partial) {
  Object.assign(state, partial);
}

/* ── 图表清理 ── */
function disposePage() {
  ['kline-chart', 'volume-chart', 'engine-bars', 'vmd-gauge', 'portfolio-pie'].forEach(charts.dispose);
}

/* ── 状态提示条 ── */
let _statusTimer = null;

function showStatus(msg) {
  const existing = document.getElementById('status-bar');
  if (existing) existing.remove();

  if (_statusTimer) clearTimeout(_statusTimer);

  if (!msg) return;

  const bar = document.createElement('div');
  bar.id = 'status-bar';
  bar.style.cssText = `
    position: fixed; top: 60px; left: 50%; transform: translateX(-50%);
    background: #eef2ff; color: #4f46e5; padding: 8px 20px;
    border-radius: 8px; font-size: 14px; z-index: 1000;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    transition: opacity 0.3s;
  `;
  bar.textContent = msg;
  document.body.appendChild(bar);

  _statusTimer = setTimeout(() => {
    bar.style.opacity = '0';
    setTimeout(() => bar.remove(), 300);
  }, 5000);
}

/* ── 骨架屏渲染 ── */
function _renderSkeleton(blocks) {
  const root = document.getElementById('app-root');
  root.innerHTML = blocks;
}

/* ── 通用 stale-while-revalidate 加载 ── */
async function _loadWithCache(key, skeletonFn, apiFn, renderFn, onErrorFn) {
  // Phase 1: 缓存优先 (use getStale for wider grace window)
  const cached = cacheManager.getStale(key);
  const isFresh = cacheManager.isFresh(key);
  let refreshBadge = null;

  if (cached) {
    const stale = !isFresh;
    renderFn(cached, /* fromCache= */ true);
    if (stale) {
      refreshBadge = _showRefreshBadge();
    }
  } else {
    skeletonFn();
  }

  // Phase 2: 后台拉新（失败重试 1 次）
  let attempts = 0;
  let success = false;
  while (attempts < 2 && !success) {
    attempts++;
    try {
      const res = await apiFn();
      if (res.ok) {
        const enriched = { ...res.data };
        if (res.server_time) enriched._server_time = res.server_time;
        if (res.cache_state) enriched._cache_state = res.cache_state;
        cacheManager.set(key, enriched);
        renderFn(enriched, /* fromCache= */ false);
        if (refreshBadge) refreshBadge.remove();
        success = true;
      } else if (!cached && attempts >= 2) {
        if (onErrorFn) onErrorFn(res.error || '数据加载失败');
        else _showErrorFallback(res.error || '数据加载失败');
      }
    } catch (_) {
      if (!cached && attempts >= 2) {
        if (onErrorFn) onErrorFn('网络连接失败');
        else _showErrorFallback('网络连接失败');
      }
    }
  }

  cacheManager.prune();  // periodic cleanup
}

/** Show a subtle pulsing dot in the top-right corner indicating background refresh. */
function _showRefreshBadge() {
  const el = document.createElement('div');
  el.className = 'refresh-badge';
  el.innerHTML = '⟳';
  el.title = '正在刷新数据…';
  document.body.appendChild(el);
  // Auto-remove after 10s as safety net
  setTimeout(() => { if (el.parentNode) el.remove(); }, 10000);
  return el;
}

function _showErrorFallback(msg) {
  const root = document.getElementById('app-root');
  root.innerHTML = ui.errorCard('数据加载失败', msg || '请检查网络后重试') +
    `<div style="text-align:center;margin-top:12px"><button onclick="location.reload()" style="padding:8px 20px;background:var(--color-primary);color:#fff;border:none;border-radius:8px;cursor:pointer;font-size:14px">🔄 重试</button></div>`;
  showStatus('');
}

/* ── 股票列表本地缓存 ── */
let _stockListCache = null;

async function _getStockList() {
  if (_stockListCache) return _stockListCache;
  // Try localStorage first
  const cached = cacheManager.get('stock_list');
  if (cached) {
    _stockListCache = cached;
    return _stockListCache;
  }
  // Fetch from backend
  try {
    const res = await api.stockList();
    if (res.ok && Array.isArray(res.data)) {
      _stockListCache = res.data;
      cacheManager.set('stock_list', res.data);
      return _stockListCache;
    }
  } catch (_) { /* fall through */ }
  _stockListCache = [];
  return _stockListCache;
}

/* ── 搜索框：下拉建议 + 防抖 ── */
let _searchDebounceTimer = null;

function _initSearchSuggestions(inputEl, opts = {}) {
  const parentSelector = opts.parentSelector || '.search-bar';
  const onSelect = opts.onSelect || null;

  // Remove any existing dropdown
  const existing = inputEl.parentNode.querySelector('.search-dropdown');
  if (existing) existing.remove();

  const dropdown = document.createElement('div');
  dropdown.className = 'search-dropdown';
  inputEl.parentNode.appendChild(dropdown);

  const _renderMatches = (matches) => {
    dropdown.innerHTML = matches.map(s => `
      <div class="search-item" data-code="${_esc(String(s.code))}" data-name="${_esc(String(s.name || ''))}">
        <span class="search-code">${_esc(String(s.code))}</span>
        <span class="search-name">${_esc(String(s.name || ''))}</span>
      </div>
    `).join('');
    dropdown.classList.add('active');

    dropdown.querySelectorAll('.search-item').forEach(el => {
      el.addEventListener('click', () => {
        const code = el.dataset.code;
        const name = el.dataset.name;
        if (onSelect) {
          onSelect(code, name);
        } else {
          inputEl.value = code;
          inputEl.dispatchEvent(new Event('change', { bubbles: true }));
        }
        dropdown.classList.remove('active');
        dropdown.innerHTML = '';
      });
    });
  };

  inputEl.addEventListener('input', () => {
    clearTimeout(_searchDebounceTimer);
    const q = inputEl.value.trim();

    if (q.length < 1) {
      dropdown.classList.remove('active');
      dropdown.innerHTML = '';
      return;
    }

    _searchDebounceTimer = setTimeout(async () => {
      // Try local stock list first (faster, no network)
      const stockList = await _getStockList();
      if (stockList.length > 0) {
        const ql = q.toLowerCase();
        const matches = stockList.filter(s => {
          const code = String(s.code || '');
          const name = String(s.name || '');
          const pinyin = String(s.pinyin || '');
          return code.includes(q) || name.includes(ql) || name.includes(q)
            || pinyin.includes(ql);
        }).slice(0, 8);

        if (matches.length > 0) {
          _renderMatches(matches);
          return;
        }
      }

      // Fallback: server-side search
      try {
        const res = await api.searchStock(q);
        if (res.ok && Array.isArray(res.data?.results) && res.data.results.length > 0) {
          _renderMatches(res.data.results.slice(0, 8));
          return;
        }
      } catch (_) { /* ignore */ }

      dropdown.classList.remove('active');
      dropdown.innerHTML = '';
    }, 200);
  });

  // Close dropdown on outside click
  document.addEventListener('click', (e) => {
    if (!e.target.closest(parentSelector)) {
      dropdown.classList.remove('active');
    }
  });

  // Close dropdown on Escape
  inputEl.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      dropdown.classList.remove('active');
    }
  });
}

/* ── 简单的 HTML 转义 ── */
function _esc(s) {
  const el = document.createElement('span');
  el.textContent = s;
  return el.innerHTML;
}

/* ── watchlist change event bus ── */
window.addEventListener('diting:watchlist_changed', () => {
  cacheManager.remove('dashboard');
  cacheManager.remove('opportunities');
  if (state.currentPage === 'dashboard') {
    import('./pages/dashboard.js').then(m => m.renderDashboard());
  } else if (state.currentPage === 'opportunities') {
    import('./pages/opportunities.js').then(m => m.renderOpportunities());
  }
});

/* ── 启动 ── */
window.addEventListener('hashchange', renderPage);
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', renderPage);
} else {
  // DOM 已就绪（模块脚本是 deferred，可能晚于 DOMContentLoaded）
  renderPage();
}

/* ── 导出供 pages/*.js 使用 ── */
export {
  state,
  updateState,
  disposePage,
  showStatus,
  _renderSkeleton,
  _loadWithCache,
  _showRefreshBadge,
  _showErrorFallback,
  _getStockList,
  _initSearchSuggestions,
  _esc,
};
