/**
 * 选股机会页面 — 谛听 v0.7.1
 * 自选股机会 + 全市场热点扫描 /w 统计卡片
 */
import { api } from '../api.js?v=0.7.7';
import {
  ui,
  _ratingTag, _fmt, _pctSigned, _dataTimeBar, _esc,
} from '../ui.js?v=0.7.7';
import {
  showStatus, _renderSkeleton, _loadWithCache,
} from '../core.js?v=0.7.7';

export async function renderOpportunities() {
  const skeleton = () => {
    showStatus("📡 正在获取数据…");
    _renderSkeleton(`
      ${ui.statGrid(4)}${ui.skeletonCard().repeat(4)}</div>
      ${ui.skeletonBlock('300px')}
      ${ui.skeletonBlock('300px')}
    `);
  };

  const render = (oppData, fromCache) => {
    if (fromCache) console.log('[谛听] 选股机会 缓存命中');

    const root = document.getElementById('app-root');
    const fromWatchlist = oppData?.from_watchlist || [];
    const fromMarket = oppData?.from_market || [];

    // Helper: build table rows from items
    const _buildTableRows = (items) => {
      const rows = [];
      for (const o of items) {
        const tag = _ratingTag(o.score);
        const pctColor = (o.change_pct ?? 0) >= 0 ? 'color:var(--color-buy)' : 'color:var(--color-avoid)';
        const pctStr = _pctSigned(o.change_pct);
        rows.push({
          code: o.code,
          cells: [
            { html: `<span style="font-weight:600">${_esc(o.code)}</span>`, align: 'left' },
            { html: _esc(o.name || o.code), align: 'left' },
            { html: _fmt(o.score, 1), align: 'right' },
            { html: tag, align: 'center' },
            { html: _fmt(o.price, 2), align: 'right' },
            { html: `<span style="${pctColor}">${pctStr}</span>`, align: 'right' },
          ],
        });
      }
      return rows;
    };

    const headers = [
      { label: '代码', align: 'left' },
      { label: '名称', align: 'left' },
      { label: '评分', align: 'right' },
      { label: '信号', align: 'center' },
      { label: '价格', align: 'right' },
      { label: '涨跌', align: 'right' },
    ];

    const watchlistRows = _buildTableRows(fromWatchlist);
    const marketRows = _buildTableRows(fromMarket);

    // 深度分析进度指示器
    const prog = oppData?.deep_analysis_progress;
    let progressSection = '';
    if (prog && prog.status === 'running' && prog.total > 0) {
      const pctVal = Math.round((prog.done / prog.total) * 100);
      progressSection = `
        <div class="card" style="margin-top:12px;padding:12px 16px">
          <div style="display:flex;justify-content:space-between;font-size:13px;color:var(--text-secondary);margin-bottom:6px">
            <span>🧠 正在对候选股跑全量分析${prog.current_code ? '（' + _esc(prog.current_code) + '）' : ''}</span>
            <span>${prog.done} / ${prog.total}</span>
          </div>
          <div style="height:6px;background:var(--border-color);border-radius:3px;overflow:hidden">
            <div style="width:${pctVal}%;height:100%;background:var(--color-primary);transition:width .3s"></div>
          </div>
        </div>`;
    }

    let watchlistSection = '';
    if (fromWatchlist.length > 0) {
      watchlistSection = `
        <div class="card-title" style="margin-top:20px">📋 自选股机会 (${fromWatchlist.length})</div>
        ${ui.table(headers, watchlistRows)}`;
    } else {
      watchlistSection = `
        <div class="card-title" style="margin-top:20px">📋 自选股机会</div>
        ${ui.emptyState('📋', '暂无自选股，请先去自选股页面添加')}`;
    }

    let marketSection = '';
    if (fromMarket.length > 0) {
      marketSection = `
        <div class="card-title" style="margin-top:20px">🔥 全市场热点 Top ${fromMarket.length}</div>
        ${ui.table(headers, marketRows)}`;
    } else {
      marketSection = `
        <div class="card-title" style="margin-top:20px">🔥 全市场热点</div>
        ${ui.emptyState('🔍', '全市场扫描进行中，请稍后刷新')}`;
    }

    root.innerHTML = `
      <h1 class="page-title">选股机会</h1>
      <p class="page-desc">自选股 + 全市场热点扫描</p>

      ${ui.statGrid(4)}${ui.statCard(oppData?.total ?? '--', '总机会')}${ui.statCard(oppData?.strong_buy ?? '--', '强烈买入', 'var(--color-buy)')}${ui.statCard(oppData?.watch ?? '--', '建议关注', 'var(--color-watch)')}${ui.statCard(oppData?.avoid ?? '--', '需回避', 'var(--color-avoid)')}</div>

      ${progressSection}

      ${watchlistSection}
      ${marketSection}

      ${_dataTimeBar('opportunities', oppData?._server_time, oppData?._cache_state, oppData?._freshness)}
    `;

    // Bind click handlers
    root.querySelectorAll('.watchlist-row').forEach(row => {
      row.addEventListener('click', () => {
        const c = row.dataset.code;
        if (c) window.location.hash = '#/stock/' + c;
      });
      row.addEventListener('mouseenter', () => {
        row.style.background = 'rgba(108,92,231,0.04)';
      });
      row.addEventListener('mouseleave', () => {
        row.style.background = '';
      });
    });

    showStatus("");
  };

  console.log('[谛听] 选股机会 开始', new Date().toISOString());
  await _loadWithCache('opportunities', skeleton, () => api.opportunities(), render);
  console.log('[谛听] 选股机会 加载完成');
}
