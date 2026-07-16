/**
 * UI 组件库 — 谛听 v0.7.1
 * 统计卡片、表格、错误提示、数据时间戳等公共 UI 组件
 */
import { cacheManager } from './cache.js';

/* ── UI 组件库 ── */
const ui = {
  /** 统计卡片网格容器 */
  statGrid(columns = 3, gap = '12px') {
    return `<div class="stat-grid" style="--grid-cols:${columns};--grid-gap:${gap}">`;
  },

  /** 统计卡片 */
  statCard(value, label, color = '', onClick = '') {
    const clickAttr = onClick ? ` class="stat-card stat-card-clickable" data-nav="${onClick}"` : ' class="stat-card"';
    const style = color ? ` style="color:${color}"` : '';
    return `<div${clickAttr}><div class="stat-value"${style}>${value ?? '--'}</div><div class="stat-label">${_esc(label)}</div></div>`;
  },

  /** 骨架屏卡片 */
  skeletonCard(height = '52px') {
    return `<div class="stat-card"><div class="skeleton" style="height:${height}"></div></div>`;
  },

  /** 表格（全宽 card 包裹） */
  table(headers, rows, clickable = true) {
    const hdrHtml = headers.map(h =>
      `<th style="text-align:${h.align || 'left'};padding:10px 8px;font-size:12px;color:var(--text-secondary);border-bottom:1px solid var(--border-color)">${h.label}</th>`
    ).join('');
    const rowClass = clickable ? 'watchlist-row' : '';
    const rowAttr = clickable ? ' style="cursor:pointer"' : '';
    let rowsHtml = '';
    for (const r of rows) {
      const cells = r.cells.map(c =>
        `<td style="padding:10px 8px;border-bottom:1px solid var(--border-color);text-align:${c.align || 'left'}${c.style ? ';' + c.style : ''}">${c.html}</td>`
      ).join('');
      rowsHtml += `<tr class="${rowClass}" data-code="${_esc(r.code || '')}"${rowAttr}>${cells}</tr>`;
    }
    return `<div class="card fade-in" style="padding:0;overflow:hidden;overflow-x:auto">
      <table style="width:100%;border-collapse:collapse;min-width:600px">
        <thead><tr>${hdrHtml}</tr></thead>
        <tbody>${rowsHtml}</tbody>
      </table></div>`;
  },

  /** 错误卡片 */
  errorCard(title, desc) {
    return `<div class="card error-card fade-in"><div class="icon">⚠️</div><div class="title">${_esc(title)}</div><div class="desc">${_esc(desc)}</div></div>`;
  },

  /** 空状态 */
  emptyState(icon, text, actionHtml = '') {
    return `<div class="card empty-state"><div class="icon">${icon}</div><p>${_esc(text)}</p>${actionHtml}</div>`;
  },

  /** 骨架屏区域 */
  skeletonBlock(height) {
    return `<div class="card"><div class="skeleton" style="height:${height}"></div></div>`;
  },
};

/* ── 辅助函数 ── */

function _scoreGradient(score) {
  if (score >= 80) return 'linear-gradient(135deg, #00b894, #00cec9)';
  if (score >= 65) return '#fdcb6e';
  if (score >= 50) return '#dfe6e9';
  if (score >= 35) return '#ffeaa7';
  return 'linear-gradient(135deg, #e17055, #d63031)';
}

function _scoreTextColor(score) {
  if (score >= 80) return '#fff';
  if (score >= 65) return '#1a1a2e';
  if (score >= 50) return '#2d3436';
  if (score >= 35) return '#2d3436';
  return '#fff';
}

function _ratingTag(score) {
  if (score >= 80) return '<span class="tag tag-buy">🟢 强烈买入</span>';
  if (score >= 65) return '<span class="tag tag-buy">🟢 建议买入</span>';
  if (score >= 50) return '<span class="tag tag-watch">🟡 建议关注</span>';
  if (score >= 35) return '<span class="tag tag-hold">⚪ 建议观望</span>';
  return '<span class="tag tag-avoid">🔴 建议回避</span>';
}

function _confidenceLabel(c) {
  if (c >= 0.7) return '高';
  if (c >= 0.4) return '中';
  return '低';
}

function _rsrStatus(rsi) {
  if (rsi == null) return { label: '-', emoji: '' };
  if (rsi < 30) return { label: '超卖', emoji: '✅' };
  if (rsi > 75) return { label: '超买', emoji: '⚠️' };
  if (rsi > 60) return { label: '偏强', emoji: '' };
  if (rsi < 40) return { label: '偏弱', emoji: '' };
  return { label: '正常', emoji: '' };
}

function _macdStatus(macd, signal) {
  if (macd == null) return { label: '-', emoji: '' };
  if (signal == null) return { label: macd > 0 ? '正值' : '负值', emoji: '' };
  if (macd > signal) return { label: '金叉', emoji: '✅' };
  if (macd < signal) return { label: '死叉', emoji: '⚠️' };
  return { label: '持平', emoji: '' };
}

function _kdjStatus(k) {
  if (k == null) return { label: '-', emoji: '' };
  if (k < 20) return { label: '超卖', emoji: '✅' };
  if (k > 80) return { label: '超买', emoji: '⚠️' };
  return { label: '正常', emoji: '' };
}

function _bollStatus(pos) {
  if (pos == null) return { label: '-', emoji: '' };
  if (pos > 0.8) return { label: '上轨压力', emoji: '⚠️' };
  if (pos < 0.2) return { label: '下轨支撑', emoji: '✅' };
  return { label: '中轨运行', emoji: '' };
}

function _maStatus(ma5, ma20) {
  if (ma5 == null || ma20 == null) return { label: '-', emoji: '' };
  if (ma5 > ma20) return { label: '多头排列', emoji: '✅' };
  return { label: '空头排列', emoji: '⚠️' };
}

function _vwapStatus(dev) {
  if (dev == null) return { label: '-', emoji: '' };
  if (dev > 2) return { label: '价格强于均价', emoji: '✅' };
  if (dev < -2) return { label: '价格弱于均价', emoji: '⚠️' };
  return { label: '均价附近', emoji: '' };
}

function _volRatioStatus(vr) {
  if (vr == null) return { label: '-', emoji: '' };
  if (vr > 1.5) return { label: '放量', emoji: '📊' };
  if (vr < 0.5) return { label: '缩量', emoji: '' };
  return { label: '正常', emoji: '' };
}

function _fmt(n, decimals) {
  if (n == null) return '-';
  return Number(n).toFixed(decimals ?? 2);
}

/** Format a JS timestamp (ms) to a readable time string. */
function _fmtTime(ts) {
  if (!ts) return '';
  const d = new Date(ts);
  const pad = (n) => String(n).padStart(2, '0');
  return `${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

/**
 * Build a data-timestamp footer bar with freshness indicator.
 */
function _dataTimeBar(cacheKey, serverTime, cacheState) {
  let ts = null;
  let freshnessClass = 'freshness-cached';
  let freshnessLabel = '';

  if (serverTime) {
    ts = new Date(serverTime).getTime();
    if (cacheState === 'fresh') {
      freshnessClass = 'freshness-fresh';
      freshnessLabel = '';
    } else if (cacheState === 'stale') {
      freshnessClass = 'freshness-stale';
      freshnessLabel = ' · 可能滞后';
    }
  } else if (cacheKey) {
    const entry = cacheManager.getEntry(cacheKey);
    if (entry) {
      ts = entry.ts;
      freshnessClass = 'freshness-cached';
      freshnessLabel = ' · 本地缓存';
    }
  }
  if (!ts) return '';
  return `<div class="data-timestamp ${freshnessClass}"><span class="freshness-dot"></span>📡 数据更新于 ${_fmtTime(ts)}${freshnessLabel}</div>`;
}

function _pctSigned(n) {
  if (n == null) return '-';
  const v = Number(n);
  const sign = v >= 0 ? '+' : '';
  return sign + v.toFixed(2) + '%';
}

function _priceStyle(changePct) {
  const v = Number(changePct) || 0;
  if (v > 0) return 'color:#00b894';
  if (v < 0) return 'color:#e17055';
  return 'color:#b2bec3';
}

function _esc(s) {
  const el = document.createElement('span');
  el.textContent = s;
  return el.innerHTML;
}

export {
  ui,
  _scoreGradient,
  _scoreTextColor,
  _ratingTag,
  _confidenceLabel,
  _rsrStatus,
  _macdStatus,
  _kdjStatus,
  _bollStatus,
  _maStatus,
  _vwapStatus,
  _volRatioStatus,
  _fmt,
  _fmtTime,
  _dataTimeBar,
  _pctSigned,
  _priceStyle,
  _esc,
};
window.__loaded = window.__loaded || []; window.__loaded.push('ui');
