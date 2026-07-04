"""谛听 · CLI 入口"""

import click

from .config import Config


@click.group()
@click.version_option(version="0.1.0", prog_name="diting")
def cli() -> None:
    """谛听 · A股多模型AI投资分析工具"""
    pass


@cli.command()
@click.option("--symbols", "-s", help="股票代码，逗号分隔")
@click.option("--watchlist", "-w", default="config/watchlist.csv", help="自选股文件路径")
def l0(symbols: str | None, watchlist: str) -> None:
    """L0: 快速行情快照（无AI）"""
    cfg = Config()
    syms = _parse_symbols(symbols, watchlist, cfg)
    click.echo(f"L0: 获取行情快照 ({len(syms)} 只标的)")
    for s in syms:
        click.echo(f"  {s}: 待实现 (data layer WIP)")


@cli.command()
@click.option("--symbols", "-s", help="股票代码，逗号分隔")
@click.option("--watchlist", "-w", default="config/watchlist.csv", help="自选股文件路径")
@click.option("--engines", "-e", default="wyckoff,vmd_rsi", help="分析引擎，逗号分隔")
@click.option("--notify", "-n", default=None, help="推送渠道")
def l1(symbols: str | None, watchlist: str, engines: str, notify: str | None) -> None:
    """L1: 标准分析 + AI解读"""
    cfg = Config()
    syms = _parse_symbols(symbols, watchlist, cfg)
    engine_list = [e.strip() for e in engines.split(",")]
    click.echo(f"L1: 标准分析 ({len(syms)} 只标的, 引擎: {engine_list})")
    for s in syms:
        click.echo(f"  {s}: 待实现 (engines WIP)")


@cli.command()
@click.option("--symbols", "-s", help="股票代码，逗号分隔")
@click.option("--watchlist", "-w", default="config/watchlist.csv", help="自选股文件路径")
@click.option("--engines", "-e", default="all", help="分析引擎，逗号分隔或 all")
@click.option("--notify", "-n", default="feishu,email,local", help="推送渠道，逗号分隔")
@click.option("--output", "-o", default="output/", help="报告输出目录")
def l2(symbols: str | None, watchlist: str, engines: str, notify: str, output: str) -> None:
    """L2: 深度分析 + 多引擎共识"""
    cfg = Config()
    syms = _parse_symbols(symbols, watchlist, cfg)
    engine_list = [e.strip() for e in engines.split(",")]
    notify_list = [n.strip() for n in notify.split(",")]
    click.echo(f"L2: 深度分析 ({len(syms)} 只标的, 引擎: {engine_list}, 推送: {notify_list})")
    click.echo(f"  输出目录: {output}")
    for s in syms:
        click.echo(f"  {s}: 待实现 (pipeline WIP)")


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
        ctx.invoke(l0, symbols=symbols, watchlist=watchlist)
    elif level == "L1":
        ctx = click.Context(l1)
        ctx.invoke(l1, symbols=symbols, watchlist=watchlist)
    else:
        ctx = click.Context(l2)
        ctx.invoke(l2, symbols=symbols, watchlist=watchlist)


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
