/** Typed v1 API client. This is the only frontend module allowed to call fetch. */

const isGatewayPath = window.location.pathname.startsWith('/app/diting');
const API_BASE = isGatewayPath ? '/api/diting/v1' : '/api/v1';
const CSRF_KEY = 'diting_v1_csrf';

class ApiError extends Error {
  constructor(code, message, status, retryable = false) {
    super(message || code);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
    this.retryable = retryable;
  }
}

function csrfToken() {
  return window.sessionStorage.getItem(CSRF_KEY);
}

function clearCsrf() {
  window.sessionStorage.removeItem(CSRF_KEY);
}

async function request(method, path, body = undefined) {
  const headers = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (!['GET', 'HEAD'].includes(method)) {
    const csrf = csrfToken();
    if (csrf) headers['X-CSRF-Token'] = csrf;
  }
  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      credentials: 'same-origin',
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (error) {
    throw new ApiError('NETWORK_ERROR', error.message || '网络连接失败', 0, true);
  }
  let envelope;
  try {
    envelope = await response.json();
  } catch (_error) {
    throw new ApiError('INVALID_RESPONSE', '服务返回了无效响应', response.status, true);
  }
  if (!response.ok || envelope.error) {
    const error = envelope.error || {};
    throw new ApiError(
      error.code || `HTTP_${response.status}`,
      error.message || '请求失败',
      response.status,
      Boolean(error.retryable),
    );
  }
  return envelope;
}

const api = {
  health: () => request('GET', '/health'),
  dashboard: () => request('GET', '/dashboard'),
  opportunities: () => request('GET', '/opportunities'),
  search: (query, limit = 10) => request('GET', `/instruments/search?q=${encodeURIComponent(query)}&limit=${limit}`),
  quote: (symbol) => request('GET', `/stocks/${encodeURIComponent(symbol)}`),
  analysis: (runId) => request('GET', `/analyses/${encodeURIComponent(runId)}`),
  createAnalysis: (symbol, profile) => request('POST', '/analyses', { symbol, profile }),
  job: (jobId) => request('GET', `/jobs/${encodeURIComponent(jobId)}`),
  cancelJob: (jobId) => request('DELETE', `/jobs/${encodeURIComponent(jobId)}`),
  session: () => request('GET', '/auth/session'),
  async login(token) {
    const envelope = await request('POST', '/auth/session', { token });
    window.sessionStorage.setItem(CSRF_KEY, envelope.data.csrf_token);
    return envelope;
  },
  async logout() {
    try {
      return await request('DELETE', '/auth/session');
    } finally {
      clearCsrf();
    }
  },
  watchlist: () => request('GET', '/watchlist'),
  addWatchlist: (entry) => request('POST', '/watchlist', entry),
  removeWatchlist: (symbol) => request('DELETE', `/watchlist/${encodeURIComponent(symbol)}`),
  preferences: () => request('GET', '/preferences'),
  savePreference: (key, value) => request('PUT', '/preferences', { key, value }),
  clearCache: (prefix = null) => request('POST', '/admin/cache/clear', { prefix }),
  strategy: () => request('GET', '/admin/strategy'),
  diagnostics: () => request('GET', '/admin/diagnostics'),
};

export { API_BASE, ApiError, api, clearCsrf, csrfToken };
