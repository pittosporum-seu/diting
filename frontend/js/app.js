/**
 * 谛听 · v0.7.2 — SPA 入口
 * 启动逻辑 + 事件处理。共享代码在 core.js。
 */
import { state, showStatus, _loadWithCache, disposePage } from './core.js?v=0.7.7';
import { cacheManager } from './cache.js?v=0.7.7';
import { renderPage } from './router.js?v=0.7.7';

// 注意: disposePage 已迁至 core.js，app.js 不再被 router.js 引用
// → app.js → router.js → pages → core.js ✓ (无循环)

/* ── watchlist 变更事件 ── */
window.addEventListener('diting:watchlist_changed', () => {
  cacheManager.remove('dashboard');
  cacheManager.remove('opportunities');
  if (state.currentPage === 'dashboard') {
    import('./pages/dashboard.js?v=0.7.7').then(m => m.renderDashboard());
  } else if (state.currentPage === 'opportunities') {
    import('./pages/opportunities.js?v=0.7.7').then(m => m.renderOpportunities());
  }
});

/* ── 启动 ── */
window.addEventListener('hashchange', renderPage);
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', renderPage);
} else {
  try {
    renderPage();
    document.getElementById('app-root').insertAdjacentHTML('beforeend', 
      '<p style="color:green;text-align:center">✓ renderPage called</p>');
  } catch(e) {
    document.getElementById('app-root').innerHTML = 
      '<p style="color:red;text-align:center;padding:40px">✗ 启动失败: ' + e.message + 
      '<br><small>' + e.stack + '</small></p>';
  }
}
