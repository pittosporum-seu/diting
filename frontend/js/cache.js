/**
 * 前端缓存管理器 — 统一 localStorage 缓存层
 * 谛听 · v0.7.1 — 从 app.js 抽出为独立模块
 *
 * 特性：
 * - TTL 5min（新鲜窗口）
 * - STALE_MAX_AGE 30min（过期但仍可用的宽限期，getStale）
 * - VERSION 版本号（升级时自动失效旧缓存）
 * - getStale / isFresh / getEntry / prune 等完整能力
 *
 * localStorage 键前缀：diting_cache_
 */
/* eslint-disable no-unused-vars */

const cacheManager = {
  PREFIX: 'diting_cache_',
  TTL: 5 * 60 * 1000,
  STALE_MAX_AGE: 30 * 60 * 1000,    // 30min — return stale data within this window
  VERSION: 2,                         // bump to invalidate all old caches on upgrade

  _read(key) {
    const raw = localStorage.getItem(this.PREFIX + key);
    if (!raw) return null;
    try {
      const parsed = JSON.parse(raw);
      // Version check — invalidate old cache on upgrade
      if (parsed.v !== this.VERSION) {
        localStorage.removeItem(this.PREFIX + key);
        return null;
      }
      const { data, ts, ttl } = parsed;
      return { data, ts, age: Date.now() - ts, ttl: ttl || this.TTL };
    } catch (_) {
      localStorage.removeItem(this.PREFIX + key);
      return null;
    }
  },

  get(key) {
    const entry = this._read(key);
    if (!entry) return null;
    const effectiveTTL = entry.ttl || this.TTL;
    if (entry.age > effectiveTTL) {
      localStorage.removeItem(this.PREFIX + key);
      return null;
    }
    return entry.data;
  },

  /** Return data even if TTL expired, as long as it's within STALE_MAX_AGE. */
  getStale(key) {
    const entry = this._read(key);
    if (!entry) return null;
    if (entry.age > this.STALE_MAX_AGE) {
      localStorage.removeItem(this.PREFIX + key);
      return null;
    }
    return entry.data;
  },

  /** Store data with optional per-entry TTL (in ms). Falls back to this.TTL. */
  set(key, data, ttlMs) {
    try {
      const payload = { data, ts: Date.now(), v: this.VERSION };
      if (ttlMs) payload.ttl = ttlMs;
      localStorage.setItem(this.PREFIX + key, JSON.stringify(payload));
    } catch (_) { /* quota exceeded — silently skip */ }
  },

  /** Check if a key is fresh (not expired). */
  isFresh(key) {
    const entry = this._read(key);
    if (!entry) return false;
    const effectiveTTL = entry.ttl || this.TTL;
    return entry.age <= effectiveTTL;
  },

  /** Return the full cache entry { data, ts } or null. */
  getEntry(key) {
    return this._read(key);
  },

  /** Remove a specific cache entry by key. */
  remove(key) {
    localStorage.removeItem(this.PREFIX + key);
  },

  /** Remove all expired cache entries. */
  prune() {
    Object.keys(localStorage)
      .filter(k => k.startsWith(this.PREFIX))
      .forEach(k => {
        const rawKey = k.slice(this.PREFIX.length);
        const entry = this._read(rawKey);
        const effectiveTTL = entry ? (entry.ttl || this.TTL) : this.TTL;
        if (!entry || entry.age > effectiveTTL) {
          localStorage.removeItem(k);
        }
      });
  },

  clear() {
    Object.keys(localStorage)
      .filter(k => k.startsWith(this.PREFIX))
      .forEach(k => localStorage.removeItem(k));
  }
};

export { cacheManager };
window.__loaded = window.__loaded || []; window.__loaded.push('cache');
