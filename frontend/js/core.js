/**
 * 谛听 · v0.7.2 — 共享核心（无循环依赖）
 * 被 app.js、router.js、pages/*.js 共同引用
 */
import { cacheManager } from './cache.js';
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
