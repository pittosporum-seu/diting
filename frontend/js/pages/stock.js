/**
 * 个股分析页面 — 谛听 v0.7.1
 * 搜索落地页 + 个股详情（K 线图、技术指标、引擎评分、多空理由）
 */
import { api } from '../api.js';
import { cacheManager } from '../cache.js';
import { charts } from '../charts.js';
import {
  ui,
  _scoreGradient, _scoreTextColor, _ratingTag, _confidenceLabel,
  _rsrStatus, _macdStatus, _kdjStatus, _bollStatus,
  _maStatus, _vwapStatus, _volRatioStatus,
  _fmt, _pctSigned, _priceStyle, _dataTimeBar, _esc,
} from '../ui.js';
import {
  state, updateState,
  showStatus, _renderSkeleton, _loadWithCache,
  _getStockList, _initSearchSuggestions,
} from '../app.js';

/* ── 个股搜索落地页（含下拉建议） ── */
export function renderStockSearch() {
  const root = document.getElementById('app-root');
  root.innerHTML = `
    <h1 class="page-title">个股分析</h1>
    <p class="page-desc">输入股票代码或名称开始分析</p>
    <div class="search-bar" style="position:relative">
      <input id="stock-search" type="text" placeholder="输入代码或名称，如 002475 / 立讯"
        autocomplete="off"
        style="flex:1;padding:10px 14px;border:1px solid var(--border-color);border-radius:var(--btn-radius);font-size:15px;outline:none">
      <button id="stock-search-btn" style="padding:10px 24px;background:var(--color-primary);color:#fff;border:none;border-radius:var(--btn-radius);cursor:pointer;font-size:15px;white-space:nowrap">分析</button>
    </div>
  `;
  _bindSearch();
}

/* ── 个股分析主渲染 ── */
export async function renderStock(code) {
  updateState({ currentStock: code });
  const root = document.getElementById('app-root');
  const cacheKey = 'stock_' + code;

  const skeleton = () => {
    showStatus("🔍 正在查询行情数据…");
    root.innerHTML = `
      <div style="display:flex;gap:12px;margin-bottom:16px">
        <div class="skeleton" style="flex:1;height:40px;border-radius:8px"></div>
        <div class="skeleton" style="width:64px;height:40px;border-radius:8px"></div>
      </div>
      ${ui.skeletonBlock('100px')}
      ${ui.skeletonBlock('360px')}
      ${ui.skeletonBlock('200px')}
      ${ui.skeletonBlock('140px')}
      <div style="display:flex;gap:16px">
        ${ui.skeletonBlock('80px').replace('class="card"', 'class="card" style="flex:1"')}
        ${ui.skeletonBlock('80px').replace('class="card"', 'class="card" style="flex:1"')}
      </div>
    `;
  };

  const render = (data, fromCache) => {
    if (fromCache) {
      console.log('[谛听] 个股分析 缓存命中', code);
      showStatus("");
    }

    if (data.error) {
      root.innerHTML = `
        <div class="search-bar" style="position:relative">
          <input id="stock-search" type="text" value="${code}" placeholder="输入代码或名称"
            autocomplete="off"
            style="flex:1;padding:10px 14px;border:1px solid var(--border-color);border-radius:var(--btn-radius);font-size:15px;outline:none">
          <button id="stock-search-btn" style="padding:10px 24px;background:var(--color-primary);color:#fff;border:none;border-radius:var(--btn-radius);cursor:pointer;font-size:15px;white-space:nowrap">搜索</button>
        </div>
        ${ui.errorCard('未找到该股票', data.error)}
      `;
      _bindSearch();
      showStatus("");
      return;
    }

    // ── 数据抽取 ──
    const {
      name = code, price, change_pct: changePct,
      score, rating_label: ratingLabel, rating_emoji: ratingEmoji,
      confidence, engine_scores: engineScores = [], engine_skipped: engineSkipped = [], chart_data: chartData,
      rsi_display: rsiDisplay, macd_display: macdDisplay,
      signals_summary: sig, bull_reasons: bullReasons, bear_reasons: bearReasons,
    } = data;

    const gradient = _scoreGradient(score);
    const txtColor = _scoreTextColor(score);
    const isGradient = score >= 75 || score < 35;
    const participatingCount = engineScores.length;
    const skippedCount = engineSkipped.length;
    const totalEngineCount = participatingCount + skippedCount;
    const skipReasonLabels = {
      no_api_key: '未配置 API Key',
      non_trading_hours: '非交易时段',
      timeout: '执行超时',
      error: '执行异常',
    };
    const skippedDetails = engineSkipped
      .map(item => `${item.engine_name}: ${skipReasonLabels[item.reason] || '执行异常'}`)
      .join('\n');
    const skippedTooltip = _esc(skippedDetails)
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#39;');
    const engineParticipation = skippedCount > 0
      ? `${participatingCount}/${totalEngineCount} 个引擎参与评估（${skippedCount} 个暂不可用）`
      : `由 ${participatingCount} 个引擎综合评估`;

    // ── 渲染页面 ──
    root.innerHTML = `
      <!-- 搜索栏 -->
       <div class="search-bar" style="position:relative">
         <input id="stock-search" type="text" value="${_esc(code)}" placeholder="输入代码或名称"
           autocomplete="off"
           style="flex:1;padding:10px 14px;border:1px solid var(--border-color);border-radius:var(--btn-radius);font-size:15px;outline:none">
         <button id="stock-search-btn" style="padding:10px 24px;background:var(--color-primary);color:#fff;border:none;border-radius:var(--btn-radius);cursor:pointer;font-size:15px;white-space:nowrap">分析</button>
       </div>

      <!-- 综合评分 -->
      <div class="card fade-in" style="background:${isGradient ? gradient : 'var(--bg-card)'};color:${txtColor};text-align:center;position:relative;overflow:hidden">
        ${!isGradient ? `<div style="position:absolute;top:0;left:0;right:0;bottom:0;background:${gradient};opacity:0.06"></div>` : ''}
        <div style="position:relative;z-index:1">
          <div style="font-size:14px;opacity:0.85;margin-bottom:8px">
            ${_esc(name)} (${_esc(code)}) · 综合评分 ${ratingEmoji}
          </div>
          <div style="font-size:48px;font-weight:800;line-height:1.2">
            ${_fmt(score, 1)}<span style="font-size:20px;opacity:0.6">/100</span>
          </div>
          <div style="margin-top:8px;font-size:16px;font-weight:600">
            ${ratingLabel}${_ratingTag(score)}
          </div>
          <div style="margin-top:6px;font-size:13px;opacity:0.7">
            置信度 ${_confidenceLabel(confidence)} · <span${skippedCount > 0 ? ` title="${skippedTooltip}" style="cursor:help;text-decoration:underline dotted"` : ''}>${engineParticipation}</span>
          </div>
        </div>
      </div>

      <!-- 价格信息 -->
      <div class="card fade-in">
        <div style="display:flex;align-items:flex-end;gap:16px;flex-wrap:wrap">
          <span style="font-size:28px;font-weight:700;${_priceStyle(changePct)}">${_fmt(price, 2)}</span>
          <span style="font-size:18px;font-weight:600;${_priceStyle(changePct)}">${_pctSigned(changePct)}</span>
          ${[['PE', data.pe], ['PB', data.pb], ['总市值(亿)', data.total_mv ? _fmt(data.total_mv / 1e8, 1) : null]].map(([label, val]) => val != null ? `<span style="font-size:13px;color:var(--text-secondary)">${label} ${_fmt(val, 2)}</span>` : '').join('')}
        </div>
      </div>

      <!-- K 线图 -->
      ${chartData?.prices?.length > 0 ? `
      <div class="card fade-in">
        <div class="card-title">📈 K 线图 & 技术指标</div>
        <div id="kline-chart" class="chart-kline"></div>
        <div id="volume-chart" style="height:100px;margin-top:8px"></div>
      </div>
      ` : ''}

      <!-- 引擎评分条 -->
      ${engineScores?.length > 0 ? `
      <div class="card fade-in">
        <div class="card-title">⚙️ 各引擎评分</div>
        <div id="engine-bars" class="chart-engine-bars"></div>
      </div>
      ` : ''}

      <!-- 技术指标网格 -->
      <div class="card fade-in">
        <div class="card-title">📊 技术指标</div>
        ${_renderIndicatorGrid(fromCache && !sig ? null : sig)}
      </div>

      <!-- 多空理由 -->
      <div style="display:flex;gap:16px;flex-wrap:wrap">
        <div class="card fade-in" style="flex:1;min-width:260px">
          <div class="card-title">✅ 看多理由</div>
          ${bullReasons?.length ? `<ul style="padding-left:20px;font-size:13px;color:var(--text-secondary);line-height:1.8">${bullReasons.map(r => `<li>${_esc(r)}</li>`).join('')}</ul>` : '<p style="color:var(--text-secondary);font-size:13px">暂无</p>'}
        </div>
        <div class="card fade-in" style="flex:1;min-width:260px">
          <div class="card-title">⚠️ 风险提示</div>
          ${bearReasons?.length ? `<ul style="padding-left:20px;font-size:13px;color:var(--text-secondary);line-height:1.8">${bearReasons.map(r => `<li>${_esc(r)}</li>`).join('')}</ul>` : '<p style="color:var(--text-secondary);font-size:13px">暂无</p>'}
        </div>
      </div>

      ${_dataTimeBar('stock_' + code, data._server_time, data._cache_state)}
    `;

    _bindSearch();

    // Only render charts on fresh data (not from cache) to avoid re-rendering
    if (!fromCache) {
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
            name: es.engine_name,
            score: es.score,
          })));
        } catch (_) { /* chart render failed */ }
      }
    }

    showStatus("");
    console.log('[谛听] 个股分析 完成', code, new Date().toISOString());
  };

  const onError = (msg) => {
    let title = '数据暂时无法获取';
    let desc = '请稍后重试';
    if (msg.includes('404') || msg.includes('未找到')) {
      title = '未找到该股票';
      desc = '请检查代码是否正确';
    } else if (/network/i.test(msg) || /fetch/i.test(msg)) {
      title = '网络连接失败';
      desc = '请检查网络后重试';
    }
    root.innerHTML = `
      <div class="search-bar" style="position:relative">
        <input id="stock-search" type="text" value="${code}" placeholder="输入代码或名称"
          autocomplete="off"
          style="flex:1;padding:10px 14px;border:1px solid var(--border-color);border-radius:var(--btn-radius);font-size:15px;outline:none">
        <button id="stock-search-btn" style="padding:10px 24px;background:var(--color-primary);color:#fff;border:none;border-radius:var(--btn-radius);cursor:pointer;font-size:15px;white-space:nowrap">搜索</button>
      </div>
      ${ui.errorCard(title, desc)}
    `;
    _bindSearch();
    showStatus("");
    console.log('[谛听] 个股分析 失败', code, msg);
  };

  console.log('[谛听] 个股分析 开始', code, new Date().toISOString());
  await _loadWithCache(cacheKey, skeleton, () => api.stock(code), render, onError);
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
      <div style="background:var(--bg-page);border-radius:var(--btn-radius);padding:10px 14px;text-align:center">
        <div style="font-size:12px;color:var(--text-secondary);margin-bottom:4px">${it.name}</div>
        <div style="font-size:16px;font-weight:600;color:var(--text-primary)">${it.value}</div>
        <div style="font-size:12px;color:var(--text-secondary);margin-top:2px">${it.status} ${it.emoji}</div>
      </div>`;
  }
  html += '</div>';
  return html;
}

/* ── 搜索框绑定（含分析按钮逻辑） ── */
async function _bindSearch() {
  const input  = document.getElementById('stock-search');
  const button = document.getElementById('stock-search-btn');
  if (!input || !button) return;

  // Init dropdown suggestions
  _initSearchSuggestions(input);

  const go = async () => {
    const v = input.value.trim();
    if (!v) return;

    button.disabled = true;
    button.textContent = '搜索中…';
    button.classList.add('btn-loading');

    // If input is not a 6-digit code, try to resolve by name/pinyin/code
    let code = v;
    if (!/^\d{6}$/.test(v)) {
      const stockList = await _getStockList();
      const vl = v.toLowerCase();
      const match = stockList.find(s =>
        String(s.name || '').includes(v) || String(s.code || '').includes(v)
        || String(s.pinyin || '').includes(vl)
      );
      if (match) {
        code = match.code;
      } else {
        // Try server-side search
        try {
          const res = await api.searchStock(v);
          if (res.ok && Array.isArray(res.data?.results) && res.data.results.length > 0) {
            code = res.data.results[0].code;
          }
        } catch (_) { /* ignore */ }
      }
    }

    if (code && /^\d{6}$/.test(code)) {
      window.location.hash = '#/stock/' + code;
    } else {
      showStatus("❌ 未找到匹配的股票，请输入6位代码");
      button.disabled = false;
      button.textContent = '分析';
      button.classList.remove('btn-loading');
    }
  };

  button.addEventListener('click', go);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') go();
  });
}
