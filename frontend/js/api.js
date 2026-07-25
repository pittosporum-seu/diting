/**
 * API 封装层 — 所有后端网络请求统一入口
 * 谛听 · v0.7.1 — 统一使用 cacheManager (fetchWithCache)
 */

import { cacheManager } from './cache.js';

// API 路径 — 本地开发用 /api，Caddy 网关用 /api/diting
// 由 index.html 注入 window.DITING_API_BASE，缺省时自动检测
const API_BASE = window.DITING_API_BASE || (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1' ? '/api' : '/api/diting');

async function _request(method, path, body) {
  try {
    const opts = {
      method,
      headers: { 'Content-Type': 'application/json' },
    };
    if (body) opts.body = JSON.stringify(body);

    const res = await fetch(`${API_BASE}${path}`, opts);
    if (!res.ok) {
      const text = await res.text().catch(() => '');
      return { ok: false, error: `HTTP ${res.status}: ${text || res.statusText}` };
    }
    const data = await res.json();
    // v0.7.0: response envelope { server_time, cache_state, data, freshness }
    return {
      ok: true,
      data: data.data !== undefined ? data.data : data,
      server_time: data.server_time || null,
      cache_state: data.cache_state || 'fresh',
      freshness: data.freshness || null,
    };
  } catch (e) {
    return { ok: false, error: e.message || 'Network error' };
  }
}

/**
 * 基于 cacheManager 的统一缓存读取接口。
 * 替代旧 _swr()，统一使用 diting_cache_ 前缀。
 *
 * @param {string} url - API 路径（用作缓存键，自动加 api_ 前缀）
 * @param {object} options
 * @param {number} options.ttl - 缓存 TTL (秒), 默认 300 (5 分钟)
 * @param {boolean} options.forceRefresh - 强制跳过缓存，直接请求
 * @returns {Promise<*>} 解析后的数据
 */
function fetchWithCache(url, options = {}) {
    const { ttl = 300, forceRefresh = false } = options;
    const cacheKey = 'api_' + url;

    if (!forceRefresh) {
        const cached = cacheManager.get(cacheKey);
        if (cached !== null) return Promise.resolve(cached);
    }

    return _request('GET', url).then(data => {
        if (data.ok) {
            // v0.7.0: include server_time in cached data for timestamp display
            const enriched = { ...data.data };
            if (data.server_time) enriched._server_time = data.server_time;
            if (data.cache_state) enriched._cache_state = data.cache_state;
            if (data.freshness) enriched._freshness = data.freshness;
            cacheManager.set(cacheKey, enriched, ttl * 1000);
            return enriched;
        }
        throw new Error(data.error || '请求失败');
    });
}

const api = {
  /** GET /api/health */
  health() {
    return _request('GET', '/health');
  },

  /** GET /api/stock/{code} */
  stock(code) {
    return _request('GET', `/stock/${encodeURIComponent(code)}`);
  },

  /** GET /api/dashboard */
  dashboard() {
    return _request('GET', '/dashboard');
  },

  /** GET /api/watchlist */
  watchlist() {
    return _request('GET', '/watchlist');
  },

  /** GET /api/opportunities */
  opportunities() {
    return _request('GET', '/opportunities');
  },

  /** GET /api/market-sentiment */
  marketSentiment() {
    return _request('GET', '/market-sentiment');
  },

  /** GET /api/settings */
  settings() {
    return _request('GET', '/settings');
  },

  /** POST /api/settings */
  saveSettings(data) {
    return _request('POST', '/settings', data);
  },

  /** POST /api/watchlist — 添加自选股 */
  addWatchlist(code, name = '', market = 'sz') {
    return _request('POST', '/watchlist', { code, name, market });
  },

  /** DELETE /api/watchlist/{code} — 删除自选股 */
  removeWatchlist(code) {
    return _request('DELETE', `/watchlist/${encodeURIComponent(code)}`);
  },

  /** GET /api/stock-search?q={keyword} — 模糊搜索股票 */
  searchStock(q) {
    return _request('GET', `/stock-search?q=${encodeURIComponent(q)}`);
  },

  /** GET /api/stock-name/{code} — 根据代码获取股票名称 */
  getStockName(code) {
    return _request('GET', `/stock-name/${encodeURIComponent(code)}`);
  },

  /** GET /api/stock-list — 全市场股票列表 */
  stockList() {
    return _request('GET', '/stock-list');
  },

  /** GET /api/cache/stats — 缓存统计 */
  cacheStats() {
    return _request('GET', '/cache/stats');
  },

  /** POST /api/cache/clear — 清除所有缓存 */
  clearCache() {
    return _request('POST', '/cache/clear');
  },

  /** POST /api/cache/refresh-scan — 强制刷新全市场扫描 */
  refreshScan() {
    return _request('POST', '/cache/refresh-scan');
  },

  /** 基于 cacheManager 的统一缓存读取（替代旧 _swr） */
  fetchWithCache,
};

export { api };
