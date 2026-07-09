/**
 * API 封装层 — 所有后端网络请求统一入口
 * 谛听 · v0.3.0
 */

// 自动探测 API 路径
// SPA 在 /app/stocks/diting/ 下时，API 在 /app/stocks/diting/api/
// 本地开发 SPA 在 /app/ 下时，API 在 /api/
const _path = window.location.pathname;
const _m = _path.match(/^(.+?\/stocks\/diting\/)/);
const API_BASE = _m ? `${_m[1]}api` : '/api';

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
    return { ok: true, data };
  } catch (e) {
    return { ok: false, error: e.message || 'Network error' };
  }
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

  /** POST /api/settings */
  saveSettings(data) {
    return _request('POST', '/settings', data);
  },
};

export { api };
