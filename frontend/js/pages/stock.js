/** 个股分析页面 — 谛听 v0.7.2 (骨架，完整功能待恢复) */
import { api } from '../api.js';
import { cacheManager } from '../cache.js';
import { charts } from '../charts.js';
import { ui, _fmt, _pctSigned, _dataTimeBar, _esc } from '../ui.js';
import { state, updateState, showStatus, _renderSkeleton, _loadWithCache, _getStockList, _initSearchSuggestions } from '../core.js';
window.__loaded = window.__loaded || []; window.__loaded.push('pages/stock');

export function renderStockSearch() {
  const root = document.getElementById('app-root');
  root.innerHTML = '<h1 class="page-title">个股分析</h1><div class="search-bar"><input id="stock-search" type="text" placeholder="输入代码或名称" autocomplete="off" style="flex:1;padding:10px 14px;border:1px solid var(--border-color);border-radius:8px;font-size:15px;outline:none"><button id="stock-search-btn" style="padding:10px 24px;background:var(--color-primary);color:#fff;border:none;border-radius:8px;cursor:pointer;font-size:15px;white-space:nowrap">搜索</button></div>';
  _bindSearch();
}

export async function renderStock(code) {
  const root = document.getElementById('app-root');
  _renderSkeleton(ui.skeletonBlock('400px'));
  await _loadWithCache('stock_'+code,
    () => { showStatus('📡 正在获取数据…'); },
    () => api.stock(code),
    (data, fromCache) => {
      if (fromCache) showStatus('');
      root.innerHTML = '<p style="text-align:center;padding:40px">' + (data.name || code) + ' · 加载完成</p>';
    }
  );
}

async function _bindSearch() {
  const input = document.getElementById('stock-search');
  const btn = document.getElementById('stock-search-btn');
  if (!input || !btn) return;
  _initSearchSuggestions(input, { onSelect: (code) => { window.location.hash = '#/stock/' + code; } });
  btn.addEventListener('click', async () => {
    const v = input.value.trim();
    if (!v) return;
    if (/^\d{6}$/.test(v)) { window.location.hash = '#/stock/' + v; return; }
    const stockList = await _getStockList();
    const match = stockList.find(s => String(s.code||'').includes(v) || String(s.name||'').includes(v));
    if (match) { window.location.hash = '#/stock/' + match.code; return; }
    const res = await api.searchStock(v);
    if (res.ok && res.data?.results?.length > 0) { window.location.hash = '#/stock/' + res.data.results[0].code; }
  });
}
