/**
 * 设置页面 — 谛听 v0.7.1
 * 数据源开关、AI 模型选择、分析引擎开关、缓存管理
 */
import { api } from '../api.js';
import { cacheManager } from '../cache.js';
import {
  ui,
  _esc,
} from '../ui.js';
import {
  updateState,
  showStatus, _renderSkeleton, _loadWithCache,
} from '../app.js';

export async function renderSettings() {
  const skeleton = () => {
    showStatus("📡 正在获取设置…");
    _renderSkeleton(`
      ${ui.skeletonBlock('120px')}
      ${ui.skeletonBlock('80px')}
      ${ui.skeletonBlock('120px')}
    `);
  };

  const render = (settings, fromCache) => {
    if (fromCache) console.log('[谛听] 设置 缓存命中');

    const root = document.getElementById('app-root');

    const _toggleRow = (key, label, on, disabled) => {
      const val = on ? '1' : '0';
      const cls = `toggle-btn${on ? ' toggle-on' : ''}${disabled ? ' disabled' : ''}`;
      return `
        <div class="settings-row${disabled ? ' disabled' : ''}">
          <span class="settings-label">${_esc(label)}</span>
          <button class="${cls}" data-key="${_esc(key)}" data-value="${val}" ${disabled ? 'disabled' : ''}>
            <span class="toggle-knob"></span>
          </button>
        </div>`;
    };

    // ── Provider Toggles ──
    const providerToggles = settings.provider_toggles || [];
    let providersHtml = '';
    for (const p of providerToggles) {
      const disabled = p.requires_api_key && !p.api_key_available;
      providersHtml += _toggleRow(p.key, p.label, p.enabled, disabled);
    }

    // ── Model Selector ──
    const currentModel = settings.ai_model || 'deepseek/deepseek-v4-pro';
    const availableModels = settings.available_models || [];
    let modelHtml = '<select id="settings-model" class="settings-select">';
    for (const m of availableModels) {
      const sel = m.id === currentModel ? 'selected' : '';
      modelHtml += `<option value="${_esc(m.id)}" ${sel}>${_esc(m.label)}</option>`;
    }
    modelHtml += '</select>';

    // ── Engine Toggles ──
    const engineToggles = settings.engine_toggles || [];
    let enginesHtml = '';
    for (const e of engineToggles) {
      enginesHtml += _toggleRow(e.key, e.label, e.enabled, false);
    }

    root.innerHTML = `
      <h1 class="page-title">设置</h1>
      <p class="page-desc">定制你的分析偏好，修改即时保存</p>

      <div class="card">
        <div class="card-title">📡 数据源</div>
        <p style="font-size:12px;color:var(--text-secondary);margin-bottom:10px">
          降级链顺序：east_money → ashare → akshare。关掉的源会被跳过。
        </p>
        ${providersHtml || '<p style="color:var(--text-secondary);font-size:14px">暂无可用数据源</p>'}
      </div>

      <div class="card">
        <div class="card-title">🤖 AI 模型</div>
        <p style="font-size:12px;color:var(--text-secondary);margin-bottom:6px">选择分析引擎使用的 LLM</p>
        ${modelHtml}
        <p style="font-size:12px;color:var(--text-secondary);margin-top:6px">当前：${_esc(settings.ai_model_label || currentModel)}</p>
      </div>

      <div class="card">
        <div class="card-title">🔧 分析引擎</div>
        <p style="font-size:12px;color:var(--text-secondary);margin-bottom:10px">
          启用/禁用各分析引擎。禁用可加速分析但减少评分维度。
        </p>
        ${enginesHtml || '<p style="color:var(--text-secondary);font-size:14px">暂无引擎</p>'}
      </div>

      <div class="card" id="cache-section">
        <div class="card-title">📦 缓存管理</div>
        <p style="font-size:12px;color:var(--text-secondary);margin-bottom:10px">
          管理本地缓存数据。缓存命中可大幅提升响应速度。
        </p>
        <div id="cache-stats" style="font-size:13px;color:var(--text-secondary);margin-bottom:10px">
          加载中…
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <button id="cache-clear-btn" class="btn btn-secondary" style="font-size:13px">🗑️ 清除所有缓存</button>
          <button id="cache-refresh-btn" class="btn btn-secondary" style="font-size:13px">🔄 立即刷新扫描</button>
        </div>
      </div>
    `;

    // ── Toggle Event Handlers ──
    root.querySelectorAll('.toggle-btn:not(.disabled)').forEach(btn => {
      btn.addEventListener('click', async () => {
        const key = btn.dataset.key;
        const currentVal = btn.dataset.value;
        const newVal = currentVal === '1' ? '0' : '1';
        const newEnabled = newVal === '1';

        btn.dataset.value = newVal;
        btn.classList.toggle('toggle-on', newEnabled);

        const payload = {};
        payload[key] = newVal;
        const res = await api.saveSettings(payload);
        if (res.ok) {
          cacheManager.clear();  // invalidate caches on settings change
          showStatus("✅ 已保存");
        } else {
          btn.dataset.value = currentVal;
          btn.classList.toggle('toggle-on', currentVal === '1');
          showStatus("❌ 保存失败");
        }
      });
    });

    // ── Model Select Handler ──
    const modelSelect = document.getElementById('settings-model');
    if (modelSelect) {
      modelSelect.addEventListener('change', async () => {
        const newModel = modelSelect.value;
        const res = await api.saveSettings({ ai_model: newModel });
        if (res.ok) {
          cacheManager.clear();
          showStatus("✅ 模型已切换");
        } else {
          showStatus("❌ 保存失败");
        }
      });
    }

    showStatus("");

    // ── Cache Management ──
    _loadCacheStats();
    const cacheClearBtn = document.getElementById('cache-clear-btn');
    const cacheRefreshBtn = document.getElementById('cache-refresh-btn');

    if (cacheClearBtn) {
      cacheClearBtn.addEventListener('click', async () => {
        cacheClearBtn.disabled = true;
        cacheClearBtn.textContent = '清除中…';
        const res = await api.clearCache();
        if (res.ok) {
          cacheManager.clear();
          showStatus('✅ 缓存已清除');
          _loadCacheStats();
        } else {
          showStatus('❌ 清除失败');
        }
        cacheClearBtn.disabled = false;
        cacheClearBtn.textContent = '🗑️ 清除所有缓存';
      });
    }

    if (cacheRefreshBtn) {
      cacheRefreshBtn.addEventListener('click', async () => {
        cacheRefreshBtn.disabled = true;
        cacheRefreshBtn.textContent = '刷新中…';
        const res = await api.refreshScan();
        if (res.ok) {
          cacheManager.clear();
          showStatus('✅ 扫描已刷新');
          _loadCacheStats();
        } else {
          showStatus('❌ 刷新失败');
        }
        cacheRefreshBtn.disabled = false;
        cacheRefreshBtn.textContent = '🔄 立即刷新扫描';
      });
    }

    updateState({ loading: false });
  };

  async function _loadCacheStats() {
    try {
      const res = await api.cacheStats();
      const el = document.getElementById('cache-stats');
      if (res.ok && el) {
        const mem = res.data.memory_cache || {};
        const sql = res.data.sqlite_cache || {};
        el.innerHTML = [
          `内存缓存：${mem.size || 0} 条目 (命中率 ${((mem.hit_rate || 0) * 100).toFixed(0)}%)`,
          `数据库：${sql.db_size_mb || 0} MB · ${Object.entries(sql.table_counts || {}).map(([k, v]) => `${k}: ${v}`).join(' · ')}`,
          `最后更新：${res.data.updated_at || '—'}`,
        ].join('<br>');
      }
    } catch (_) {
      const el = document.getElementById('cache-stats');
      if (el) el.textContent = '统计加载失败';
    }
  }

  console.log('[谛听] 设置 开始', new Date().toISOString());
  await _loadWithCache('settings', skeleton, () => api.settings(), render);
  console.log('[谛听] 设置 加载完成');
}
