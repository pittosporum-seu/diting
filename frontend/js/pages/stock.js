/** 个股分析页面 — 谛听 v0.7.6 */
import { api } from '../api.js';
import { cacheManager } from '../cache.js';
import { charts } from '../charts.js';
import {
  ui, _fmt, _pctSigned, _priceStyle, _dataTimeBar, _esc,
  _scoreGradient, _scoreTextColor, _ratingTag, _confidenceLabel,
  _rsrStatus, _macdStatus, _kdjStatus, _bollStatus, _maStatus, _vwapStatus, _volRatioStatus,
} from '../ui.js';
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
      _renderStockHTML(code, data);
    }
  );
}

function _renderStockHTML(code, d) {
  const root = document.getElementById('app-root');

  // 错误/空数据
  if (!d || d.error || d.score == null) {
    root.innerHTML = `
      <h1 class="page-title">${_esc(d?.name || code)}</h1>
      ${ui.errorCard('暂无分析数据', d?.error || '请稍后重试，或检查股票代码是否正确')}
    `;
    return;
  }

  const score = d.score;
  const pctStyle = _priceStyle(d.change_pct);

  // 看多/看空理由
  const bullHtml = (d.bull_reasons || []).length
    ? (d.bull_reasons).map((r, i) => `<div style="padding:6px 0;color:var(--color-buy)">📈 ${_esc(String(r))}</div>`).join('')
    : '<div style="color:var(--text-secondary);padding:6px 0">暂无</div>';
  const bearHtml = (d.bear_reasons || []).length
    ? (d.bear_reasons).map((r, i) => `<div style="padding:6px 0;color:var(--color-avoid)">📉 ${_esc(String(r))}</div>`).join('')
    : '<div style="color:var(--text-secondary);padding:6px 0">暂无</div>';

  // 引擎评分列表
  const engineScores = d.engine_scores || [];
  const engineRows = engineScores.map(e => ({
    code: e.engine_name,
    cells: [
      { html: _esc(String(e.engine_name)), align: 'left' },
      { html: `<span style="font-weight:600">${_fmt(e.score, 0)}</span>`, align: 'right' },
      { html: _ratingTag(e.score), align: 'center' },
      { html: _confidenceLabel(e.confidence), align: 'center' },
    ],
  }));
  const engineTable = engineRows.length
    ? ui.table(
        [{label:'引擎',align:'left'},{label:'评分',align:'right'},{label:'评级',align:'center'},{label:'置信',align:'center'}],
        engineRows, false)
    : '<p style="color:var(--text-secondary)">本次未运行评分引擎</p>';

  // 被跳过的引擎
  const skipped = d.engine_skipped || [];
  const skippedHtml = skipped.length
    ? `<p style="font-size:12px;color:var(--text-secondary);margin-top:8px">已跳过：${skipped.map(s => `${_esc(s.engine_name)}(${_esc(s.reason)})`).join('、')}</p>`
    : '';

  // 技术信号摘要
  const s = d.signals_summary || {};
  const rsi = _rsrStatus(s.rsi_14);
  const macd = _macdStatus(s.macd, s.macd_signal_line);
  const kdj = _kdjStatus(s.kdj_k);
  const boll = _bollStatus(s.bollinger_position);
  const ma = _maStatus(s.ma_5, s.ma_20);
  const vwap = _vwapStatus(s.vwap_deviation);
  const vol = _volRatioStatus(s.volume_ratio);

  const signalCards = `
    ${ui.statGrid(4)}
      ${ui.statCard(`${_fmt(s.rsi_14,1)}<div style="font-size:12px;margin-top:4px">${rsi.emoji} ${rsi.label}</div>`, 'RSI(14)')}
      ${ui.statCard(`${_fmt(s.macd,2)}<div style="font-size:12px;margin-top:4px">${macd.emoji} ${macd.label}</div>`, 'MACD')}
      ${ui.statCard(`${_fmt(s.kdj_k,1)}<div style="font-size:12px;margin-top:4px">${kdj.emoji} ${kdj.label}</div>`, 'KDJ-K')}
      ${ui.statCard(`${_fmt(s.bollinger_position!=null?s.bollinger_position*100:null,0)}%<div style="font-size:12px;margin-top:4px">${boll.emoji} ${boll.label}</div>`, '布林位置')}
      ${ui.statCard(`<div style="font-size:13px">${ma.emoji} ${ma.label}</div>`, '均线 MA5/20')}
      ${ui.statCard(`<div style="font-size:13px">${vwap.emoji} ${vwap.label}</div>`, 'VWAP 偏离')}
      ${ui.statCard(`${_fmt(s.volume_ratio,2)}<div style="font-size:12px;margin-top:4px">${vol.emoji} ${vol.label}</div>`, '量比')}
    </div>`;

  root.innerHTML = `
    <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;margin-bottom:8px">
      <div>
        <h1 class="page-title" style="margin:0">${_esc(d.name || code)} <span style="font-size:14px;color:var(--text-secondary);font-weight:400">${_esc(String(code))}</span></h1>
        <div style="margin-top:6px;font-size:22px;font-weight:700;${pctStyle}">${_fmt(d.price,2)} <span style="font-size:15px">${_pctSigned(d.change_pct)}</span></div>
      </div>
      <div style="text-align:center;padding:12px 24px;border-radius:12px;background:${_scoreGradient(score)};color:${_scoreTextColor(score)};min-width:110px">
        <div style="font-size:32px;font-weight:800;line-height:1">${_fmt(score,0)}</div>
        <div style="font-size:12px;margin-top:4px;opacity:.9">综合评分</div>
      </div>
    </div>
    <div style="margin:8px 0 16px">${_ratingTag(score)} <span style="font-size:12px;color:var(--text-secondary);margin-left:8px">置信度：${_confidenceLabel(d.confidence)}</span></div>

    ${_dataTimeBar('stock_'+code, d._server_time, d._cache_state, d._freshness)}

    <div class="card" style="margin-top:12px">
      <div class="card-title">💡 多空理由</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
        <div><div style="font-weight:600;color:var(--color-buy);margin-bottom:4px">看多</div>${bullHtml}</div>
        <div><div style="font-weight:600;color:var(--color-avoid);margin-bottom:4px">看空</div>${bearHtml}</div>
      </div>
    </div>

    <div class="card" style="margin-top:12px">
      <div class="card-title">🧠 引擎评分</div>
      ${engineTable}
      ${skippedHtml}
      <div id="engine-bars" style="height:180px;margin-top:8px"></div>
    </div>

    <div class="card" style="margin-top:12px">
      <div class="card-title">📊 技术信号</div>
      ${signalCards}
    </div>

    <div class="card" style="margin-top:12px">
      <div class="card-title">📈 K 线走势</div>
      <div id="kline-chart" style="height:340px"></div>
      <div id="volume-chart" style="height:120px"></div>
    </div>
  `;

  // 渲染图表
  try {
    if (engineScores.length) charts.renderEngineBars('engine-bars', engineScores);
    if (d.chart_data && (d.chart_data.dates || []).length) {
      charts.renderKline('kline-chart', d.chart_data);
      charts.renderVolume('volume-chart', d.chart_data);
    }
  } catch (e) {
    console.warn('[谛听] 图表渲染失败', e);
  }
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
