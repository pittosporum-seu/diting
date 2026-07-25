/**
 * 自选股页面 — 谛听 v0.7.1
 * 自选股列表 + 添加/删除 + 搜索建议
 */
import { api } from '../api.js';
import { cacheManager } from '../cache.js';
import {
  ui,
  _fmt, _pctSigned, _priceStyle, _dataTimeBar, _esc,
} from '../ui.js';
import {
  showStatus, _renderSkeleton, _loadWithCache,
  _getStockList, _initSearchSuggestions,
} from '../core.js';

export async function renderWatchlist() {
  const skeleton = () => {
    showStatus("📡 正在获取数据…");
    _renderSkeleton(`
      <h1 class="page-title">自选股</h1>
      <p class="page-desc">持仓评分变化一览</p>
      ${ui.skeletonBlock('200px')}
    `);
  };

  const render = (data, fromCache) => {
    if (fromCache) console.log('[谛听] 自选股 缓存命中');

    // API 返回 {items:[...]}，_loadWithCache 透传为对象；兼容数组形式
    const list = Array.isArray(data) ? data : (data?.items || []);

    const root = document.getElementById('app-root');
    const addBar = `
      <div class="wl-add-bar">
        <input id="wl-search" type="text" placeholder="搜索股票代码或名称，如 603667 / 五洲新春"
          autocomplete="off"
          style="flex:1;padding:8px 12px;border:1px solid var(--border-color);border-radius:var(--btn-radius);font-size:14px;max-width:320px;outline:none">
        <button id="wl-add-btn" style="padding:8px 16px;background:var(--color-primary);color:#fff;border:none;border-radius:var(--btn-radius);cursor:pointer;font-size:14px;white-space:nowrap">＋ 添加</button>
      </div>`;

    if (!Array.isArray(list) || list.length === 0) {
      root.innerHTML = `
        <h1 class="page-title">自选股</h1>
        <p class="page-desc">持仓评分变化一览</p>
        ${addBar}
        ${ui.emptyState('📋', '还没有添加自选股', '<p><a href="#/opportunities" class="action-link">去选股机会看看有什么值得关注</a></p>')}
      `;
      _bindWatchlistAdd();
      showStatus("");
      return;
    }

    const headers = [
      { label: '代码', align: 'left' },
      { label: '名称', align: 'left' },
      { label: '价格', align: 'right' },
      { label: '涨跌', align: 'right' },
      { label: '操作', align: 'center' },
    ];

    const rows = [];
    for (const item of list) {
      const code = item.code || item;
      const name = item.name || code;
      const price = item.price != null ? _fmt(item.price, 2) : '-';
      const change = item.change_pct != null ? _pctSigned(item.change_pct) : '-';
      const pctStyle = _priceStyle(item.change_pct);
      rows.push({
        code: String(code),
        cells: [
          { html: `<span style="font-weight:600">${_esc(String(code))}</span>`, align: 'left' },
          { html: _esc(String(name)), align: 'left' },
          { html: `<span style="${pctStyle}">${price}</span>`, align: 'right' },
          { html: `<span style="${pctStyle}">${change}</span>`, align: 'right' },
          { html: `<button class="wl-del-btn" data-code="${_esc(String(code))}" style="background:none;border:none;color:var(--color-avoid);cursor:pointer;font-size:16px;padding:4px 8px" title="删除">✕</button>`, align: 'center' },
        ],
      });
    }

    root.innerHTML = `
      <h1 class="page-title">自选股</h1>
      <p class="page-desc" style="font-size:12px;color:var(--text-secondary)">持仓评分变化一览</p>
      ${addBar}
      ${ui.table(headers, rows)}
      ${_dataTimeBar('watchlist', data?._server_time, data?._cache_state, data?._freshness)}
    `;

    // ── 事件绑定 ──
    root.querySelectorAll('.watchlist-row').forEach(row => {
      row.addEventListener('click', (e) => {
        if (e.target.closest('.wl-del-btn')) return;
        const c = row.dataset.code;
        if (c) window.location.hash = '#/stock/' + c;
      });
    });

    root.querySelectorAll('.wl-del-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const code = btn.dataset.code;
        if (!code) return;
        btn.disabled = true;
        const res = await api.removeWatchlist(code);
        if (res.ok) {
          cacheManager.clear();  // invalidate all caches after mutation
          window.dispatchEvent(new CustomEvent('diting:watchlist_changed'));
          showStatus("✅ 已删除");
          renderWatchlist();
        } else {
          showStatus("❌ 删除失败");
          btn.disabled = false;
        }
      });
    });

    _bindWatchlistAdd();
    showStatus("");
  };

  console.log('[谛听] 自选股 开始', new Date().toISOString());
  await _loadWithCache('watchlist', skeleton, () => api.watchlist(), render);
  console.log('[谛听] 自选股 加载完成');
}

/* ── watchlist add bar ── */
async function _bindWatchlistAdd() {
  const input = document.getElementById('wl-search');
  const btn = document.getElementById('wl-add-btn');
  if (!input || !btn) return;

  // Shared add helper
  const _doAdd = async (code, name = '') => {
    btn.disabled = true;
    btn.classList.add('btn-loading');
    btn.textContent = '添加中…';

    const res = await api.addWatchlist(code, name);
    if (res.ok) {
      cacheManager.clear();
      window.dispatchEvent(new CustomEvent('diting:watchlist_changed'));
      input.value = '';
      showStatus(`✅ ${code} 已添加到自选股`);
      renderWatchlist();
    } else {
      showStatus(`❌ 添加失败: ${res.error || '未知错误'}`);
      btn.disabled = false;
      btn.classList.remove('btn-loading');
      btn.textContent = '＋ 添加';
    }
  };

  // Init search suggestions with onSelect = auto-add
  _initSearchSuggestions(input, {
    parentSelector: '.wl-add-bar',
    onSelect: async (code, name) => {
      await _doAdd(code, name);
    }
  });

  // "+ 添加" button: if input is 6-digit code → add; if text → first match
  btn.addEventListener('click', async () => {
    const v = input.value.trim();
    if (!v) return;

    // If it looks like a 6-digit stock code, add directly
    if (/^\d{6}$/.test(v)) {
      await _doAdd(v);
      return;
    }

    // Otherwise, search local stock list for first match
    const stockList = await _getStockList();
    const ql = v.toLowerCase();
    const match = stockList.find(s => {
      const code = String(s.code || '');
      const name = String(s.name || '');
      const pinyin = String(s.pinyin || '');
      return code.includes(v) || name.includes(ql) || name.includes(v)
        || pinyin.includes(ql);
    });

    if (match) {
      await _doAdd(String(match.code), match.name || '');
    } else {
      showStatus(`❌ 未找到匹配 "${v}" 的股票`);
    }
  });

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') btn.click();
  });
}
