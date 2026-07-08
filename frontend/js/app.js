/**
 * 谛听 · v0.3.0 — SPA 路由 + 状态管理 + 5 页面完整实现
 * 纯 JS，无依赖框架。
 */
import { api } from './api.js';
import { charts } from './charts.js';

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

  // 5秒后自动消失
  _statusTimer = setTimeout(() => {
    bar.style.opacity = '0';
    setTimeout(() => bar.remove(), 300);
  }, 5000);
}

/* ── 辅助函数 ── */

function _scoreGradient(score) {
  if (score >= 75) return 'linear-gradient(135deg, #00b894, #00cec9)';
  if (score >= 55) return '#fdcb6e';
  if (score >= 35) return '#b2bec3';
  return 'linear-gradient(135deg, #e17055, #d63031)';
}

function _scoreTextColor(score) {
  if (score >= 75) return '#fff';
  if (score >= 55) return '#1a1a2e';
  if (score >= 35) return '#fff';
  return '#fff';
}

function _ratingTag(score) {
  if (score >= 75) return '<span class="tag tag-buy">🟢 建议买入</span>';
  if (score >= 55) return '<span class="tag tag-watch">🟡 建议关注</span>';
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

/* ── 路由表 ── */
const ROUTE_MAP = {
  'dashboard':     { re: /^#\/dashboard$/,                     render: renderDashboard },
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
    el.classList.toggle('active', el.dataset.route === name);
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

  // 更新页面标题
  const titleMap = {
    'dashboard': '谛听 · A股多模型AI投资分析',
    'stock': `${state.currentStock || '个股分析'} - 谛听`,
    'opportunities': '选股机会 - 谛听',
    'watchlist': '自选股 - 谛听',
    'settings': '设置 - 谛听',
  };
  document.title = titleMap[name] || '谛听';

  // 滚动到顶部
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

/* ═══════════════════════════════════════════════
   1. 仪表盘 renderDashboard()
   ═══════════════════════════════════════════════ */
async function renderDashboard() {
  const root = document.getElementById('app-root');

  showStatus("📡 正在获取市场数据…");
  console.log('[谛听] 仪表盘 开始', new Date().toISOString());

  // ── 骨架屏 ──
  root.innerHTML = `
    <div class="stat-grid">
      ${'<div class="stat-card"><div class="skeleton" style="height:52px"></div></div>'.repeat(4)}
    </div>
    <div class="card"><div class="skeleton" style="height:260px"></div></div>
    <div class="card"><div class="skeleton" style="height:300px"></div></div>
    <div class="card"><div class="skeleton" style="height:120px"></div></div>
  `;

  let dashboardData = null;
  let dashApiFailed = false;
  try {
    const res = await api.dashboard();
    if (res.ok) dashboardData = res.data;
  } catch (_) { dashApiFailed = true; }

  // ── 统计卡片 ──
  const buyCount    = dashboardData?.buy_signals    ?? '--';
  const watchCount  = dashboardData?.watch_signals  ?? '--';
  const holdCount   = dashboardData?.hold_signals   ?? '--';
  const avoidCount  = dashboardData?.avoid_signals  ?? '--';

  const errorBanner = dashApiFailed
    ? '<div class="dash-error">⚠️ 无法连接服务器，数据可能不是最新</div>'
    : '';

  root.innerHTML = `
    <h1 class="page-title">仪表盘</h1>
    <p class="page-desc">大盘状态概览与最近信号</p>
    ${errorBanner}

    <div class="stat-grid">
      <div class="stat-card">
        <div class="stat-value" style="color:var(--color-buy)">${buyCount}</div>
        <div class="stat-label">买入信号</div>
      </div>
      <div class="stat-card">
        <div class="stat-value" style="color:var(--color-watch)">${watchCount}</div>
        <div class="stat-label">关注信号</div>
      </div>
      <div class="stat-card">
        <div class="stat-value" style="color:var(--color-hold)">${holdCount}</div>
        <div class="stat-label">观望信号</div>
      </div>
      <div class="stat-card">
        <div class="stat-value" style="color:var(--color-avoid)">${avoidCount}</div>
        <div class="stat-label">回避信号</div>
      </div>
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
      <div class="card-title">📋 最近信号</div>
      <p style="color:var(--text-secondary);text-align:center;padding:24px">暂无数据</p>
    </div>
  `;

  // 渲染模拟图表
  try {
    charts.renderVMDGauge('vmd-gauge', 48);
    charts.renderPie('portfolio-pie', [
      { name: '买入', value: 12 },
      { name: '关注', value: 8 },
      { name: '观望', value: 5 },
      { name: '回避', value: 3 },
    ], '信号分布');
  } catch (_) { /* chart render failed */ }

  showStatus("");
  console.log('[谛听] 仪表盘 完成', new Date().toISOString());
  console.log('[谛听] 仪表盘 加载完成');
}

/* ═══════════════════════════════════════════════
   2. 个股分析 renderStock(code)
   ═══════════════════════════════════════════════ */
async function renderStock(code) {
  updateState({ currentStock: code });
  const root = document.getElementById('app-root');

  showStatus("🔍 正在查询行情数据…");
  console.log('[谛听] 个股分析 开始', code, new Date().toISOString());

  // ── 骨架屏 ──
  root.innerHTML = `
    <div style="display:flex;gap:12px;margin-bottom:16px">
      <div class="skeleton" style="flex:1;height:40px;border-radius:8px"></div>
      <div class="skeleton" style="width:64px;height:40px;border-radius:8px"></div>
    </div>
    <div class="card"><div class="skeleton" style="height:100px"></div></div>
    <div class="card"><div class="skeleton" style="height:360px"></div></div>
    <div class="card"><div class="skeleton" style="height:200px"></div></div>
    <div class="card"><div class="skeleton" style="height:140px"></div></div>
    <div style="display:flex;gap:16px">
      <div class="card" style="flex:1"><div class="skeleton" style="height:80px"></div></div>
      <div class="card" style="flex:1"><div class="skeleton" style="height:80px"></div></div>
    </div>
  `;

  // ── API 调用 ──
  let data = null;
  try {
    const res = await api.stock(code);
    if (res.ok) data = res.data;
    else throw new Error(res.error);
    console.log('[谛听] 行情数据 ✅', data?.name, code);
  } catch (e) {
    // 错误卡片
    root.innerHTML = `
      <div class="search-bar">
        <input id="stock-search" type="text" value="${code}" placeholder="输入6位股票代码"
          style="flex:1;padding:8px 12px;border:1px solid var(--border-color);border-radius:8px;font-size:14px">
        <button id="stock-search-btn" style="padding:8px 20px;background:var(--color-primary);color:#fff;border:none;border-radius:8px;cursor:pointer;font-size:14px">搜索</button>
      </div>
      <div class="card error-card">
        <div class="icon">⚠️</div>
        <div class="title">数据暂时无法获取</div>
        <div class="desc">${e.message || '网络错误，请稍后重试'}</div>
      </div>
    `;
    console.log('[谛听] 行情数据 ❌', e.message);
    _bindSearch();
    showStatus("");
    console.log(`[谛听] 个股分析 ${code} 加载完成`);
    return;
  }

  showStatus("📊 正在计算技术指标…");
  console.log('[谛听] 技术指标', data?.rsi_display ? `RSI=${data.rsi_display}` : '无数据');

  showStatus("🧠 正在运行分析引擎…");
  console.log('[谛听] 引擎评分', data?.engine_scores?.length || 0, '个引擎');

  // ── 数据抽取 ──
  const {
    name = code, price, change_pct: changePct,
    score, rating_label: ratingLabel, rating_emoji: ratingEmoji,
    confidence, engine_scores: engineScores, chart_data: chartData,
    rsi_display: rsiDisplay, macd_display: macdDisplay,
    signals_summary: sig, bull_reasons: bullReasons, bear_reasons: bearReasons,
  } = data;

  const gradient = _scoreGradient(score);
  const txtColor = _scoreTextColor(score);
  const isGradient = score >= 75 || score < 35;

  // ── 渲染页面 ──
  root.innerHTML = `
    <!-- 搜索栏 -->
     <div class="search-bar">
       <input id="stock-search" type="text" value="${code}" placeholder="输入6位股票代码"
        style="flex:1;padding:8px 12px;border:1px solid var(--border-color);border-radius:8px;font-size:14px">
      <button id="stock-search-btn" style="padding:8px 20px;background:var(--color-primary);color:#fff;border:none;border-radius:8px;cursor:pointer;font-size:14px">搜索</button>
    </div>

    <!-- 结论卡 -->
    <div class="card" style="overflow:hidden;margin-bottom:16px;padding:0">
      <div style="display:flex;align-items:center;padding:24px 20px;
        ${isGradient ? `background:${gradient};color:${txtColor}` : `background:${gradient};color:${txtColor}`}">
        <div style="flex-shrink:0;text-align:center;margin-right:20px">
          <div style="font-size:48px;font-weight:700;line-height:1.1">${Math.round(score)}</div>
        </div>
        <div style="flex:1">
          <div style="font-size:16px;font-weight:600;margin-bottom:4px">
            ${ratingEmoji} ${ratingLabel}
          </div>
          <div style="font-size:13px;opacity:0.9">
            评分 ${Math.round(score)}/100 · 多引擎共识 · 信心${_confidenceLabel(confidence)}
          </div>
        </div>
        <div style="text-align:right;flex-shrink:0">
          <div style="font-size:20px;font-weight:700;${isGradient ? `color:${txtColor}` : _priceStyle(changePct)}">${_fmt(price, 2)}</div>
          <div style="font-size:13px;${isGradient ? `color:${txtColor};opacity:0.85` : ''}">${_pctSigned(changePct)}</div>
        </div>
      </div>
    </div>

    <!-- K线图 -->
    <div class="card">
      <div class="card-title">📈 K线图 + 均线 + 布林带</div>
       <div id="kline-chart" class="chart-kline"></div>
    </div>

    <!-- 成交量图 -->
    <div class="card">
      <div class="card-title">📊 成交量</div>
      <div id="volume-chart" style="height:160px"></div>
    </div>

    <!-- 引擎评分柱状图 -->
    <div class="card">
      <div class="card-title">🧠 引擎评分</div>
       <div id="engine-bars" class="chart-engine-bars"></div>
    </div>

    <!-- 技术指标面板 -->
    <div class="card">
      <div class="card-title">📊 技术指标</div>
      ${_renderIndicatorGrid(sig)}
    </div>

    <!-- 多空理由 -->
    <div style="display:flex;gap:16px;flex-wrap:wrap">
      <div class="card" style="flex:1;min-width:260px">
        <div class="card-title">📈 看多理由</div>
        ${bullReasons && bullReasons.length > 0
          ? '<ul style="padding-left:20px;color:var(--text-primary);font-size:14px;line-height:1.8">'
            + bullReasons.map(r => `<li>${_esc(r)}</li>`).join('')
            + '</ul>'
          : '<p style="color:var(--text-secondary);font-size:14px">暂无看多信号</p>'}
      </div>
      <div class="card" style="flex:1;min-width:260px">
        <div class="card-title">📉 看空理由</div>
        ${bearReasons && bearReasons.length > 0
          ? '<ul style="padding-left:20px;color:var(--text-primary);font-size:14px;line-height:1.8">'
            + bearReasons.map(r => `<li>${_esc(r)}</li>`).join('')
            + '</ul>'
          : '<p style="color:var(--text-secondary);font-size:14px">暂无看空信号</p>'}
      </div>
    </div>
  `;

  _bindSearch();

  showStatus("📈 正在渲染图表…");
  console.log('[谛听] 渲染图表', chartData?.dates?.length || 0, '个数据点');

  // ── 渲染图表 ──
  if (chartData && chartData.dates && chartData.dates.length > 0) {
    try {
      charts.renderKline('kline-chart', {
        dates: chartData.dates,
        prices: chartData.prices || [],
        ohlc: chartData.ohlc,
        ma_5: chartData.ma_5 || [],
        ma_20: chartData.ma_20 || [],
        boll_upper: chartData.boll_upper || [],
        boll_lower: chartData.boll_lower || [],
      });
    } catch (_) { /* chart render failed */ }

    try {
      if (chartData.volumes && chartData.volumes.length > 0) {
        charts.renderVolume('volume-chart', chartData);
      }
    } catch (_) { /* chart render failed */ }
  }

  if (engineScores && engineScores.length > 0) {
    try {
      charts.renderEngineBars('engine-bars', engineScores.map(es => ({
        name: es.name,
        score: es.score,
      })));
    } catch (_) { /* chart render failed */ }
  }

  showStatus("");
  console.log('[谛听] 渲染完成', code, new Date().toISOString());
  console.log(`[谛听] 个股分析 ${code} 加载完成`);
}

function _renderIndicatorGrid(sig) {
  if (!sig) {
    return '<p style="color:var(--text-secondary);text-align:center;padding:24px">暂无技术指标数据</p>';
  }

  const rsi    = _rsrStatus(sig.rsi_14);
  const macd   = _macdStatus(sig.macd, sig.macd_signal_line);
  const kdj    = _kdjStatus(sig.kdj_k);
  const boll   = _bollStatus(sig.bollinger_position);
  const ma     = _maStatus(sig.ma_5, sig.ma_20);
  const vwap   = _vwapStatus(sig.vwap_deviation);
  const vr     = _volRatioStatus(sig.volume_ratio);

  const items = [
    { name: 'RSI(14)',  value: _fmt(sig.rsi_14, 1),   status: rsi.label,  emoji: rsi.emoji },
    { name: 'MACD',    value: _fmt(sig.macd, 3),     status: macd.label, emoji: macd.emoji },
    { name: 'KDJ-K',   value: _fmt(sig.kdj_k, 1),     status: kdj.label,  emoji: kdj.emoji },
    { name: '布林带',  value: _fmt(sig.bollinger_position, 2), status: boll.label, emoji: boll.emoji },
    { name: 'MA5',     value: _fmt(sig.ma_5, 2),      status: ma.label,   emoji: ma.emoji },
    { name: 'MA20',    value: _fmt(sig.ma_20, 2),     status: '-',        emoji: '' },
    { name: 'VWAP',    value: _fmt(sig.vwap, 2),      status: vwap.label, emoji: vwap.emoji },
    { name: '量比',    value: _fmt(sig.volume_ratio, 2), status: vr.label, emoji: vr.emoji },
  ];

  let html = '<div class="indicator-grid">';
  for (const it of items) {
    html += `
      <div style="background:#f8f9fb;border-radius:8px;padding:10px 14px;text-align:center">
        <div style="font-size:12px;color:var(--text-secondary);margin-bottom:4px">${it.name}</div>
        <div style="font-size:16px;font-weight:600;color:var(--text-primary)">${it.value}</div>
        <div style="font-size:12px;color:var(--text-secondary);margin-top:2px">${it.status} ${it.emoji}</div>
      </div>`;
  }
  html += '</div>';
  return html;
}

function _esc(s) {
  const el = document.createElement('span');
  el.textContent = s;
  return el.innerHTML;
}

function _bindSearch() {
  const input  = document.getElementById('stock-search');
  const button = document.getElementById('stock-search-btn');
  if (!input || !button) return;
  const go = () => {
    const v = input.value.trim();
    if (v && /^\d{6}$/.test(v)) {
      window.location.hash = '#/stock/' + v;
    }
  };
  button.onclick = go;
  input.onkeydown = (e) => { if (e.key === 'Enter') go(); };
}

/* ═══════════════════════════════════════════════
   3. 选股机会 renderOpportunities()
   ═══════════════════════════════════════════════ */
async function renderOpportunities() {
  const root = document.getElementById('app-root');

  showStatus("📡 正在获取数据…");
  console.log('[谛听] 选股机会 开始', new Date().toISOString());

  // ── 骨架屏 ──
  root.innerHTML = `
    <h1 class="page-title">选股机会</h1>
    <p class="page-desc">信号统计与评分排序</p>
    <div class="stat-grid">
      ${'<div class="stat-card"><div class="skeleton" style="height:52px"></div></div>'.repeat(4)}
    </div>
    <div class="card"><div class="skeleton" style="height:200px"></div></div>
  `;

  let oppData = null;
  let oppApiFailed = false;
  try {
    const res = await api.opportunities();
    if (res.ok) oppData = res.data;
  } catch (_) { oppApiFailed = true; }

  // ── API 失败 ──
  if (oppApiFailed) {
    root.innerHTML = `
      <h1 class="page-title">选股机会</h1>
      <p class="page-desc">信号统计与评分排序</p>
      <div class="card error-card">
        <div class="icon">⚠️</div>
        <div class="title">暂时无法获取选股数据</div>
        <div class="desc">请检查网络连接后重试</div>
      </div>
    `;
    showStatus("");
    console.log('[谛听] 选股机会 加载完成');
    return;
  }

  // ── 渲染 ──
  root.innerHTML = `
    <h1 class="page-title">选股机会</h1>
    <p class="page-desc">信号统计与评分排序</p>

    <div class="stat-grid">
      <div class="stat-card">
        <div class="stat-value">${oppData?.total ?? '--'}</div>
        <div class="stat-label">总机会</div>
      </div>
      <div class="stat-card">
        <div class="stat-value" style="color:var(--color-buy)">${oppData?.strong_buy ?? '--'}</div>
        <div class="stat-label">强烈买入</div>
      </div>
      <div class="stat-card">
        <div class="stat-value" style="color:var(--color-watch)">${oppData?.watch ?? '--'}</div>
        <div class="stat-label">建议关注</div>
      </div>
      <div class="stat-card">
        <div class="stat-value" style="color:var(--color-avoid)">${oppData?.avoid ?? '--'}</div>
        <div class="stat-label">需回避</div>
      </div>
    </div>

    <div class="card empty-state">
      <div class="icon">📋</div>
      <p>暂无符合条件的选股机会</p>
    </div>
  `;

  showStatus("");
  console.log('[谛听] 选股机会 完成', new Date().toISOString());
  console.log('[谛听] 选股机会 加载完成');
}

/* ═══════════════════════════════════════════════
   4. 自选股 renderWatchlist()
   ═══════════════════════════════════════════════ */
async function renderWatchlist() {
  const root = document.getElementById('app-root');

  showStatus("📡 正在获取数据…");
  console.log('[谛听] 自选股 开始', new Date().toISOString());

  // ── 骨架屏 ──
  root.innerHTML = `
    <h1 class="page-title">自选股</h1>
    <p class="page-desc">持仓评分变化一览</p>
    <div class="card"><div class="skeleton" style="height:200px"></div></div>
  `;

  let list = [];
  let wlApiFailed = false;
  try {
    const res = await api.watchlist();
    if (res.ok && Array.isArray(res.data)) list = res.data;
  } catch (_) { wlApiFailed = true; }

  // ── API 失败 ──
  if (wlApiFailed) {
    root.innerHTML = `
      <h1 class="page-title">自选股</h1>
      <p class="page-desc">持仓评分变化一览</p>
      <div class="card error-card">
        <div class="icon">⚠️</div>
        <div class="title">暂时无法获取自选股数据</div>
        <div class="desc">请检查网络连接后重试</div>
      </div>
    `;
    showStatus("");
    console.log('[谛听] 自选股 加载完成');
    return;
  }

  // ── 空状态 ──
  if (list.length === 0) {
    root.innerHTML = `
      <h1 class="page-title">自选股</h1>
      <p class="page-desc">持仓评分变化一览</p>
      <div class="card empty-state">
        <div class="icon">📋</div>
        <p>还没有添加自选股</p>
        <p><a href="#/opportunities" class="action-link">去选股机会看看有什么值得关注</a></p>
      </div>
    `;
    showStatus("");
    console.log('[谛听] 自选股 加载完成');
    return;
  }

  const now = new Date().toLocaleString('zh-CN');
  let rows = '';
  for (const item of list) {
    const code = item.code || item;
    const name = item.name || code;
    rows += `
      <tr class="watchlist-row" data-code="${_esc(String(code))}" style="cursor:pointer">
        <td style="padding:10px 12px;border-bottom:1px solid var(--border-color);font-weight:600">${_esc(String(code))}</td>
        <td style="padding:10px 12px;border-bottom:1px solid var(--border-color)">${_esc(String(name))}</td>
      </tr>`;
  }

  root.innerHTML = `
    <h1 class="page-title">自选股</h1>
    <p class="page-desc" style="font-size:12px;color:var(--text-secondary)">更新于 ${now}</p>
    <div class="card" style="padding:0;overflow:hidden">
      <table style="width:100%;border-collapse:collapse">
        <thead>
          <tr>
            <th style="text-align:left;padding:10px 12px;font-size:12px;color:var(--text-secondary);border-bottom:1px solid var(--border-color)">代码</th>
            <th style="text-align:left;padding:10px 12px;font-size:12px;color:var(--text-secondary);border-bottom:1px solid var(--border-color)">名称</th>
          </tr>
        </thead>
        <tbody>
          ${rows}
        </tbody>
      </table>
    </div>
  `;

  // 行点击 → 跳转个股分析
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
  console.log('[谛听] 自选股 完成', new Date().toISOString());
  console.log('[谛听] 自选股 加载完成');
}

/* ═══════════════════════════════════════════════
   5. 设置 renderSettings()
   ═══════════════════════════════════════════════ */
function renderSettings() {
  const root = document.getElementById('app-root');

  const groups = [
    {
      title: '📡 数据源配置',
      desc: '当前降级链：eltdx → ashare → mx-data → akshare',
      items: [
        { label: 'eltdx（通达信直连）',   on: true,  desc: '0.2s 极速，免费' },
        { label: 'ashare（新浪/腾讯）',    on: true,  desc: '免费，不限量' },
        { label: 'mx-data（东方财富）',    on: true,  desc: '需 API Key' },
        { label: 'akshare（免费兜底）',    on: true,  desc: '最后备用' },
      ],
    },
    {
      title: '🤖 AI 模型配置',
      desc: '当前模型：deepseek-v4-pro',
      items: [
        { label: 'deepseek-v4-pro', on: true, desc: '默认模型，高性价比' },
        { label: 'deepseek-v4-flash', on: false, desc: '更快，适合简单任务' },
      ],
    },
    {
      title: '🔧 引擎开关',
      desc: '选中引擎参与分析评分',
      items: [
        { label: 'Wyckoff（威克夫）',    on: true,  desc: 'Phase A-E 阶段识别' },
        { label: 'Buffett/Munger',      on: true,  desc: '100分综合评分' },
        { label: 'CANSLIM',             on: true,  desc: '七维成长股评分' },
        { label: 'Volume Profile',      on: true,  desc: 'VAH/POC/VAL 支撑压力' },
        { label: 'VMD+RSI',             on: true,  desc: '三维择时' },
        { label: 'Verdict',             on: true,  desc: '信号→人话结论' },
      ],
    },
    {
      title: '📬 通知渠道',
      desc: '分析结果推送方式',
      items: [
        { label: '飞书机器人', on: false, desc: '通过 Webhook 推送' },
        { label: '邮件通知',   on: false, desc: 'SMTP 发送' },
        { label: '本地文件',   on: true,  desc: '生成 HTML / JSON 报告' },
      ],
    },
  ];

  let groupsHtml = '';
  for (const g of groups) {
    let itemsHtml = '';
    for (const it of g.items) {
      itemsHtml += `
        <div style="display:flex;align-items:center;justify-content:space-between;padding:10px 0;border-bottom:1px solid var(--border-color)">
          <div>
            <div style="font-size:14px;font-weight:500;color:var(--text-primary)">${it.label}</div>
            <div style="font-size:12px;color:var(--text-secondary)">${it.desc}</div>
          </div>
          <div style="width:44px;height:24px;border-radius:12px;position:relative;cursor:pointer;
            background:${it.on ? 'var(--color-primary)' : '#d1d5db'};transition:background .2s">
            <div style="position:absolute;top:2px;${it.on ? 'right:2px' : 'left:2px'};width:20px;height:20px;
              border-radius:50%;background:#fff;transition:all .2s;box-shadow:0 1px 3px rgba(0,0,0,.2)"></div>
          </div>
        </div>`;
    }
    groupsHtml += `
      <div class="card">
        <div class="card-title">${g.title}</div>
        <div style="font-size:12px;color:var(--text-secondary);margin-bottom:8px">${g.desc}</div>
        ${itemsHtml}
      </div>`;
  }

  root.innerHTML = `
    <h1 class="page-title">设置</h1>
    <p class="page-desc">数据源、AI 模型、引擎开关与通知渠道</p>
    ${groupsHtml}
    <div style="text-align:center;margin-top:16px">
      <button id="settings-save" style="padding:10px 32px;background:var(--color-primary);color:#fff;
        border:none;border-radius:8px;cursor:pointer;font-size:14px;font-weight:600">保存配置</button>
    </div>
  `;

  document.getElementById('settings-save').addEventListener('click', () => {
    alert('配置保存将在后续版本实现');
  });

  console.log('[谛听] 设置 加载完成');
}

/* ── 启动 ── */
window.addEventListener('hashchange', renderPage);
window.addEventListener('DOMContentLoaded', renderPage);
