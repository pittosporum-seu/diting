/**
 * 仪表盘页面 — 谛听 v0.7.1
 * 大盘指数、信号统计、VMD 周期仪表盘、信号分布饼图、Top 机会列表
 */
import { api } from '../api.js';
import { cacheManager } from '../cache.js';
import { charts } from '../charts.js';
import {
  ui,
  _fmt, _pctSigned, _dataTimeBar, _esc,
} from '../ui.js';
import {
  showStatus, _renderSkeleton, _loadWithCache,
} from '../core.js';

export async function renderDashboard() {
  const skeleton = () => {
    showStatus("📡 正在获取市场数据…");
    _renderSkeleton(`
      ${ui.statGrid(3)}${ui.skeletonCard().repeat(3)}</div>
      ${ui.statGrid(4)}${ui.skeletonCard().repeat(4)}</div>
      ${ui.skeletonBlock('260px')}
      ${ui.skeletonBlock('300px')}
      ${ui.skeletonBlock('120px')}
    `);
  };

  const render = (data, fromCache) => {
    if (fromCache) console.log('[谛听] 仪表盘 缓存命中');
    _renderDashboardHTML(data);
    if (fromCache) {
      showStatus("");  // 缓存命中时不显示 loading
    }
  };

  console.log('[谛听] 仪表盘 开始', new Date().toISOString());
  await _loadWithCache('dashboard', skeleton, () => api.dashboard(), render);
  console.log('[谛听] 仪表盘 加载完成');
}

function _renderDashboardHTML(dashboardData) {
  const root = document.getElementById('app-root');

  // ── 大盘指数卡片 ──
  const defaultIndices = [
    { code: '000001', name: '上证指数' },
    { code: '399001', name: '深证成指' },
    { code: '399006', name: '创业板指' },
  ];
  const indices = dashboardData?.market_indices || [];
  let indicesHtml = `<div class="stat-grid" id="dash-indices" style="--grid-cols:3;--grid-gap:12px">`;
  if (indices.length > 0) {
    for (const idx of indices) {
      const pct = idx.change_pct ?? 0;
      const color = pct > 0 ? 'var(--color-buy)' : pct < 0 ? 'var(--color-avoid)' : 'var(--text-secondary)';
      const sign = pct >= 0 ? '+' : '';
      const valueHtml = `${_fmt(idx.price, 2)}<div style="font-size:13px;color:${color};margin-top:4px">${sign}${_fmt(pct, 2)}%</div>`;
      indicesHtml += ui.statCard(valueHtml, idx.name, color, `#/stock/${idx.code}`);
    }
  } else {
    for (const idx of defaultIndices) {
      const emptyValue = '--<div style="font-size:13px;color:var(--text-secondary);margin-top:4px">--</div>';
      indicesHtml += ui.statCard(emptyValue, idx.name, 'var(--text-secondary)');
    }
  }
  indicesHtml += '</div>';

  // ── 信号统计卡片 ──
  const buyCount   = dashboardData?.buy_signals    ?? '--';
  const watchCount = dashboardData?.watch_signals  ?? '--';
  const holdCount  = dashboardData?.hold_signals   ?? '--';
  const avoidCount = dashboardData?.avoid_signals  ?? '--';

  // ── Top 机会列表 ──
  const topOpps = dashboardData?.top_opportunities || [];
  let recentHtml = '';
  if (topOpps.length > 0) {
    recentHtml = '<div style="max-height:240px;overflow-y:auto">';
    for (const o of topOpps) {
      const pctColor = (o.change_pct ?? 0) >= 0 ? 'color:var(--color-buy)' : 'color:var(--color-avoid)';
      const pctStr = _pctSigned(o.change_pct);
      recentHtml += `
        <div class="opp-row" data-code="${_esc(o.code)}" style="display:flex;align-items:center;justify-content:space-between;
          padding:10px 12px;border-bottom:1px solid var(--border-color);cursor:pointer;transition:background .15s">
          <div>
            <span style="font-weight:600;font-size:14px">${_esc(o.code)}</span>
            <span style="margin-left:6px;font-size:13px;color:var(--text-secondary)">${_esc(o.name || o.code)}</span>
          </div>
          <div style="display:flex;align-items:center;gap:8px">
            <span style="${pctColor};font-size:13px">${pctStr}</span>
          </div>
        </div>`;
    }
    recentHtml += '</div>';
  } else {
    recentHtml = '<p style="color:var(--text-secondary);text-align:center;padding:24px">暂无信号</p>';
  }

  root.innerHTML = `
    <h1 class="page-title">仪表盘</h1>
    <p class="page-desc">大盘状态概览与最近信号</p>

    ${_dataTimeBar('dashboard', dashboardData?._server_time, dashboardData?._cache_state)}

    ${indicesHtml}

    <div class="stat-grid" id="dash-signals" style="--grid-cols:4;--grid-gap:12px">
    ${ui.statCard(buyCount, '买入信号', 'var(--color-buy)', '#/opportunities')}
    ${ui.statCard(watchCount, '关注信号', 'var(--color-watch)', '#/opportunities')}
    ${ui.statCard(holdCount, '观望信号', 'var(--color-hold)', '#/opportunities')}
    ${ui.statCard(avoidCount, '回避信号', 'var(--color-avoid)', '#/opportunities')}
    </div>

    <div class="card">
      <div class="card-title">📊 大盘 VMD 周期仪表盘</div>
      <div id="vmd-gauge" style="height:260px"></div>
    </div>

    <div class="card">
      <div class="card-title">🥧 信号分布</div>
      <div id="portfolio-pie" style="height:300px"></div>
    </div>

    <div class="card">
      <div class="card-title">📋 选股机会 Top 5</div>
      ${recentHtml}
    </div>
  `;

  // ── 事件绑定 ──
  root.querySelectorAll('#dash-indices .stat-card-clickable').forEach(card => {
    card.addEventListener('click', () => {
      const nav = card.dataset.nav;
      if (nav) window.location.hash = nav;
    });
  });

  root.querySelectorAll('#dash-signals .stat-card-clickable').forEach(card => {
    card.addEventListener('click', () => {
      window.location.hash = '#/opportunities';
    });
  });

  root.querySelectorAll('.opp-row').forEach(row => {
    const code = row.dataset.code;
    if (code) {
      row.addEventListener('click', () => {
        window.location.hash = '#/stock/' + code;
      });
      row.addEventListener('mouseenter', () => { row.style.background = 'rgba(108,92,231,0.04)'; });
      row.addEventListener('mouseleave', () => { row.style.background = ''; });
    }
  });

  // ── 渲染图表 ──
  const vmdPos = dashboardData?.vmd_cycle?.cycle_position ?? 48;
  try {
    charts.renderVMDGauge('vmd-gauge', vmdPos);
    charts.renderPie('portfolio-pie', [
      { name: '买入', value: typeof buyCount === 'number' ? buyCount : 0 },
      { name: '关注', value: typeof watchCount === 'number' ? watchCount : 0 },
      { name: '观望', value: typeof holdCount === 'number' ? holdCount : 0 },
      { name: '回避', value: typeof avoidCount === 'number' ? avoidCount : 0 },
    ], '信号分布');
  } catch (_) { /* chart render failed */ }

  showStatus("");
  console.log('[谛听] 仪表盘 完成', new Date().toISOString());
}
