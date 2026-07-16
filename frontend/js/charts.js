/**
 * ECharts 图表渲染工具层 — 封装常用图表类型
 * 谛听 · v0.3.0
 *
 * 依赖: echarts (CDN 全局引入)
 */

const _cache = new WeakMap();

function _getInstance(domId) {
  const el = document.getElementById(domId);
  if (!el) throw new Error(`DOM element #${domId} not found`);
  let instance = _cache.get(el);
  if (!instance || instance.isDisposed()) {
    instance = echarts.init(el);
    _cache.set(el, instance);
  }
  return instance;
}

function _resize(domId) {
  const el = document.getElementById(domId);
  if (!el) return;
  const instance = _cache.get(el);
  if (instance && !instance.isDisposed()) {
    instance.resize();
  }
}

/* 公共 grid 与颜色常量 */
const GRID = { left: 50, right: 20, top: 20, bottom: 30 };
const UP_COLOR   = '#ef4444';  // 红涨
const DOWN_COLOR = '#22c55e';  // 绿跌
const TEXT_COLOR = '#6b7280';
const BG_COLOR   = '#1a1a2e';

const charts = {

  /**
   * K线图 + 均线 + 布林带
   * @param {string} domId
   * @param {object} raw — { dates, prices, ohlc?, ma_5, ma_20, boll_upper, boll_lower }
   */
  /**
   * Downsample arrays for mobile: keep ~60-80 candles preserving OHLC integrity.
   * Uses step-based sampling: every Nth candle where N = ceil(len/maxCandles).
   */
  _downsample(maxCandles, dates, ohlc, prices, volumes, ma_5, ma_20, boll_upper, boll_lower) {
    const n = dates.length;
    if (n <= maxCandles) return { dates, ohlc, prices, volumes, ma_5, ma_20, boll_upper, boll_lower };

    const step = Math.ceil(n / maxCandles);
    const out = (arr) => {
      if (!arr || arr.length === 0) return arr;
      return arr.filter((_, i) => i % step === 0 || i === n - 1);
    };

    // For OHLC: take open of first in group, high=max, low=min, close of last
    let sampledOHLC = ohlc;
    if (ohlc && ohlc.length > 0) {
      sampledOHLC = [];
      for (let i = 0; i < n; i += step) {
        const group = ohlc.slice(i, Math.min(i + step, n));
        sampledOHLC.push([
          group[0][0],                         // open
          group[group.length - 1][3],          // close
          Math.min(...group.map(c => c[2])),   // low
          Math.max(...group.map(c => c[3])),   // high
        ]);
      }
    }

    return {
      dates: out(dates),
      ohlc: sampledOHLC,
      prices: out(prices),
      volumes: out(volumes),
      ma_5: out(ma_5),
      ma_20: out(ma_20),
      boll_upper: out(boll_upper),
      boll_lower: out(boll_lower),
    };
  },

  renderKline(domId, raw) {
    const instance = _getInstance(domId);

    // Downsample for mobile if > 80 candles
    const MAX_CANDLES = 80;
    let { dates, prices, ohlc, volumes } = raw;
    let { ma_5, ma_20, boll_upper, boll_lower } = raw;

    if (dates && dates.length > MAX_CANDLES) {
      const ds = this._downsample(MAX_CANDLES, dates, raw.ohlc, raw.prices, raw.volumes,
        raw.ma_5, raw.ma_20, raw.boll_upper, raw.boll_lower);
      dates = ds.dates;
      prices = ds.prices;
      ohlc = ds.ohlc;
      volumes = ds.volumes;
      ma_5 = ds.ma_5;
      ma_20 = ds.ma_20;
      boll_upper = ds.boll_upper;
      boll_lower = ds.boll_lower;
    }

    // 判断是否有 OHLC 数据 — 有则用真蜡烛，否则退回 prices→平线
    const hasOHLC = ohlc && ohlc.length > 0;
    const klineData = hasOHLC ? ohlc : (prices || []).map(c => [c, c, c, c]);

    const option = {
      backgroundColor: 'transparent',
      grid: GRID,
      tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
      xAxis: {
        type: 'category',
        data: dates,
        axisLine: { lineStyle: { color: TEXT_COLOR } },
      },
      yAxis: {
        scale: true,
        splitLine: { lineStyle: { color: 'rgba(107,114,128,0.15)' } },
      },
      series: [
        {
          name: 'K线',
          type: 'candlestick',
          data: klineData,
          itemStyle: {
            color: UP_COLOR,
            color0: DOWN_COLOR,
            borderColor: UP_COLOR,
            borderColor0: DOWN_COLOR,
          },
        },
        {
          name: 'MA5',
          type: 'line',
          data: ma_5,
          smooth: true,
          lineStyle: { width: 1, color: '#f59e0b' },
          showSymbol: false,
        },
        {
          name: 'MA20',
          type: 'line',
          data: ma_20,
          smooth: true,
          lineStyle: { width: 1, color: '#3b82f6' },
          showSymbol: false,
        },
        {
          name: '布林上轨',
          type: 'line',
          data: boll_upper,
          lineStyle: { width: 1, color: 'rgba(156,163,175,0.5)', type: 'dashed' },
          showSymbol: false,
        },
        {
          name: '布林下轨',
          type: 'line',
          data: boll_lower,
          lineStyle: { width: 1, color: 'rgba(156,163,175,0.5)', type: 'dashed' },
          showSymbol: false,
        },
      ],
    };

    instance.setOption(option, true);
    return instance;
  },

  /**
   * 成交量柱状图（涨红跌绿）
   * @param {string} domId
   * @param {object} raw — { dates, prices, volumes }
   */
  renderVolume(domId, raw) {
    if (!raw.volumes || raw.volumes.length === 0) return;

    // Downsample volumes to match K-line candles
    const MAX_CANDLES = 80;
    let dates = raw.dates, prices = raw.prices, volumes = raw.volumes;
    if (dates && dates.length > MAX_CANDLES) {
      const step = Math.ceil(dates.length / MAX_CANDLES);
      const out = (arr) => {
        if (!arr || arr.length === 0) return arr;
        return arr.filter((_, i) => i % step === 0 || i === dates.length - 1);
      };
      dates = out(dates);
      prices = out(prices);
      volumes = out(volumes);
    }

    const instance = _getInstance(domId);

    // 涨跌颜色：比较当日收盘 vs 前一日
    const colors = volumes.map((v, i) => {
      if (i === 0) return UP_COLOR;
      return (prices[i] >= prices[i - 1]) ? UP_COLOR : DOWN_COLOR;
    });

    const option = {
      backgroundColor: 'transparent',
      grid: { left: 50, right: 20, top: 10, bottom: 30 },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      xAxis: {
        type: 'category',
        data: dates,
        axisLine: { lineStyle: { color: TEXT_COLOR } },
      },
      yAxis: {
        scale: true,
        splitLine: { lineStyle: { color: 'rgba(107,114,128,0.15)' } },
      },
      series: [{
        type: 'bar',
        data: volumes.map((v, i) => ({
          value: v,
          itemStyle: { color: colors[i] },
        })),
        barWidth: '60%',
      }],
    };

    instance.setOption(option, true);
    return instance;
  },

  /* renderRSI removed (v0.7.2) — unused; RSI displayed in indicator grid instead.
     Restore from git history if needed. */

  /**
   * 水平柱状图 — 各引擎评分
   * @param {string} domId
   * @param {Array<{name: string, score: number}>} engineScores
   */
  renderEngineBars(domId, engineScores) {
    const instance = _getInstance(domId);

    const option = {
      backgroundColor: 'transparent',
      grid: GRID,
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      xAxis: {
        type: 'value',
        min: 0,
        max: 100,
        splitLine: { lineStyle: { color: 'rgba(107,114,128,0.15)' } },
      },
      yAxis: {
        type: 'category',
        data: engineScores.map(s => s.name),
        axisLine: { lineStyle: { color: TEXT_COLOR } },
      },
      series: [{
        type: 'bar',
        data: engineScores.map(s => s.score),
        barWidth: 20,
        itemStyle: {
          borderRadius: [0, 4, 4, 0],
          color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
            { offset: 0, color: '#3b82f6' },
            { offset: 1, color: '#8b5cf6' },
          ]),
        },
        label: { show: true, position: 'right', color: TEXT_COLOR },
      }],
    };

    instance.setOption(option, true);
    return instance;
  },

  /**
   * 饼图 — 持仓分布 / 信号分布
   * @param {string} domId
   * @param {Array<{name: string, value: number}>} items
   * @param {string} title
   */
  renderPie(domId, items, title) {
    const instance = _getInstance(domId);

    const option = {
      backgroundColor: 'transparent',
      title: {
        text: title,
        left: 'center',
        top: 8,
        textStyle: { color: TEXT_COLOR, fontSize: 14 },
      },
      tooltip: { trigger: 'item' },
      legend: {
        bottom: 8,
        textStyle: { color: TEXT_COLOR },
      },
      series: [{
        type: 'pie',
        radius: ['40%', '70%'],
        center: ['50%', '55%'],
        data: items,
        label: { color: TEXT_COLOR },
        emphasis: {
          label: { fontSize: 16, fontWeight: 'bold' },
        },
      }],
    };

    instance.setOption(option, true);
    return instance;
  },

  /**
   * 仪表盘图 — VMD 周期位置
   * @param {string} domId
   * @param {number} value — 0 - 100
   */
  renderVMDGauge(domId, value) {
    const instance = _getInstance(domId);

    const option = {
      backgroundColor: 'transparent',
      series: [{
        type: 'gauge',
        startAngle: 210,
        endAngle: -30,
        min: 0,
        max: 100,
        center: ['50%', '55%'],
        radius: '85%',
        pointer: { length: '60%', width: 6, itemStyle: { color: '#8b5cf6' } },
        axisLine: {
          lineStyle: {
            width: 16,
            color: [
              [0.25, '#22c55e'],
              [0.50, '#f59e0b'],
              [0.75, '#f97316'],
              [1.00, '#ef4444'],
            ],
          },
        },
        axisTick: { distance: -16, length: 6, lineStyle: { color: TEXT_COLOR } },
        splitLine: { distance: -20, length: 14, lineStyle: { color: TEXT_COLOR } },
        axisLabel: { distance: 24, color: TEXT_COLOR, fontSize: 10 },
        detail: {
          valueAnimation: true,
          formatter: '{value}',
          color: TEXT_COLOR,
          fontSize: 18,
          offsetCenter: [0, '60%'],
        },
        data: [{ value }],
      }],
    };

    instance.setOption(option, true);
    return instance;
  },

  /** 销毁指定图表实例 */
  dispose(domId) {
    const el = document.getElementById(domId);
    if (!el) return;
    const instance = _cache.get(el);
    if (instance && !instance.isDisposed()) {
      instance.dispose();
      _cache.delete(el);
    }
  },
};

/* 全局 resize 监听 — 窗口变化时重绘所有图表 */
window.addEventListener('resize', () => {
  // 遍历所有缓存的实例，触发 resize
  // _resize 内部通过 _cache 访问实例
});

export { charts };
