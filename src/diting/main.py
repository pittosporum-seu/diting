"""谛听 · CLI 入口 — v0.7.1 命令框架重构

diting <code>          默认快速评估
diting <code> --more   详细技术分析
diting <code> --report 生成 HTML 报告
diting scan <code>     行情快照
"""

from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import click

from .config import Config
from .data.providers.akshare import AkShareProvider
from .data.providers.base import DataProvider
from .data.repository import MarketDataRepository
from .engines.registry import discover_engines
from .infra.config_loader import ConfigLoader
from .infra.errors import AllProvidersFailedError
from .infra.logging_config import get_logger, setup_logging
from .pipeline.consensus import ConsensusEngine
from .pipeline.runner import AnalysisPipeline
from .schema import AnalysisContext, PipelineResult

logger = get_logger(__name__)

# ── suppress LiteLLM debug noise ──────────────────────────────

os.environ.setdefault("LITELLM_LOG", "ERROR")

# ── helpers ──────────────────────────────────────────────────

_RATING_CN: dict[str, str] = {
    "strong_buy": "强烈买入",
    "buy": "建议买入",
    "accumulate": "建议关注",
    "hold": "建议观望",
    "reduce": "建议回避",
    "sell": "建议回避",
}

_RATING_EMOJI: dict[str, str] = {
    "strong_buy": "🟢",
    "buy": "🟢",
    "accumulate": "🟡",
    "hold": "⚪",
    "reduce": "🔴",
    "sell": "🔴",
}


def _build_repo(cfg: Config) -> MarketDataRepository:
    providers = []
    provider_configs = ConfigLoader.get_section("providers")
    for pc in provider_configs:
        name = pc.get("name", "")
        if not name:
            continue
        # 跳过要求 key 但未配置的
        requires_key = pc.get("requires_key", "")
        if requires_key and not cfg.get(requires_key):
            continue
        # 跳过 auto_detect 失败的
        if pc.get("auto_detect", False):
            try:
                provider = DataProvider.from_config(name, pc.get("settings"))
                if not provider.health_check():
                    continue
            except Exception:
                continue
        else:
            provider = DataProvider.from_config(name, pc.get("settings"))
        providers.append(provider)

    if not providers:
        providers.append(AkShareProvider())  # 兜底

    return MarketDataRepository(providers=providers)


def _log_level() -> int:
    raw = os.environ.get("DITING_LOG", "WARNING").upper()
    return getattr(logging, raw, logging.WARNING)


def _is_stock_code(s: str) -> bool:
    return len(s) == 6 and s.isdigit() and s not in {"000000", "999999"}


def _elapsed(start: float) -> str:
    ms = (time.monotonic() - start) * 1000
    if ms < 1000:
        return f"{ms:.0f}ms"
    return f"{ms / 1000:.1f}s"


def _rating_cn(rating) -> str:
    val = rating.value if hasattr(rating, "value") else str(rating)
    return _RATING_CN.get(val, val)


def _rating_emoji(rating) -> str:
    val = rating.value if hasattr(rating, "value") else str(rating)
    return _RATING_EMOJI.get(val, "")


def _color_change(pct: float | None) -> str:
    if pct is None:
        return "  -"
    if pct > 0:
        return click.style(f"+{pct:.2f}%", fg="green")
    if pct < 0:
        return click.style(f"{pct:.2f}%", fg="red")
    return click.style(" 0.00%", fg="white")


def _score_color(score: float) -> str:
    """Color a score string by threshold."""
    s = f"{score:.0f}"
    if score >= 75:
        return click.style(s, fg="green", bold=True)
    if score >= 55:
        return click.style(s, fg="yellow", bold=True)
    if score >= 35:
        return click.style(s, fg="white")
    return click.style(s, fg="red", bold=True)


def _parse_symbols(
    symbols: str | None, watchlist: str, cfg: Config
) -> list[str]:
    if symbols:
        return [s.strip() for s in symbols.split(",") if s.strip()]
    wl = cfg.load_watchlist(watchlist)
    if wl:
        return [row["code"] for row in wl if "code" in row]
    return []


def _err_friendly(exc: Exception) -> str:
    """Translate exceptions into user-friendly messages."""
    if isinstance(exc, AllProvidersFailedError):
        return "⚠️ 暂时无法获取数据，请稍后重试"
    msg = str(exc)
    # truncate overly long traceback-ish messages
    if len(msg) > 200:
        msg = msg[:200] + "…"
    return f"⚠️ {msg}"


# ── custom group: default <code> routing ──────────────────────


class _DitingGroup(click.Group):
    """Route `diting <stock_code>` to the default analysis command."""

    def resolve_command(self, ctx, args):
        if args and _is_stock_code(args[0]) and args[0] not in self.commands:
            cmd = self.get_command(ctx, "_default_code")
            return "_default_code", cmd, args
        return super().resolve_command(ctx, args)


# ── main group ───────────────────────────────────────────────


@click.group(
    cls=_DitingGroup,
    invoke_without_command=True,
    context_settings={
        "help_option_names": ["-h", "--help"],
        "auto_envvar_prefix": "DITING",
    },
)
@click.version_option(version="0.7.1", prog_name="diting")
@click.pass_context
def cli(ctx):
    """谛听 · A股多模型AI投资分析工具

    快速评估：  diting 002475
    详细分析：  diting 002475 --more
    生成报告：  diting 002475 --report
    行情快照：  diting scan 002475
    多股对比：  diting compare 002475,600519
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())
        return
    setup_logging(level=_log_level())


# ── default analysis (hidden, routed by _DitingGroup) ─────────


@cli.command(name="_default_code", hidden=True)
@click.argument("code")
@click.option("--more", is_flag=True, help="详细分析模式")
@click.option("--report", "gen_report", is_flag=True, help="生成 HTML 报告")
@click.option(
    "--engine", "-e", default=None, help="指定分析引擎（逗号分隔）"
)
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 格式输出")
@click.pass_context
def _default_code(ctx, code, more, gen_report, engine, json_output):
    """默认股票分析 — `diting <code>`"""
    _do_analyze(code, more=more, gen_report=gen_report, engine=engine,
                json_output=json_output)


def _do_analyze(
    code: str, *,
    more: bool = False,
    gen_report: bool = False,
    engine: str | None = None,
    json_output: bool = False,
) -> None:
    """Core analysis: realtime quote + consensus + optional signals / report."""
    t0 = time.monotonic()
    cfg = Config()

    # ── fetch realtime ──
    try:
        repo = _build_repo(cfg)
        quotes = repo.get_realtime([code])
    except Exception as e:
        click.echo(f"❌ 数据获取失败: {_err_friendly(e)}", err=True)
        return

    quote = quotes.get(code)
    if not quote:
        click.echo(f"❌ 未找到股票 {code}", err=True)
        return

    name = quote.name or code

    # ── JSON mode: raw data dump ──
    if json_output:
        data = {
            "symbol": quote.symbol,
            "name": name,
            "price": quote.price,
            "change_pct": quote.change_pct,
            "volume": quote.volume,
            "turnover": quote.turnover,
            "pe": quote.pe,
            "pb": quote.pb,
            "total_mv": quote.total_mv,
        }
        click.echo(json.dumps(data, ensure_ascii=False, indent=2))
        elapsed = _elapsed(t0)
        click.echo(f"\n⏱ 耗时: {elapsed}")
        return

    # ── fetch historical for technicals ──
    try:
        end = date.today()
        start = end - timedelta(days=120)
        historical = repo.get_historical(code, start, end)
    except Exception:
        historical = None

    # ── compute technical signals ──
    sig = None
    if historical and historical.df is not None:
        try:
            from .signals.technical import TechnicalCalculator
            sig = TechnicalCalculator.calculate(historical)
        except Exception:
            pass

    # ── compute VMD（引擎依赖，始终计算） ──
    vmd = None
    if historical and historical.df is not None:
        try:
            from .signals.vmd import VMDDecomposer

            df = historical.df
            close_col = None
            for c in ["close", "收盘", "收盘价"]:
                if c in df.columns:
                    close_col = c
                    break
            if close_col is not None:
                close_arr = df[close_col].values
                if close_arr.dtype == object:
                    close_arr = close_arr.astype(float)
                vmd = VMDDecomposer.decompose(close_arr, symbol=code)
        except Exception:
            pass

    # ── run analysis pipeline for consensus ──
    consensus = None
    bull_reasons: list[str] = []
    bear_reasons: list[str] = []

    if engine:
        engine_names = [e.strip() for e in engine.split(",")]
    else:
        engines_cfg = ConfigLoader.get_section("engines")
        engine_names = engines_cfg.get("default", discover_engines()[:3])

    ctx_obj = AnalysisContext(
        symbol=code, realtime=quote, historical=historical,
        signals=sig, vmd=vmd,
    )

    try:
        pipeline = AnalysisPipeline(engine_names=engine_names)
        result: PipelineResult = pipeline.run([ctx_obj])
        ce = ConsensusEngine()
        consensus = ce.fuse(code, result.results.get(code, []))

        # ── extract bull/bear reasons from engine narratives ──
        for r in result.results.get(code, []):
            if r.error or not r.narrative:
                continue
            narrative = r.narrative
            # Simple heuristic: split narrative into sentences, classify
            for sentence in narrative.replace("\n", " ").split("。"):
                s = sentence.strip()
                if not s:
                    continue
                low = s.lower()
                if any(w in low for w in ("看多", "买入", "超卖", "低估", "支撑",
                                          "金叉", "反弹", "触底", "低位", "价值",
                                          "增长", "成长", "流入", "放量", "突破")):
                    if len(bull_reasons) < 4:
                        short = s[:60] + ("…" if len(s) > 60 else "")
                        bull_reasons.append(short)
                elif any(w in low for w in ("看空", "卖出", "超买", "高估", "压力",
                                            "死叉", "回调", "高位", "泡沫", "流出",
                                            "缩量", "破位", "风险", "偏高")):
                    if len(bear_reasons) < 4:
                        short = s[:60] + ("…" if len(s) > 60 else "")
                        bear_reasons.append(short)
    except Exception:
        pass

    # ── fallback bull/bear from technicals ──
    if not bull_reasons and not bear_reasons and sig:
        if sig.rsi_14 < 30:
            bull_reasons.append("RSI 超卖 — 短期有修复动力")
        if sig.macd > sig.macd_signal_line:
            bull_reasons.append("MACD 金叉 — 短期趋势向好")
        if sig.rsi_14 > 70:
            bear_reasons.append("RSI 超买 — 短期回调风险")
        if sig.macd < sig.macd_signal_line:
            bear_reasons.append("MACD 死叉 — 短期趋势偏弱")
        if quote.pe and quote.pe > 100:
            bear_reasons.append("PE 偏高 — 估值压力较大")

    if not bull_reasons and not bear_reasons:
        bull_reasons.append("暂无明确信号")

    # ── 结论先行输出 ──
    click.echo()
    pct_str = _color_change(quote.change_pct)

    if consensus:
        rating_val = _rating_cn(consensus.rating)
        emoji = _rating_emoji(consensus.rating)
        score_display = _score_color(consensus.weighted_score)
        click.echo(
            f"  {quote.symbol} · {name}  "
            f"{pct_str}"
        )
        click.echo(f"  {emoji} {rating_val} · 评分 {score_display}/100")
    else:
        click.echo(f"  {quote.symbol} · {name}  {pct_str}")

    if bull_reasons and bull_reasons[0] != "暂无明确信号":
        click.echo("\n  📈 看多理由：")
        for i, reason in enumerate(bull_reasons[:3], 1):
            click.echo(f"     {chr(0x245F + i)}  {reason}")

    if bear_reasons:
        click.echo("\n  📉 看空理由：")
        for i, reason in enumerate(bear_reasons[:3], 1):
            click.echo(f"     {chr(0x245F + i)}  {reason}")

    # ── --more: detailed technical analysis ──
    if more:
        _show_more(code, quote, sig, vmd=vmd)

    # ── --report: HTML report ──
    if gen_report:
        _show_report(code, quote, repo, engine)

    elapsed = _elapsed(t0)
    click.echo(f"\n  ⏱ {elapsed}")


def _show_more(code: str, quote, sig=None, vmd=None) -> None:
    """Print detailed technical and fundamental panel."""

    # ── VMD label helper ──
    def _vmd_zone(pos: float) -> str:
        if pos < 0.2:
            return "谷底区 ✅"
        elif pos < 0.4:
            return "低位区 ✅"
        elif pos < 0.6:
            return "中位区"
        elif pos < 0.8:
            return "高位区 ⚠️"
        else:
            return "峰顶区 ⚠️"

    # ── technical signals ──
    click.echo("\n📊 技术面")
    if sig:
        rsi_label = "超卖 ⚠️" if sig.rsi_14 < 30 else (
            "超买 ⚠️" if sig.rsi_14 > 70 else "正常")
        macd_label = "金叉 ✅" if sig.macd > sig.macd_signal_line else "死叉"
        boll_label = "下轨" if sig.bollinger_position < 0.1 else (
            "上轨" if sig.bollinger_position > 0.9 else "中轨")

        click.echo(f"  RSI(14):     {sig.rsi_14:.1f}  {rsi_label}")
        click.echo(f"  MACD:        {sig.macd:.3f}  {macd_label}")
        click.echo(f"  KDJ-K/D/J:   {sig.kdj_k:.1f}/{sig.kdj_d:.1f}/{sig.kdj_j:.1f}")
        click.echo(f"  布林位置:     {sig.bollinger_position:.2f}  {boll_label}")
        click.echo(f"  量比:         {sig.volume_ratio:.2f}")
        if vmd:
            zone = _vmd_zone(vmd.cycle_position)
            click.echo(f"  VMD 位置:    {vmd.cycle_position:.2f}  {zone}")
    else:
        click.echo("  ⚠️ 无历史数据")

    # ── fundamentals ──
    click.echo("\n📈 基础数据")
    pe_str = f"{quote.pe:.1f}" if quote.pe else "-"
    pb_str = f"{quote.pb:.1f}" if quote.pb else "-"
    mv_str = f"{quote.total_mv / 1e8:.0f}亿" if quote.total_mv else "-"
    click.echo(f"  PE:      {pe_str}")
    click.echo(f"  PB:      {pb_str}")
    click.echo(f"  总市值:   {mv_str}")
    click.echo(f"  成交量:   {quote.volume:,}")
    click.echo(f"  成交额:   {quote.turnover:,.0f}")


def _extract_chart_arrays(df) -> dict:
    """Extract chart array data from historical DataFrame.

    Returns dict with keys: dates, prices, ma_5, ma_20, boll_upper,
    boll_lower, rsi_values. Each value is a list for JSON serialization.
    """
    import numpy as np

    # ── column discovery ──
    date_col = close_col = None
    for c in df.columns:
        cl = c.lower()
        if cl in ("date", "日期", "trade_date"):
            date_col = c
        elif cl in ("close", "收盘", "收盘价"):
            close_col = c

    if date_col is None or close_col is None:
        return {}

    dates = [str(d) for d in df[date_col].tolist()]
    close = df[close_col].values
    if close.dtype == object:
        close = close.astype(float)
    n = len(close)

    result: dict = {"dates": dates, "prices": close.tolist()}

    # MA5
    if n >= 5:
        result["ma_5"] = (
            df[close_col].astype(float).rolling(window=5).mean().tolist()
        )

    # MA20
    if n >= 20:
        result["ma_20"] = (
            df[close_col].astype(float).rolling(window=20).mean().tolist()
        )

    # Bollinger (20, 2)
    if n >= 20:
        roll = df[close_col].astype(float).rolling(window=20)
        middle = roll.mean()
        std = roll.std(ddof=1)
        result["boll_upper"] = (middle + 2 * std).tolist()
        result["boll_lower"] = (middle - 2 * std).tolist()

    # RSI(14)
    if n >= 15:
        diff = np.diff(close)
        gain = np.maximum(diff, 0)
        loss = np.maximum(-diff, 0)

        rsi = np.full(n, np.nan)
        avg_gain = float(np.mean(gain[:14]))
        avg_loss = float(np.mean(loss[:14]))
        rsi[14] = 100.0 if avg_loss == 0 else float(100 - 100 / (1 + avg_gain / avg_loss))

        for i in range(15, n):
            avg_gain = (avg_gain * 13 + gain[i - 1]) / 14
            avg_loss = (avg_loss * 13 + loss[i - 1]) / 14
            if avg_loss == 0:
                rsi[i] = 100.0
            else:
                rsi[i] = float(100 - 100 / (1 + avg_gain / avg_loss))

        result["rsi_values"] = rsi.tolist()

    return result


def _show_report(code: str, quote, repo, engine: str | None = None) -> None:
    """Generate and save HTML report."""
    click.echo("\n⏳ 生成报告中...")

    try:
        end = date.today()
        start = end - timedelta(days=250)
        historical = repo.get_historical(code, start, end)
    except Exception:
        historical = None

    # ── compute chart arrays from historical data ──
    chart_arrays: dict = {}
    if historical and historical.df is not None:
        try:
            chart_arrays = _extract_chart_arrays(historical.df)
        except Exception:
            pass

    # ── compute signals + VMD for engines ──
    sig = None
    if historical and historical.df is not None:
        try:
            from .signals.technical import TechnicalCalculator
            sig = TechnicalCalculator.calculate(historical)
        except Exception:
            pass

    vmd = None
    if historical and historical.df is not None:
        try:
            from .signals.vmd import VMDDecomposer
            df = historical.df
            close_col = None
            for c in ["close", "收盘", "收盘价"]:
                if c in df.columns:
                    close_col = c
                    break
            if close_col is not None:
                close_arr = df[close_col].values
                if close_arr.dtype == object:
                    close_arr = close_arr.astype(float)
                vmd = VMDDecomposer.decompose(close_arr, symbol=code)
        except Exception:
            pass

    # Determine engines
    if engine:
        engine_names = [e.strip() for e in engine.split(",")]
    else:
        engines_cfg = ConfigLoader.get_section("engines")
        engine_names = engines_cfg.get("default", discover_engines()[:3])

    ctx_obj = AnalysisContext(
        symbol=code, realtime=quote, historical=historical,
        signals=sig, vmd=vmd,
    )

    try:
        pipeline = AnalysisPipeline(engine_names=engine_names)
        result: PipelineResult = pipeline.run([ctx_obj])
    except Exception as e:
        click.echo(f"⚠️ 分析管道执行失败: {e}", err=True)
        return

    try:
        from .report.builder import ReportBuilder
        builder = ReportBuilder(level="L2")
        html = builder.build(result, chart_data={
            code: {
                "name": quote.name,
                "realtime_price": quote.price,
                "change_pct": quote.change_pct,
                **chart_arrays,
            }
        })
        path = Path(f"report-{code}.html")
        path.write_text(html, encoding="utf-8")
        click.echo(f"📄 报告已保存: {path}")
    except Exception as e:
        click.echo(f"⚠️ 报告生成失败: {e}", err=True)


# ── scan (原 l0) ─────────────────────────────────────────────


@cli.command()
@click.argument("codes")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 格式输出")
def scan(codes, json_output):
    """🔍 行情快照 — diting scan 002475 或 diting scan 002475,603659"""
    t0 = time.monotonic()
    cfg = Config()
    syms = [s.strip() for s in codes.split(",") if s.strip()]

    if not syms:
        click.echo("❌ 请指定股票代码", err=True)
        return

    try:
        repo = _build_repo(cfg)
        quotes = repo.get_realtime(syms)
    except Exception as e:
        click.echo(f"❌ 数据获取失败: {_err_friendly(e)}", err=True)
        return

    if not quotes:
        click.echo("❌ 无返回数据", err=True)
        return

    if json_output:
        data = []
        for q in quotes.values():
            data.append({
                "symbol": q.symbol, "name": q.name,
                "price": q.price, "change_pct": q.change_pct,
                "volume": q.volume, "turnover": q.turnover,
                "pe": q.pe, "pb": q.pb, "total_mv": q.total_mv,
            })
        click.echo(json.dumps(data, ensure_ascii=False, indent=2))
        elapsed = _elapsed(t0)
        click.echo(f"\n⏱ 耗时: {elapsed}")
        return

    click.echo()
    for q in quotes.values():
        name = q.name or q.symbol
        pct = q.change_pct
        if pct is not None:
            pct_str = click.style(f"{pct:+.2f}%", fg="green" if pct > 0
                                  else "red" if pct < 0 else "white")
        else:
            pct_str = "  -"
        vol_str = f"{q.volume / 1e4:.0f}万" if q.volume else "-"
        turnover_str = f"{q.turnover / 1e8:.1f}亿" if q.turnover else "-"

        elapsed = _elapsed(t0)
        click.echo(
            f"  {q.symbol:>6}  {name:<10}  {q.price:>8.2f}  {pct_str}  "
            f"量 {vol_str}  额 {turnover_str}   ⏱ {elapsed}"
        )


# ── hidden aliases (旧脚本兼容) ──────────────────────────────


@cli.command(name="l0", hidden=True)
@click.argument("codes")
@click.option("--json", "-j", "json_output", is_flag=True)
@click.pass_context
def l0_alias(ctx, codes, json_output):
    """[兼容] 旧版 L0 → 同 scan"""
    ctx.invoke(scan, codes=codes, json_output=json_output)


@cli.command(name="l1", hidden=True)
@click.argument("code")
@click.option("--more/--no-more", default=False)
@click.option("--engine", "-e", default=None)
@click.pass_context
def l1_alias(ctx, code, more, engine):
    """[兼容] 旧版 L1 → 同 diting <code> --more"""
    ctx.invoke(_default_code, code=code, more=more, engine=engine)


@cli.command(name="l2", hidden=True)
@click.argument("code")
@click.option("--engine", "-e", default=None)
@click.pass_context
def l2_alias(ctx, code, engine):
    """[兼容] 旧版 L2 → 同 diting <code> --report --more"""
    ctx.invoke(
        _default_code, code=code, gen_report=True, more=True, engine=engine,
    )


@cli.command(name="run", hidden=True)
@click.option("--symbols", "-s", help="股票代码，逗号分隔")
def run_alias(symbols):
    """[兼容] 旧版 run → 引导使用新命令"""
    click.echo("⚠️ 'diting run' 已废弃，请使用新命令:")
    click.echo("  diting <code>       快速评估")
    click.echo("  diting <code> --more 详细分析")
    click.echo("  diting scan <code>   行情快照")
    if symbols:
        code = symbols.split(",")[0].strip()
        click.echo(f"\n→ 为你跳转到: diting {code}")
        _do_analyze(code)


# ── compare + watchlist helpers ───────────────────────────────


@dataclass
class _StockSummary:
    """Lightweight stock summary for compare/watchlist."""
    symbol: str
    name: str
    price: float
    change_pct: float | None
    pe: float | None
    rsi: float | None
    vmd_position: float | None
    score: float
    rating: str   # Rating.value string


def _compute_quick_score(
    rsi: float | None,
    vmd_pos: float | None,
    pe: float | None = None,
    change_pct: float | None = None,
) -> float:
    """Quick technical score (0-100) without AI, mirrors VMDRSIEngine logic."""
    score = 50.0
    if rsi is not None:
        if rsi < 25:
            score += 20
        elif rsi < 35:
            score += 10
        elif rsi > 75:
            score -= 20
        elif rsi > 65:
            score -= 10
    if vmd_pos is not None:
        if vmd_pos < 0.2:
            score += 15
        elif vmd_pos > 0.8:
            score -= 15
    return max(0.0, min(100.0, score))


def _score_to_rating_str(score: float) -> str:
    if score >= 80:
        return "strong_buy"
    if score >= 65:
        return "buy"
    if score >= 50:
        return "accumulate"
    if score >= 35:
        return "hold"
    if score >= 20:
        return "reduce"
    return "sell"


def _compute_one_summary_from_quote(
    code: str, quote, repo: MarketDataRepository,
) -> _StockSummary | None:
    """Compute signals and score for one stock from a pre-fetched quote."""
    if quote is None:
        return None

    # ── historical + RSI ──
    rsi: float | None = None
    try:
        end = date.today()
        start = end - timedelta(days=120)
        historical = repo.get_historical(code, start, end)
    except Exception:
        historical = None

    if historical and historical.df is not None:
        try:
            from .signals.technical import TechnicalCalculator
            sig = TechnicalCalculator.calculate(historical)
            rsi = sig.rsi_14
        except Exception:
            pass

    # ── VMD ──
    vmd_pos: float | None = None
    if historical and historical.df is not None:
        try:
            from .signals.vmd import VMDDecomposer
            df = historical.df
            close_col = None
            for c in ["close", "收盘", "收盘价"]:
                if c in df.columns:
                    close_col = c
                    break
            if close_col is not None:
                close_arr = df[close_col].values
                if close_arr.dtype == object:
                    close_arr = close_arr.astype(float)
                vmd = VMDDecomposer.decompose(close_arr, symbol=code)
                vmd_pos = vmd.cycle_position
        except Exception:
            pass

    score = _compute_quick_score(rsi, vmd_pos, quote.pe, quote.change_pct)
    rating = _score_to_rating_str(score)

    return _StockSummary(
        symbol=code,
        name=quote.name or code,
        price=quote.price,
        change_pct=quote.change_pct,
        pe=quote.pe,
        rsi=rsi,
        vmd_position=vmd_pos,
        score=score,
        rating=rating,
    )


def _compute_stock_summaries(
    symbols: list[str], repo: MarketDataRepository,
) -> list[_StockSummary]:
    """Fetch realtime quotes in one batch, then historical+signals in parallel."""
    # ── batch realtime ──
    try:
        all_quotes = repo.get_realtime(symbols)
    except Exception:
        all_quotes = {}

    # ── parallel historical + signals ──
    results: list[_StockSummary] = []
    with ThreadPoolExecutor(max_workers=min(8, len(symbols))) as pool:
        futures = {
            pool.submit(
                _compute_one_summary_from_quote, s, all_quotes.get(s), repo,
            ): s
            for s in symbols
        }
        for future in as_completed(futures):
            sym = futures[future]
            try:
                summary = future.result()
                if summary:
                    results.append(summary)
                else:
                    logger.warning("compare.fetch_failed", symbol=sym)
            except Exception:
                logger.warning("compare.fetch_failed", symbol=sym)
    # Preserve input order for compare
    order = {s: i for i, s in enumerate(symbols)}
    results.sort(key=lambda x: order.get(x.symbol, 999))
    return results


# ── compare ───────────────────────────────────────────────────


@cli.command()
@click.argument("codes")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 格式输出")
def compare(codes, json_output):
    """🔄 对比多只股票 — diting compare 002475,600519"""
    t0 = time.monotonic()
    syms = [s.strip() for s in codes.split(",") if s.strip()]
    if not syms:
        click.echo("❌ 请指定股票代码", err=True)
        return

    cfg = Config()
    try:
        repo = _build_repo(cfg)
    except Exception as e:
        click.echo(f"❌ 初始化失败: {_err_friendly(e)}", err=True)
        return

    click.echo(f"\n⏳ 正在获取 {len(syms)} 只股票数据...")
    summaries = _compute_stock_summaries(syms, repo)

    if not summaries:
        click.echo("❌ 无返回数据", err=True)
        return

    if json_output:
        data = []
        for s in summaries:
            data.append({
                "symbol": s.symbol, "name": s.name,
                "price": s.price, "change_pct": s.change_pct,
                "pe": s.pe, "rsi": s.rsi,
                "vmd_position": s.vmd_position,
                "score": s.score, "rating": s.rating,
            })
        click.echo(json.dumps(data, ensure_ascii=False, indent=2))
        elapsed = _elapsed(t0)
        click.echo(f"\n⏱ 耗时: {elapsed}")
        return

    # ── format comparison table ──
    # Header row: empty label + stock names
    max_name = max(len(s.name) for s in summaries)
    col_width = max(max_name, 10) + 2

    header = " " * 12
    for s in summaries:
        header += f"{s.name:<{col_width}}"
    click.echo(header)

    # Score row
    score_row = click.style("评分", bold=True).ljust(12)
    for s in summaries:
        emoji = _rating_emoji(s.rating)
        cell = f"{s.score:.0f} {emoji}"
        score_row += f"{cell:<{col_width}}"
    click.echo(score_row)

    # Rating row
    rating_row = click.style("结论", bold=True).ljust(12)
    for s in summaries:
        cell = _rating_cn(s.rating)
        rating_row += f"{cell:<{col_width}}"
    click.echo(rating_row)

    # PE row
    pe_row = click.style("PE", bold=True).ljust(12)
    for s in summaries:
        cell = f"{s.pe:.1f}x" if s.pe else "  -"
        pe_row += f"{cell:<{col_width}}"
    click.echo(pe_row)

    # RSI row
    rsi_row = click.style("RSI(14)", bold=True).ljust(12)
    for s in summaries:
        cell = f"{s.rsi:.1f}" if s.rsi is not None else "  -"
        rsi_row += f"{cell:<{col_width}}"
    click.echo(rsi_row)

    # VMD row
    vmd_row = click.style("VMD 位置", bold=True).ljust(12)
    for s in summaries:
        cell = f"{s.vmd_position:.2f}" if s.vmd_position is not None else "  -"
        vmd_row += f"{cell:<{col_width}}"
    click.echo(vmd_row)

    # Change row
    chg_row = click.style("涨跌幅", bold=True).ljust(12)
    for s in summaries:
        cell = _color_change(s.change_pct)
        chg_row += f"{cell:<{col_width}}"
    click.echo(chg_row)

    elapsed = _elapsed(t0)
    click.echo(f"\n  ⏱ {elapsed}")


# ── watchlist ─────────────────────────────────────────────────


@cli.command()
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 格式输出")
@click.option(
    "--file", "-f", "watchlist_file", default=None,
    help="自选股 CSV 文件路径（默认 config/watchlist.csv）",
)
def watchlist(json_output, watchlist_file):
    """📋 自选股概览 — diting watchlist"""
    t0 = time.monotonic()
    cfg = Config()

    # ── load watchlist ──
    try:
        rows = cfg.load_watchlist(watchlist_file)
    except Exception as e:
        click.echo(f"❌ 加载自选股失败: {e}", err=True)
        return

    if not rows:
        click.echo("⚠️ 自选股列表为空", err=True)
        return

    syms = [row["code"] for row in rows if "code" in row]
    name_map = {row["code"]: row.get("name", row["code"]) for row in rows}

    # ── fetch all data in parallel ──
    try:
        repo = _build_repo(cfg)
    except Exception as e:
        click.echo(f"❌ 初始化失败: {_err_friendly(e)}", err=True)
        return

    click.echo(f"\n⏳ 正在获取 {len(syms)} 只自选股数据...")
    summaries = _compute_stock_summaries(syms, repo)

    if not summaries:
        click.echo("❌ 无返回数据", err=True)
        return

    # Override names from watchlist CSV
    for s in summaries:
        if s.symbol in name_map:
            s.name = name_map[s.symbol]

    # ── sort by score descending ──
    summaries.sort(key=lambda x: x.score, reverse=True)

    if json_output:
        data = []
        for s in summaries:
            data.append({
                "symbol": s.symbol, "name": s.name,
                "price": s.price, "change_pct": s.change_pct,
                "pe": s.pe, "rsi": s.rsi,
                "vmd_position": s.vmd_position,
                "score": s.score, "rating": s.rating,
            })
        click.echo(json.dumps(data, ensure_ascii=False, indent=2))
        elapsed = _elapsed(t0)
        click.echo(f"\n⏱ 耗时: {elapsed}")
        return

    # ── format output ──
    click.echo()
    for s in summaries:
        pct_str = _color_change(s.change_pct)
        emoji = _rating_emoji(s.rating)
        rating_label = _rating_cn(s.rating)
        score_display = _score_color(s.score)
        click.echo(
            f"  {s.name:<10}  {s.price:>8.2f}  {pct_str}  "
            f"{score_display} {emoji}  {rating_label}"
        )

    elapsed = _elapsed(t0)
    click.echo(f"\n  ⏱ {elapsed}")


# ── init ──────────────────────────────────────────────────────


@cli.command()
@click.option("--yes", "-y", is_flag=True, help="跳过交互，使用检测到的 MX_APIKEY")
@click.option("--mx-key", default=None, help="直接指定 MX_APIKEY")
@click.option("--ai-key", default=None, help="直接指定 AI_API_KEY")
def init(yes, mx_key, ai_key):
    """⚙️ 首次配置引导 — diting init"""
    _do_init(yes=yes, mx_key=mx_key, ai_key=ai_key)


def _do_init(
    *, yes: bool = False, mx_key: str | None = None, ai_key: str | None = None
) -> None:
    """Interactive first-time configuration wizard."""
    env_path = Path.cwd() / ".env"

    click.echo()
    click.echo("⚙️  谛听首次配置")
    click.echo()

    # ── Step 1: MX_APIKEY ──
    final_mx_key: str | None = None

    if mx_key:
        final_mx_key = mx_key
        click.echo("  MX_APIKEY 已通过 --mx-key 指定 ✓")
    else:
        # Check ~/.hermes/.env
        hermes_env = Path.home() / ".hermes" / ".env"
        if hermes_env.exists():
            detected_key = _read_env_value(hermes_env, "MX_APIKEY")
            if detected_key:
                if yes:
                    final_mx_key = detected_key
                    click.echo("  检测到 MX_APIKEY ✓  (--yes: 自动使用)")
                else:
                    click.echo(f"  检测到 MX_APIKEY ({hermes_env})")
                    choice = click.prompt(
                        "  是否使用？", type=click.Choice(["Y", "n"]),
                        default="Y", show_choices=False,
                        prompt_suffix=" [Y/n] ",
                    )
                    if choice == "Y":
                        final_mx_key = detected_key
                    else:
                        click.echo("  跳过 Hermes 配置。")

        if not final_mx_key:
            if yes:
                click.echo("  未检测到 MX_APIKEY，--yes 模式下跳过。")
            else:
                final_mx_key = click.prompt(
                    "  请输入 MX_APIKEY",
                    default="", show_default=False,
                )
                if not final_mx_key.strip():
                    final_mx_key = None
                    click.echo("  MX_APIKEY 未配置，将使用免费数据源。")

    # ── Step 2: AI_API_KEY ──
    final_ai_key: str | None = None

    if ai_key:
        final_ai_key = ai_key
        click.echo("  AI_API_KEY 已通过 --ai-key 指定 ✓")
    elif yes:
        click.echo("  AI_API_KEY: 跳过（--yes 模式）")
    else:
        choice = click.prompt(
            "  是否需要配置 AI API KEY（用于智能分析引擎）？",
            type=click.Choice(["y", "N"]),
            default="N", show_choices=False,
            prompt_suffix=" [y/N] ",
        )
        if choice == "y":
            final_ai_key = click.prompt(
                "  请输入 AI_API_KEY",
                default="", show_default=False,
            )
            if not final_ai_key.strip():
                final_ai_key = None

    # ── Step 3: Write .env ──
    click.echo()
    lines = _build_env_lines(
        mx_key=final_mx_key,
        ai_key=final_ai_key,
    )
    env_path.write_text("".join(lines), encoding="utf-8")
    click.echo(f"  配置已写入 {env_path}")

    # ── Step 4: Test connection ──
    click.echo()
    click.echo("  测试数据连接...")
    if final_mx_key:
        _test_connection(final_mx_key)
    else:
        click.echo("  ⚠️ 无 MX_APIKEY，跳过连接测试。")

    # ── Step 5: Summary ──
    click.echo()
    click.echo("✅ 配置完成！")
    mx_status = "configured" if final_mx_key else "not configured（使用免费数据源）"
    ai_status = "configured" if final_ai_key else "not configured（智能引擎将跳过）"
    click.echo(f"  MX_APIKEY:    {mx_status}")
    click.echo(f"  AI_API_KEY:   {ai_status}")
    click.echo()
    click.echo("  试试：diting 002475")


def _read_env_value(env_path: Path, key: str) -> str | None:
    """Read a KEY=VALUE from a .env file."""
    if not env_path.exists():
        return None
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip() == key:
                val = v.strip().strip('"').strip("'")
                return val if val else None
    return None


def _build_env_lines(
    mx_key: str | None, ai_key: str | None
) -> list[str]:
    """Build .env content lines."""
    lines = [
        "# 谛听 · 环境变量\n",
        "# 由 diting init 生成\n",
        "\n",
        "DITING_LEVEL=L1\n",
        "\n",
        f"MX_APIKEY={mx_key or ''}\n",
        f"AI_API_KEY={ai_key or ''}\n",
        "AI_MODEL=deepseek/deepseek-v4-pro\n",
        "\n",
        "# 沙箱\n",
        "SANDBOX_BACKEND=process\n",
        "SANDBOX_MEMORY_MB=512\n",
        "SANDBOX_TIMEOUT=60\n",
        "\n",
    ]
    return lines


def _test_connection(mx_key: str) -> None:
    """Test data provider connectivity with a known symbol."""
    try:
        from .data.providers.mx_data import MxDataProvider
        from .data.repository import MarketDataRepository

        repo = MarketDataRepository(
            providers=[MxDataProvider(api_key=mx_key)]
        )
        quotes = repo.get_realtime(["000001"])
        if quotes and "000001" in quotes:
            q = quotes["000001"]
            name = q.name or "000001"
            pct = q.change_pct or 0
            arrow = "↑" if pct > 0 else "↓" if pct < 0 else "→"
            click.echo(f"  ✅ 数据连接正常 — 000001 {name} {q.price:.2f} {arrow}")
        else:
            click.echo("  ⚠️ 数据连接成功但未返回 000001 数据")
    except Exception as e:
        click.echo(f"  ⚠️ 连接测试失败: {e}")
        click.echo("  MX_APIKEY 可能无效，但会继续。")


# ── serve ─────────────────────────────────────────────────────


@cli.command()
@click.option("--port", "-p", default=8080, help="服务端口")
@click.option("--host", "-h", default="127.0.0.1", help="绑定地址")
def serve(port, host):
    """🌐 启动 Web 版 — diting serve"""
    import uvicorn

    from .web.app import app

    click.echo("🐾 谛听 Web 服务启动中...")
    click.echo(f"   地址: http://{host}:{port}")
    click.echo("   按 Ctrl+C 停止")
    uvicorn.run(app, host=host, port=port, log_level="warning")


# ── entry ─────────────────────────────────────────────────────

if __name__ == "__main__":
    cli()
