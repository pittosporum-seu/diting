/** Diting v0.8 application shell, page state machine and safe DOM rendering. */

import { ApiError, api, clearCsrf, csrfToken } from './api.js?v=0.8.0';

const root = document.getElementById('app-root');
const title = document.getElementById('page-title');
const eyebrow = document.getElementById('page-eyebrow');
const authButton = document.getElementById('auth-button');
const authState = document.getElementById('auth-state');
const loginDialog = document.getElementById('login-dialog');
const loginForm = document.getElementById('login-form');
const loginError = document.getElementById('login-error');
const tokenInput = document.getElementById('owner-token');

const state = {
  route: 'dashboard',
  phase: 'idle',
  authenticated: false,
  authConfigured: true,
  pageEpoch: 0,
};

const pageMeta = {
  dashboard: ['市场概览', 'MARKET INTELLIGENCE'],
  stock: ['个股分析', 'SECURITY ANALYSIS'],
  opportunities: ['机会策略', 'ACTIVE STRATEGY'],
  watchlist: ['自选列表', 'OWNER WATCHLIST'],
  settings: ['系统设置', 'OWNER CONTROLS'],
};

const icons = {
  dashboard: [['path', { d: 'M4 17h6V4H4v13Zm9 0h6V10h-6v7Zm9 0h6V7h-6v10Z' }]],
  search: [['circle', { cx: '14', cy: '14', r: '8' }], ['path', { d: 'm20 20 6 6' }]],
  ranking: [['path', { d: 'M6 25V14m10 11V7m10 18V11' }]],
  bookmark: [['path', { d: 'M9 5h14v22l-7-4-7 4V5Z' }]],
  settings: [
    ['circle', { cx: '16', cy: '16', r: '4' }],
    ['path', { d: 'M16 3v4m0 18v4M3 16h4m18 0h4M6.8 6.8l2.8 2.8m12.8 12.8 2.8 2.8m0-18.4-2.8 2.8M9.6 22.4l-2.8 2.8' }],
  ],
  close: [['path', { d: 'm9 9 14 14M23 9 9 23' }]],
  empty: [['circle', { cx: '16', cy: '16', r: '12' }], ['path', { d: 'M11 16h10' }]],
  lock: [['rect', { x: '7', y: '14', width: '18', height: '14', rx: '3' }], ['path', { d: 'M11 14V9a5 5 0 0 1 10 0v5' }]],
  alert: [['path', { d: 'M16 4 29 27H3L16 4Z' }], ['path', { d: 'M16 12v7m0 4v.2' }]],
  activity: [['path', { d: 'M3 17h6l3-8 7 16 4-8h6' }]],
};

function svgIcon(name, className = '') {
  const wrapper = document.createElement('span');
  wrapper.className = className;
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 32 32');
  svg.setAttribute('aria-hidden', 'true');
  for (const [tag, attributes] of icons[name] || icons.empty) {
    const shape = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [attribute, value] of Object.entries(attributes)) shape.setAttribute(attribute, value);
    svg.append(shape);
  }
  wrapper.append(svg);
  return wrapper;
}

function element(tag, options = {}, children = []) {
  const node = document.createElement(tag);
  if (options.className) node.className = options.className;
  if (options.text !== undefined) node.textContent = String(options.text);
  if (options.id) node.id = options.id;
  for (const [name, value] of Object.entries(options.attrs || {})) node.setAttribute(name, value);
  for (const child of Array.isArray(children) ? children : [children]) {
    if (child !== null && child !== undefined) node.append(child);
  }
  return node;
}

function button(label, className = 'button secondary', onClick = null) {
  const node = element('button', { className, text: label, attrs: { type: 'button' } });
  if (onClick) node.addEventListener('click', onClick);
  return node;
}

function card(children, className = '') {
  return element('section', { className: `card ${className}`.trim() }, children);
}

function setPage(route) {
  state.route = route;
  state.pageEpoch += 1;
  const meta = pageMeta[route] || pageMeta.dashboard;
  title.textContent = meta[0];
  eyebrow.textContent = meta[1];
  document.querySelectorAll('[data-route]').forEach((link) => {
    link.classList.toggle('active', link.dataset.route === route);
  });
}

function loadingState() {
  state.phase = 'loading';
  const blocks = Array.from({ length: 4 }, () => element('div', { className: 'skeleton', attrs: { style: 'height:120px' } }));
  root.replaceChildren(element('div', { className: 'grid metrics' }, blocks));
}

function statePanel(kind, heading, copy, action = null) {
  state.phase = kind;
  const content = element('div', {}, [
    svgIcon(kind === 'auth-required' ? 'lock' : kind === 'error' ? 'alert' : 'empty', 'state-icon'),
    element('h2', { text: heading }),
    element('p', { text: copy }),
  ]);
  if (action) content.append(action);
  root.replaceChildren(element('section', { className: 'card state-panel' }, content));
}

function authRequired(copy = '此页面包含 owner 数据，请先建立安全会话。') {
  statePanel('auth-required', '需要 Owner 权限', copy, button('Owner 登录', 'button primary', openLogin));
}

function handlePageError(error) {
  if (error instanceof ApiError && error.code === 'AUTH_REQUIRED') {
    state.authenticated = false;
    updateAuthUi();
    authRequired();
    return;
  }
  const code = error instanceof ApiError ? error.code : 'UNEXPECTED_ERROR';
  statePanel('error', '页面暂时不可用', `${code} · ${error.message || '未知错误'}`, button('重试', 'button secondary', renderRoute));
}

function metric(label, value, context) {
  return card([
    element('div', { className: 'metric-label', text: label }),
    element('div', { className: 'metric-value', text: value }),
    element('div', { className: 'metric-context', text: context }),
  ], 'compact');
}

function pill(text, kind = '') {
  return element('span', { className: `status-pill ${kind}`.trim(), text });
}

async function renderDashboard() {
  loadingState();
  try {
    const [dashboard, opportunities] = await Promise.all([api.dashboard(), api.opportunities()]);
    const data = dashboard.data;
    const opportunity = opportunities.data;
    const statusWarning = opportunities.meta.warnings?.[0];
    const stack = element('div', { className: 'page-stack' });
    stack.append(element('div', { className: 'grid metrics' }, [
      metric('系统版本', data.version, '统一 Python / CLI / HTTP 版本'),
      metric('分析内核', data.analysis_available ? '可用' : '不可用', '确定性与结构化引擎'),
      metric('生产策略', data.active_strategy || '未激活', statusWarning?.code || 'active registry'),
      metric('公开读取', data.public_readonly ? '已开启' : 'Owner 限定', '写操作始终需要会话'),
    ]));
    const strategyCard = card([
      element('div', { className: 'card-header' }, [
        element('div', {}, [element('h2', { text: '机会策略状态' }), element('p', { text: '榜单只读取人工激活且可追溯的版本' })]),
        pill(data.active_strategy ? 'Active' : 'Unavailable', data.active_strategy ? 'success' : 'warning'),
      ]),
      element('p', { text: data.active_strategy ? `当前版本 ${data.active_strategy}` : '当前没有可用于生产排名的策略。系统不会回退到旧权重。' }),
      button('查看机会页', 'button secondary', () => { window.location.hash = '#/opportunities'; }),
    ]);
    const queueCard = card([
      element('div', { className: 'card-header' }, [
        element('div', {}, [element('h2', { text: '分析入口' }), element('p', { text: '先冻结数据快照，再执行引擎计划与共识' })]),
        pill('Snapshot first', 'info'),
      ]),
      element('p', { text: '个股页面支持 standard 与 deep 两种档位，并展示持久化任务进度。' }),
      button('开始个股分析', 'button primary', () => { window.location.hash = '#/stock'; }),
    ]);
    stack.append(element('div', { className: 'grid two' }, [strategyCard, queueCard]));
    if (opportunity.total > 0) stack.append(opportunityTable(opportunity.items));
    root.replaceChildren(stack);
    state.phase = 'ready';
  } catch (error) {
    handlePageError(error);
  }
}

function stockSearchCard() {
  const input = element('input', { attrs: { type: 'search', placeholder: '输入六位代码或证券名称', autocomplete: 'off', 'aria-label': '证券搜索' } });
  const submit = button('查询证券', 'button primary');
  submit.type = 'submit';
  const form = element('form', { className: 'search-form' }, [input, submit]);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const query = input.value.trim();
    if (!query) return;
    submit.disabled = true;
    submit.textContent = '查询中';
    try {
      if (/^\d{6}$/.test(query)) {
        window.location.hash = `#/stock/${query}`;
        return;
      }
      const response = await api.search(query, 10);
      if (!response.data.items.length) throw new ApiError('INSTRUMENT_NOT_FOUND', '没有匹配证券', 404);
      window.location.hash = `#/stock/${response.data.items[0].symbol}`;
    } catch (error) {
      toast(error.message, true);
    } finally {
      submit.disabled = false;
      submit.textContent = '查询证券';
    }
  });
  return card([
    element('div', { className: 'card-header' }, [
      element('div', {}, [element('h2', { text: '选择分析标的' }), element('p', { text: '行情读取不会隐式启动分析任务' })]),
    ]),
    form,
  ]);
}

async function renderStock(symbol) {
  if (!symbol) {
    root.replaceChildren(element('div', { className: 'page-stack' }, [stockSearchCard(), stateMessage('输入证券代码后查看行情和分析入口。')]));
    return;
  }
  loadingState();
  try {
    const response = await api.quote(symbol);
    const quote = response.data;
    const stack = element('div', { className: 'page-stack' }, [stockSearchCard()]);
    const priceClass = quote.change_pct > 0 ? 'positive' : quote.change_pct < 0 ? 'negative' : '';
    const actions = element('div', { className: 'button-row' });
    actions.append(
      button('标准分析', 'button primary', () => startAnalysis(symbol, 'standard', stack)),
      button('深度分析', 'button secondary', () => startAnalysis(symbol, 'deep', stack)),
    );
    stack.append(card([
      element('div', { className: 'quote-hero' }, [
        element('div', {}, [
          element('div', { className: 'quote-symbol', text: quote.symbol }),
          element('h2', { className: 'quote-name', text: quote.name || quote.symbol }),
          element('div', { className: `quote-price ${priceClass}`.trim(), text: `${formatNumber(quote.price, 2)}  ${signed(quote.change_pct)}%` }),
        ]),
        actions,
      ]),
      element('div', { className: 'grid metrics', attrs: { style: 'margin-top:24px' } }, [
        metric('开盘', formatNumber(quote.open, 2), `最高 ${formatNumber(quote.high, 2)}`),
        metric('最低', formatNumber(quote.low, 2), `成交量 ${formatCompact(quote.volume)}`),
        metric('市盈率', nullableNumber(quote.pe), `市净率 ${nullableNumber(quote.pb)}`),
        metric('数据来源', quote.source, response.meta.cache ? `${response.meta.cache.state} / ${response.meta.cache.level}` : 'upstream'),
      ]),
      element('p', { className: 'freshness', text: freshnessText(response.meta) }),
    ]));
    root.replaceChildren(stack);
    state.phase = 'ready';
  } catch (error) {
    handlePageError(error);
  }
}

async function startAnalysis(symbol, profile, stack) {
  if (!state.authenticated) {
    openLogin();
    toast('分析任务需要 Owner 会话');
    return;
  }
  if (!csrfToken()) {
    openLogin();
    toast('当前标签页缺少 CSRF 凭据，请重新登录', true);
    return;
  }
  const epoch = state.pageEpoch;
  const panel = card([], 'analysis-panel');
  panel.append(element('div', { className: 'card-header' }, [
    element('div', {}, [element('h2', { text: `${profile} 分析任务` }), element('p', { text: '任务已进入有界持久化队列' })]),
    pill('Queued', 'info'),
  ]));
  const progress = element('div', { className: 'progress-value', attrs: { style: 'width:0%' } });
  const status = element('p', { className: 'freshness', text: '正在提交任务' });
  panel.append(element('div', { className: 'progress-track' }, progress), status);
  stack.append(panel);
  try {
    const created = await api.createAnalysis(symbol, profile);
    const jobId = created.data.job_id;
    const cancel = button('取消任务', 'button danger', async () => {
      cancel.disabled = true;
      try { await api.cancelJob(jobId); } catch (error) { toast(error.message, true); }
    });
    panel.append(element('div', { className: 'button-row', attrs: { style: 'margin-top:16px' } }, cancel));
    for (let attempt = 0; attempt < 240 && state.pageEpoch === epoch; attempt += 1) {
      const response = await api.job(jobId);
      const job = response.data;
      progress.style.width = `${Math.max(2, job.progress * 100)}%`;
      status.textContent = `${job.status} · ${Math.round(job.progress * 100)}% · ${job.job_id}`;
      if (job.status === 'succeeded') {
        cancel.remove();
        const run = await api.analysis(job.result_ref);
        panel.replaceChildren(analysisResult(run.data));
        return;
      }
      if (['failed', 'cancelled', 'interrupted'].includes(job.status)) {
        throw new ApiError(job.error_code || 'ANALYSIS_FAILED', '分析任务未完成', 409);
      }
      await delay(750);
    }
  } catch (error) {
    panel.replaceChildren(stateMessage(`${error.code || 'ANALYSIS_FAILED'} · ${error.message}`));
  }
}

function analysisResult(run) {
  const wrapper = element('div');
  const score = run.consensus?.analysis_score;
  wrapper.append(element('div', { className: 'card-header' }, [
    element('div', {}, [element('h2', { text: '分析已持久化' }), element('p', { text: `${run.run_id} · ${run.snapshot_hash}` })]),
    pill(run.status, run.status === 'succeeded' ? 'success' : 'warning'),
  ]));
  wrapper.append(element('div', { className: 'grid metrics' }, [
    metric('共识评分', score === null || score === undefined ? '证据不足' : formatNumber(score, 1), run.consensus?.insufficient_reason || 'weighted consensus'),
    metric('置信度', run.consensus ? `${Math.round(run.consensus.confidence * 100)}%` : '—', `覆盖率 ${run.consensus ? Math.round(run.consensus.weight_coverage * 100) : 0}%`),
    metric('分析档位', run.profile, `${run.engine_runs.length} 个引擎运行记录`),
    metric('策略版本', run.strategy_version, run.code_version),
  ]));
  wrapper.append(engineTable(run.engine_runs));
  if (run.verdict) wrapper.append(card([element('h3', { text: run.verdict.label }), element('p', { text: run.verdict.summary })], 'compact'));
  return wrapper;
}

function engineTable(runs) {
  const table = element('table');
  const head = element('thead', {}, element('tr', {}, ['引擎', '状态', '评分', '置信度', '耗时'].map((value) => element('th', { text: value }))));
  const body = element('tbody');
  for (const run of runs) {
    body.append(element('tr', {}, [
      element('td', {}, element('strong', { text: `${run.engine_name} ${run.engine_version}` })),
      element('td', {}, pill(run.status, run.status === 'succeeded' ? 'success' : 'warning')),
      element('td', { text: run.engine_score ?? '—' }),
      element('td', { text: run.confidence === null ? '—' : `${Math.round(run.confidence * 100)}%` }),
      element('td', { text: `${run.duration_ms} ms` }),
    ]));
  }
  table.append(head, body);
  return element('div', { className: 'table-wrap', attrs: { style: 'margin-top:20px' } }, table);
}

async function renderOpportunities() {
  loadingState();
  try {
    const response = await api.opportunities();
    const data = response.data;
    if (!data.items.length) {
      const warning = response.meta.warnings?.[0];
      statePanel('empty', '暂无可用机会榜', warning ? `${warning.code} · ${warning.message}` : '当前策略没有返回机会。');
      return;
    }
    root.replaceChildren(element('div', { className: 'page-stack' }, [
      card([element('div', { className: 'card-header' }, [
        element('div', {}, [element('h2', { text: data.strategy_version }), element('p', { text: '所有结果可追溯到策略、因子和数据日期' })]),
        pill('Active', 'success'),
      ])]),
      opportunityTable(data.items),
    ]));
  } catch (error) {
    handlePageError(error);
  }
}

function opportunityTable(items) {
  const table = element('table');
  table.append(element('thead', {}, element('tr', {}, ['排名', '证券', '评分', '数据日期', '证据'].map((value) => element('th', { text: value })))));
  const body = element('tbody');
  for (const item of items) {
    body.append(element('tr', {}, [
      element('td', {}, element('strong', { text: item.rank })),
      element('td', {}, [element('strong', { text: item.name }), element('div', { className: 'freshness', text: item.symbol })]),
      element('td', { text: formatNumber(item.screening_score, 2) }),
      element('td', { text: item.data_date }),
      element('td', { text: item.evidence.join(' · ') || '—' }),
    ]));
  }
  table.append(body);
  return card(element('div', { className: 'table-wrap' }, table));
}

async function renderWatchlist() {
  if (!state.authenticated) {
    authRequired();
    return;
  }
  loadingState();
  try {
    const response = await api.watchlist();
    const items = response.data.items;
    const stack = element('div', { className: 'page-stack' });
    stack.append(element('div', { className: 'section-heading' }, [
      element('div', {}, [element('h2', { text: 'Owner 自选证券' }), element('p', { text: '业务状态持久化在 diting.db' })]),
      button('添加证券', 'button primary', openWatchlistDialog),
    ]));
    if (!items.length) {
      stack.append(stateMessage('自选列表为空。添加证券后可从此处快速进入分析。'));
    } else {
      const table = element('table');
      table.append(element('thead', {}, element('tr', {}, ['证券', '市场', '标签', '更新时间', ''].map((value) => element('th', { text: value })))));
      const body = element('tbody');
      for (const item of items) {
        const remove = button('移除', 'button ghost');
        remove.addEventListener('click', async () => {
          remove.disabled = true;
          try {
            await api.removeWatchlist(item.symbol);
            toast(`${item.symbol} 已移除`);
            await renderWatchlist();
          } catch (error) {
            remove.disabled = false;
            toast(error.message, true);
          }
        });
        body.append(element('tr', {}, [
          element('td', {}, [element('strong', { text: item.name || item.symbol }), element('div', { className: 'freshness', text: item.symbol })]),
          element('td', { text: item.market }),
          element('td', { text: item.tags.join(' · ') || '—' }),
          element('td', { text: formatDateTime(item.updated_at) }),
          element('td', {}, remove),
        ]));
      }
      table.append(body);
      stack.append(card(element('div', { className: 'table-wrap' }, table)));
    }
    root.replaceChildren(stack);
  } catch (error) {
    handlePageError(error);
  }
}

function openWatchlistDialog() {
  if (!csrfToken()) {
    openLogin();
    toast('请重新登录以获取当前标签页的 CSRF 凭据');
    return;
  }
  const dialog = element('dialog', { className: 'modal' });
  const symbol = element('input', { attrs: { name: 'symbol', pattern: '\\d{6}', maxlength: '6', required: '', autocomplete: 'off' } });
  const name = element('input', { attrs: { name: 'name', maxlength: '80', autocomplete: 'off' } });
  const market = element('select', { attrs: { name: 'market' } }, ['SZ', 'SH', 'BJ'].map((value) => element('option', { text: value, attrs: { value } })));
  const save = button('保存', 'button primary');
  save.type = 'submit';
  const form = element('form', {}, [
    element('div', { className: 'modal-heading' }, [element('h2', { text: '添加自选证券' }), button('关闭', 'button ghost', () => dialog.close())]),
    element('label', { className: 'field' }, [element('span', { text: '六位代码' }), symbol]),
    element('label', { className: 'field', attrs: { style: 'margin-top:14px' } }, [element('span', { text: '名称（可选）' }), name]),
    element('label', { className: 'field', attrs: { style: 'margin-top:14px' } }, [element('span', { text: '市场' }), market]),
    element('div', { className: 'modal-actions' }, save),
  ]);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const submit = form.querySelector('.button.primary');
    submit.disabled = true;
    try {
      await api.addWatchlist({ symbol: symbol.value, name: name.value, market: market.value, tags: [] });
      dialog.close();
      toast(`${symbol.value} 已加入自选`);
      await renderWatchlist();
    } catch (error) {
      submit.disabled = false;
      toast(error.message, true);
    }
  });
  dialog.append(form);
  document.body.append(dialog);
  dialog.addEventListener('close', () => dialog.remove(), { once: true });
  dialog.showModal();
  symbol.focus();
}

async function renderSettings() {
  if (!state.authenticated) {
    authRequired();
    return;
  }
  loadingState();
  try {
    const [preferences, strategy, diagnostics] = await Promise.all([api.preferences(), api.strategy(), api.diagnostics()]);
    const values = Object.fromEntries(preferences.data.items.map((item) => [item.key, item.value]));
    const form = element('form', { className: 'settings-form' });
    const theme = selectField('界面主题', 'theme', ['light', 'dark'], values.theme || 'light');
    const profile = selectField('默认分析档位', 'default_profile', ['standard', 'deep'], values.default_profile || 'standard');
    const pageSize = element('input', { attrs: { type: 'number', min: '10', max: '100', value: String(values.page_size || 20) } });
    form.append(theme.label, profile.label, element('label', { className: 'field' }, [element('span', { text: '每页条目' }), pageSize]));
    const save = button('保存偏好', 'button primary');
    save.type = 'submit';
    form.append(save);
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      save.disabled = true;
      try {
        await Promise.all([
          api.savePreference('theme', theme.select.value),
          api.savePreference('default_profile', profile.select.value),
          api.savePreference('page_size', Number(pageSize.value)),
        ]);
        window.localStorage.setItem('diting_theme', theme.select.value);
        document.documentElement.dataset.theme = theme.select.value;
        toast('偏好已保存');
      } catch (error) {
        toast(error.message, true);
      } finally {
        save.disabled = false;
      }
    });
    const clear = button('清理可丢弃缓存', 'button danger', async () => {
      clear.disabled = true;
      try {
        const response = await api.clearCache();
        toast(`已清理 ${response.data.cleared} 个缓存条目`);
      } catch (error) {
        toast(error.message, true);
      } finally {
        clear.disabled = false;
      }
    });
    const settingsCard = card([
      element('div', { className: 'card-header' }, [element('div', {}, [element('h2', { text: '个人偏好' }), element('p', { text: '仅允许白名单设置项' })])]),
      form,
    ]);
    const opsCard = card([
      element('div', { className: 'card-header' }, [element('div', {}, [element('h2', { text: '运行状态' }), element('p', { text: '脱敏诊断不会暴露密钥或堆栈' })]), pill(strategy.data.active ? 'Active' : 'Unavailable', strategy.data.active ? 'success' : 'warning')]),
      definitionList({
        '版本': diagnostics.data.version,
        '环境': diagnostics.data.environment,
        '公开读取': String(diagnostics.data.public_readonly),
        '分析服务': String(diagnostics.data.analysis_available),
        '任务服务': String(diagnostics.data.jobs_available),
        '缓存服务': String(diagnostics.data.cache_available),
        '选定策略': strategy.data.version ? `${strategy.data.selected}:${strategy.data.version}` : `${strategy.data.selected}（未激活）`,
      }),
      element('div', { attrs: { style: 'margin-top:20px' } }, clear),
    ]);
    root.replaceChildren(element('div', { className: 'settings-layout' }, [
      element('aside', { className: 'settings-nav' }, [element('strong', { text: 'Owner controls' }), element('span', { text: '偏好、策略、缓存与诊断统一受会话保护。' })]),
      element('div', { className: 'page-stack' }, [settingsCard, opsCard]),
    ]));
  } catch (error) {
    handlePageError(error);
  }
}

function selectField(labelText, name, values, selectedValue) {
  const select = element('select', { attrs: { name } }, values.map((value) => element('option', { text: value, attrs: { value } })));
  select.value = selectedValue;
  return { select, label: element('label', { className: 'field' }, [element('span', { text: labelText }), select]) };
}

function definitionList(values) {
  const list = element('dl', { className: 'definition-list' });
  for (const [key, value] of Object.entries(values)) list.append(element('dt', { text: key }), element('dd', { text: value }));
  return list;
}

function stateMessage(copy) {
  return element('section', { className: 'card state-panel' }, element('div', {}, [svgIcon('activity', 'state-icon'), element('p', { text: copy })]));
}

async function refreshSession() {
  try {
    const response = await api.session();
    state.authenticated = response.data.authenticated;
    state.authConfigured = response.data.configured;
  } catch (error) {
    state.authenticated = false;
    if (error instanceof ApiError && error.code === 'AUTH_NOT_CONFIGURED') state.authConfigured = false;
  }
  updateAuthUi();
}

function updateAuthUi() {
  authState.textContent = state.authenticated ? 'Owner 会话' : '访客只读';
  authButton.textContent = state.authenticated ? '退出' : 'Owner 登录';
}

function openLogin() {
  if (!state.authConfigured) {
    toast('Owner 认证尚未配置', true);
    return;
  }
  loginError.textContent = '';
  tokenInput.value = '';
  loginDialog.showModal();
  tokenInput.focus();
}

loginForm.addEventListener('submit', async (event) => {
  const submitter = event.submitter;
  if (submitter?.value === 'cancel') return;
  event.preventDefault();
  const submit = document.getElementById('login-submit');
  submit.disabled = true;
  submit.textContent = '校验中';
  loginError.textContent = '';
  try {
    await api.login(tokenInput.value);
    state.authenticated = true;
    updateAuthUi();
    loginDialog.close();
    toast('Owner 会话已建立');
    await renderRoute();
  } catch (error) {
    loginError.textContent = `${error.code || 'LOGIN_FAILED'} · ${error.message}`;
  } finally {
    submit.disabled = false;
    submit.textContent = '建立安全会话';
    tokenInput.value = '';
  }
});

loginForm.querySelectorAll('[value="cancel"]').forEach((control) => {
  control.addEventListener('click', (event) => {
    event.preventDefault();
    loginDialog.close();
  });
});

authButton.addEventListener('click', async () => {
  if (!state.authenticated) {
    openLogin();
    return;
  }
  if (!csrfToken()) {
    clearCsrf();
    state.authenticated = false;
    updateAuthUi();
    openLogin();
    toast('请重新登录后注销当前会话', true);
    return;
  }
  try {
    await api.logout();
    state.authenticated = false;
    updateAuthUi();
    toast('已退出 Owner 会话');
    await renderRoute();
  } catch (error) {
    toast(error.message, true);
  }
});

function toast(message, isError = false) {
  const region = document.getElementById('toast-region');
  const node = element('div', { className: `toast ${isError ? 'error' : ''}`.trim(), text: message });
  region.append(node);
  window.setTimeout(() => node.remove(), 4200);
}

function parseRoute() {
  const parts = window.location.hash.replace(/^#\/?/, '').split('/').filter(Boolean);
  const route = pageMeta[parts[0]] ? parts[0] : 'dashboard';
  return { route, parameter: parts[1] || null };
}

async function renderRoute() {
  const { route, parameter } = parseRoute();
  setPage(route);
  if (route === 'dashboard') await renderDashboard();
  if (route === 'stock') await renderStock(parameter);
  if (route === 'opportunities') await renderOpportunities();
  if (route === 'watchlist') await renderWatchlist();
  if (route === 'settings') await renderSettings();
  root.focus({ preventScroll: true });
}

function formatNumber(value, digits = 0) {
  return Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : '—';
}

function nullableNumber(value) {
  return value === null || value === undefined ? '—' : formatNumber(value, 2);
}

function signed(value) {
  const number = Number(value || 0);
  return `${number >= 0 ? '+' : ''}${number.toFixed(2)}`;
}

function formatCompact(value) {
  return new Intl.NumberFormat('zh-CN', { notation: 'compact', maximumFractionDigits: 1 }).format(value || 0);
}

function formatDateTime(value) {
  if (!value) return '—';
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
}

function freshnessText(meta) {
  if (!meta.freshness?.data_time) return '数据时间不可用';
  const sources = meta.freshness.sources?.join(', ') || 'unknown';
  return `数据时间 ${formatDateTime(meta.freshness.data_time)} · ${sources}`;
}

function delay(milliseconds) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

function installIcons() {
  document.querySelectorAll('[data-icon]').forEach((node) => node.replaceChildren(svgIcon(node.dataset.icon)));
}

async function checkHealth() {
  const indicator = document.getElementById('system-indicator');
  const label = document.getElementById('system-label');
  try {
    await api.health();
    indicator.className = 'system-dot online';
    label.textContent = '服务正常';
  } catch (_error) {
    indicator.className = 'system-dot offline';
    label.textContent = '连接失败';
  }
}

window.addEventListener('hashchange', renderRoute);
document.documentElement.dataset.theme = window.localStorage.getItem('diting_theme') || 'light';
installIcons();
await Promise.all([refreshSession(), checkHealth()]);
await renderRoute();
