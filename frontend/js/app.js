/**
 * 谛听 · v0.7.2 — SPA 入口
 * 启动逻辑 + 事件处理，共享代码在 core.js
 */
import { state, updateState, showStatus, _renderSkeleton, _loadWithCache } from './core.js';
import { cacheManager } from './cache.js';
import { api } from './api.js';
import { charts } from './charts.js';
import { renderPage } from './router.js';

/* ── 图表清理 ── */
export function disposePage() {
  ['kline-chart', 'volume-chart', 'engine-bars', 'vmd-gauge', 'portfolio-pie'].forEach(charts.dispose);
}

/* ── 股票列表本地缓存 ── */
let _stockListCache = null;
export async function _getStockList() {
  if (_stockListCache) return _stockListCache;
  const cached = cacheManager.get('stock_list');
  if (cached) { _stockListCache = cached; return _stockListCache; }
  try {
    const res = await api.stockList();
    if (res.ok && Array.isArray(res.data)) {
      _stockListCache = res.data;
      cacheManager.set('stock_list', res.data);
      return _stockListCache;
    }
  } catch (_) {}
  _stockListCache = [];
  return _stockListCache;
}

/* ── 搜索建议 ── */
let _searchDebounceTimer = null;
function _esc(s) { const el = document.createElement('span'); el.textContent = s; return el.innerHTML; }

export function _initSearchSuggestions(inputEl, opts = {}) {
  const parentSelector = opts.parentSelector || '.search-bar';
  const onSelect = opts.onSelect || null;
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
        if (onSelect) onSelect(code, el.dataset.name);
        else { inputEl.value = code; inputEl.dispatchEvent(new Event('change', { bubbles: true })); }
        dropdown.classList.remove('active');
        dropdown.innerHTML = '';
      });
    });
  };

  inputEl.addEventListener('input', () => {
    clearTimeout(_searchDebounceTimer);
    const q = inputEl.value.trim();
    if (q.length < 1) { dropdown.classList.remove('active'); dropdown.innerHTML = ''; return; }
    _searchDebounceTimer = setTimeout(async () => {
      const stockList = await _getStockList();
      if (stockList.length > 0) {
        const ql = q.toLowerCase();
        const matches = stockList.filter(s => {
          const code = String(s.code || ''), name = String(s.name || '');
          return code.includes(q) || name.includes(ql) || name.includes(q) || String(s.pinyin || '').includes(ql);
        }).slice(0, 8);
        if (matches.length > 0) { _renderMatches(matches); return; }
      }
      try {
        const res = await api.searchStock(q);
        if (res.ok && Array.isArray(res.data?.results) && res.data.results.length > 0) {
          _renderMatches(res.data.results.slice(0, 8));
          return;
        }
      } catch (_) {}
      dropdown.classList.remove('active'); dropdown.innerHTML = '';
    }, 200);
  });

  document.addEventListener('click', (e) => { if (!e.target.closest(parentSelector)) dropdown.classList.remove('active'); });
  inputEl.addEventListener('keydown', (e) => { if (e.key === 'Escape') dropdown.classList.remove('active'); });
}

/* ── watchlist 变更事件 ── */
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
  renderPage();
}
