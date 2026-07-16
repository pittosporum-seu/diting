/**
 * 谛听 · v0.7.2 — 共享核心（无循环依赖）
 * 被 app.js、router.js、pages/*.js 共同引用
 */
import { cacheManager } from './cache.js';
import { api } from './api.js';
import { ui } from './ui.js';

/* ── 全局状态 ── */
export const state = {
  currentPage: 'dashboard',
  currentStock: null,
  dashboardData: null,
  watchlist: [],
  loading: false,
  error: null,
};

export function updateState(partial) {
  Object.assign(state, partial);
}

/* ── 状态提示条 ── */
let _statusTimer = null;
export function showStatus(msg) {
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

/* ── 骨架屏 ── */
export function _renderSkeleton(blocks) {
  document.getElementById('app-root').innerHTML = blocks;
}

/* ── 通用 stale-while-revalidate ── */
function _showRefreshBadge() {
  const el = document.createElement('div');
  el.className = 'refresh-badge';
  el.innerHTML = '⟳';
  el.title = '正在刷新数据…';
  document.body.appendChild(el);
  setTimeout(() => { if (el.parentNode) el.remove(); }, 10000);
  return el;
}

function _showErrorFallback(msg) {
  const root = document.getElementById('app-root');
  root.innerHTML = ui.errorCard('数据加载失败', msg || '请检查网络后重试') +
    `<div style="text-align:center;margin-top:12px"><button onclick="location.reload()" style="padding:8px 20px;background:var(--color-primary);color:#fff;border:none;border-radius:8px;cursor:pointer;font-size:14px">🔄 重试</button></div>`;
  showStatus('');
}

export async function _loadWithCache(key, skeletonFn, apiFn, renderFn, onErrorFn) {
  const cached = cacheManager.getStale(key);
  const isFresh = cacheManager.isFresh(key);
  let refreshBadge = null;

  if (cached) {
    renderFn(cached, true);
    if (!isFresh) refreshBadge = _showRefreshBadge();
  } else {
    skeletonFn();
  }

  let attempts = 0, success = false;
  while (attempts < 2 && !success) {
    attempts++;
    try {
      const res = await apiFn();
      if (res.ok) {
        const enriched = { ...res.data };
        if (res.server_time) enriched._server_time = res.server_time;
        if (res.cache_state) enriched._cache_state = res.cache_state;
        cacheManager.set(key, enriched);
        renderFn(enriched, false);
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
  cacheManager.prune();
}

/* ── HTML 转义 ── */
function _esc(s) { const el = document.createElement('span'); el.textContent = s; return el.innerHTML; }

/* ── 股票列表缓存 ── */
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
        dropdown.classList.remove('active'); dropdown.innerHTML = '';
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
          _renderMatches(res.data.results.slice(0, 8)); return;
        }
      } catch (_) {}
      dropdown.classList.remove('active'); dropdown.innerHTML = '';
    }, 200);
  });

  document.addEventListener('click', (e) => { if (!e.target.closest(parentSelector)) dropdown.classList.remove('active'); });
  inputEl.addEventListener('keydown', (e) => { if (e.key === 'Escape') dropdown.classList.remove('active'); });
}
