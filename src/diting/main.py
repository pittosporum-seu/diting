"""谛听 · CLI 入口 — 六层架构全链路串接"""

import json
import logging
import os
from datetime import date, timedelta
from pathlib import Path

import click

from .config import Config
from .data.providers.akshare import AkShareProvider
from .data.providers.mx_data import MxDataProvider
from .data.repository import MarketDataRepository
from .engines.registry import discover_engines
from .infra.logging_config import get_logger, setup_logging
from .pipeline.runner import AnalysisPipeline
from .schema import AnalysisContext, PipelineResult

logger = get_logger(__name__)


def _build_repo(cfg: Config) -> MarketDataRepository:
    """构建数据仓库，按可用性降级"""
    providers = []
    mx_key = cfg.get("MX_APIKEY") or os.environ.get("MX_APIKEY")
    if mx_key:
        providers.append(MxDataProvider(api_key=mx_key))
    providers.append(AkShareProvider())
    return MarketDataRepository(providers=providers)


def _log_level() -> int:
    raw = os.environ.get("DITING_LOG", "WARNING").upper()
    return getattr(logging, raw, logging.WARNING)


@click.group()
@click.version_option(version="0.1.0", prog_name="diting")
def cli() -> None:
    """谛听 · A股多模型AI投资分析工具"""
    setup_logging(level=_log_level())


@cli.command()
@click.option("--symbols", "-s", help="股票代码，逗号分隔")
@click.option("--watchlist", "-w", default="config/watchlist.csv", help="自选股文件路径")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 格式输出")
def l0(symbols: str | None, watchlist: str, json_output: bool) -> None:
    """L0: 快速行情快照（无AI）"""
    cfg = Config()
    syms = _parse_symbols(symbols, watchlist, cfg)
    if not syms:
        click.echo("请指定 --symbols 或配置 watchlist.csv")
        return

    click.echo(f"L0: 获取行情快照 ({len(syms)} 只标的)")

    repo = _build_repo(cfg)

    try:
        quotes = repo.get_realtime(syms)
    except Exception as e:
        click.echo(f"✗ 数据获取失败: {e}")
        return

    if not quotes:
        click.echo("✗ 无返回数据")
        return

    if json_output:
        data = []
        for q in quotes.values():
            data.append({
                "symbol": q.symbol,
                "name": q.name,
                "price": q.price,
                "change_pct": q.change_pct,
                "volume": q.volume,
                "turnover": q.turnover,
                "pe": q.pe,
                "pb": q.pb,
                "total_mv": q.total_mv,
            })
        click.echo(json.dumps(data, ensure_ascii=False, indent=2))
        return

    # 表格输出
    header = (
        f"\n{'代码':>6} {'名称':10} {'最新价':>8} "
        f"{'涨跌幅':>6} {'成交量':>10} {'成交额':>12}"
    )
    click.echo(header)
    click.echo("-" * 55)
    for q in quotes.values():
        pct = f"{q.change_pct:+.2f}%" if q.change_pct else " -"
        click.echo(
            f"{q.symbol:>6} {q.name[:10]:10} {q.price:>8.2f} {pct:>6}"
            f" {q.volume:>10,} {q.turnover:>12,.0f}"
        )


@cli.command()
@click.option("--symbols", "-s", help="股票代码，逗号分隔")
@click.option("--watchlist", "-w", default="config/watchlist.csv", help="自选股文件路径")
@click.option("--engines", "-e", default="wyckoff,vmd_rsi", help="分析引擎，逗号分隔")
@click.option("--notify", "-n", default=None, help="推送渠道")
def l1(symbols: str | None, watchlist: str, engines: str, notify: str | None) -> None:
    """L1: 标准分析 + AI解读"""
    cfg = Config()
    syms = _parse_symbols(symbols, watchlist, cfg)
    if not syms:
        click.echo("请指定 --symbols 或配置 watchlist.csv")
        return

    engine_list = [e.strip() for e in engines.split(",")] if engines else []
    click.echo(f"L1: 标准分析 ({len(syms)} 只标的, 引擎: {engine_list})")

    repo = _build_repo(cfg)

    # Step 1: 获取数据
    try:
        quotes = repo.get_realtime(syms)
    except Exception as e:
        click.echo(f"✗ 数据获取失败: {e}")
        return
    if not quotes:
        click.echo("✗ 数据获取失败")
        return

    # Step 2: 构建分析上下文
    contexts: list[AnalysisContext] = []
    for sym in syms:
        quote = quotes.get(sym)
        if not quote:
            click.echo(f"  {sym}: 无行情数据")
            continue
        # 尝试获取历史数据
        try:
            end = date.today()
            start = end - timedelta(days=120)
            historical = repo.get_historical(sym, start, end)
        except Exception:
            historical = None
        contexts.append(AnalysisContext(
            symbol=sym,
            realtime=quote,
            historical=historical,
        ))

    if not contexts:
        click.echo("✗ 无有效分析标的")
        return

    # Step 3: 运行管道
    available = [e for e in engine_list if e in discover_engines()]
    if not available:
        click.echo("⚠ 指定的引擎均未注册，退回纯数据模式")
        click.echo(f"  可用引擎: {discover_engines()}")
        available = discover_engines()[:1]

    pipeline = AnalysisPipeline(engine_names=available)
    result: PipelineResult = pipeline.run(contexts)

    # Step 4: 输出结果
    click.echo(f"\n=== 分析结果 ({len(result.results)} 只) ===")
    for sym, engine_results in result.results.items():
        click.echo(f"\n--- {sym} ---")
        for ar in engine_results:
            rating_str = ar.rating.value if hasattr(ar.rating, "value") else str(ar.rating)
            click.echo(f"  [{ar.engine_name}] 评分 {ar.score:.0f}/100 · {rating_str}")
            if ar.narrative:
                click.echo(f"  {ar.narrative[:200]}")
            if ar.risks:
                for risk in ar.risks:
                    click.echo(f"  ⚠ {risk}")
            if ar.duration_ms:
                click.echo(f"  耗时: {ar.duration_ms}ms")

    if result.errors:
        click.echo(f"\n⚠ {len(result.errors)} 个引擎执行出错")
        for err in result.errors:
            click.echo(f"  {err.get('engine', '?')}: {err.get('error', '')}")

    click.echo(f"\n总耗时: {result.metrics.get('duration_ms', 0)}ms")


@cli.command()
@click.option("--symbols", "-s", help="股票代码，逗号分隔")
@click.option("--watchlist", "-w", default="config/watchlist.csv", help="自选股文件路径")
@click.option("--engines", "-e", default="all", help="分析引擎，逗号分隔或 all")
@click.option("--notify", "-n", default="local", help="推送渠道，逗号分隔")
@click.option("--output", "-o", default="output/", help="报告输出目录")
def l2(symbols: str | None, watchlist: str, engines: str, notify: str, output: str) -> None:
    """L2: 深度分析 + 多引擎共识 + 报告生成"""
    cfg = Config()
    syms = _parse_symbols(symbols, watchlist, cfg)
    if not syms:
        click.echo("请指定 --symbols 或配置 watchlist.csv")
        return

    engine_list_str = [e.strip() for e in engines.split(",")]
    notify_list = [n.strip() for n in notify.split(",")]
    click.echo(f"L2: 深度分析 ({len(syms)} 只标的, 推送: {notify_list})")

    repo = _build_repo(cfg)

    # Step 1: 数据获取
    try:
        quotes = repo.get_realtime(syms)
    except Exception as e:
        click.echo(f"✗ 数据获取失败: {e}")
        return
    if not quotes:
        click.echo("✗ 数据获取失败")
        return

    # Step 2: 引擎选择
    all_engines = discover_engines()
    if "all" in engine_list_str:
        engine_list = all_engines
    else:
        engine_list = [e for e in engine_list_str if e in all_engines]
    click.echo(f"  引擎: {engine_list}")

    # Step 3: 分析上下文
    contexts = []
    for sym in syms:
        quote = quotes.get(sym)
        if not quote:
            continue
        try:
            end = date.today()
            start = end - timedelta(days=250)
            historical = repo.get_historical(sym, start, end)
        except Exception:
            historical = None
        contexts.append(AnalysisContext(
            symbol=sym,
            realtime=quote,
            historical=historical,
        ))

    if not contexts:
        click.echo("✗ 无有效分析标的")
        return

    # Step 4: 运行管道
    pipeline = AnalysisPipeline(engine_names=engine_list)
    result = pipeline.run(contexts)

    # Step 5: 生成报告
    report_dir = Path(output)
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"report-{'-'.join(syms[:3])}.html"

    try:
        from .report.builder import ReportBuilder
        builder = ReportBuilder(level="L2")
        html = builder.build(result)
        report_path.write_text(html, encoding="utf-8")
        click.echo(f"\n📄 报告已保存: {report_path}")
    except Exception as e:
        click.echo(f"⚠ 报告生成失败: {e}")
        # 仍然输出文本摘要
        pass

    # Step 6: 摘要输出
    click.echo(f"\n=== 分析摘要 ({len(result.results)} 只) ===")
    for sym, engine_results in result.results.items():
        click.echo(f"\n--- {sym} ---")
        for ar in engine_results:
            rating_str = ar.rating.value if hasattr(ar.rating, "value") else str(ar.rating)
            click.echo(f"  [{ar.engine_name}] {ar.score:.0f}/100 · {rating_str}")
            if ar.narrative:
                click.echo(f"  {ar.narrative[:300]}")

    if result.errors:
        click.echo(f"\n⚠ {len(result.errors)} 个引擎出错")

    click.echo(f"\n总耗时: {result.metrics.get('duration_ms', 0)}ms")


@cli.command()
@click.option("--symbols", "-s", help="股票代码，逗号分隔")
@click.option("--watchlist", "-w", default="config/watchlist.csv", help="自选股文件路径")
def run(symbols: str | None, watchlist: str) -> None:
    """按 DITING_LEVEL 环境变量自动选择层级"""
    cfg = Config()
    level = cfg.level.upper()
    click.echo(f"谛听 v0.1.0 — 运行层级: {level}")
    if level == "L0":
        ctx = click.Context(l0)
        ctx.ensure_object(dict)
        ctx.invoke(l0, symbols=symbols, watchlist=watchlist, json_output=False)
    elif level == "L1":
        ctx = click.Context(l1)
        ctx.ensure_object(dict)
        ctx.invoke(l1, symbols=symbols, watchlist=watchlist, engines="wyckoff,vmd_rsi", notify=None)
    else:
        ctx = click.Context(l2)
        ctx.ensure_object(dict)
        ctx.invoke(
            l2,
            symbols=symbols,
            watchlist=watchlist,
            engines="all",
            notify="local",
            output="output/",
        )


def _parse_symbols(symbols: str | None, watchlist: str, cfg: Config) -> list[str]:
    """解析股票代码：CLI 参数优先，否则读 watchlist"""
    if symbols:
        return [s.strip() for s in symbols.split(",") if s.strip()]
    wl = cfg.load_watchlist(watchlist)
    if wl:
        return [row["code"] for row in wl if "code" in row]
    return []


if __name__ == "__main__":
    cli()
