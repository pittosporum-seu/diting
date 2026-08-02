"""Breaking v0.8 Click interface backed by the public facade and composition root."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

import click

from . import __version__
from .enums import AnalysisProfile, FetchMode, RunStatus
from .facade import Diting
from .schema import AuditEvent, WatchlistEntry

_REMOVED_COMMANDS = {"l0", "l1", "l2", "run", "init"}
_OWNER_ID = "owner"


@dataclass
class _CliRuntime:
    config_path: Path | None
    _client: Diting | None = None

    @property
    def client(self) -> Diting:
        if self._client is None:
            self._client = Diting.from_config(self.config_path)
        return self._client

    @property
    def container(self):
        # CLI-only administration uses the same container owned by Diting.
        return self.client._container

    def close(self) -> None:
        if self._client is not None:
            self._client.close()


class _DitingGroup(click.Group):
    """Map a six-digit first argument to standard analysis and reject removed aliases."""

    def resolve_command(self, ctx, args):
        if args and args[0].lower() in _REMOVED_COMMANDS:
            raise click.UsageError(
                f"CLI_COMMAND_REMOVED: '{args[0]}' was removed in v0.8; use analyze/quote/scan"
            )
        if args and _is_symbol(args[0]) and args[0] not in self.commands:
            command = self.get_command(ctx, "analyze")
            return "analyze", command, args
        return super().resolve_command(ctx, args)


@click.group(
    cls=_DitingGroup,
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.version_option(version=__version__, prog_name="diting")
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=None,
    help="严格 v0.8 YAML 配置路径。",
)
@click.pass_context
def cli(ctx: click.Context, config_path: Path | None) -> None:
    """谛听 · A股多模型投资分析工具。"""

    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())
        return
    runtime = _CliRuntime(config_path)
    ctx.obj = runtime
    ctx.call_on_close(runtime.close)


@cli.command()
@click.argument("symbol")
@click.option(
    "--profile",
    type=click.Choice([item.value for item in AnalysisProfile], case_sensitive=False),
    default=AnalysisProfile.STANDARD.value,
    show_default=True,
)
@click.option("--force-refresh", is_flag=True, help="跳过缓存读取，成功数据仍写回缓存。")
@click.option("--engine", "engines", multiple=True, help="限制到已配置引擎；可重复。")
@click.option("--json", "json_output", is_flag=True, help="输出机器可读 JSON。")
@click.pass_obj
def analyze(
    runtime: _CliRuntime,
    symbol: str,
    profile: str,
    force_refresh: bool,
    engines: tuple[str, ...],
    json_output: bool,
) -> None:
    """分析一只证券；`diting CODE` 等价于 standard 分析。"""

    try:
        run = runtime.client.analyze(
            symbol,
            profile=profile,
            force_refresh=force_refresh,
            engines=engines or None,
        )
    except Exception as exc:
        raise _click_error(exc) from exc
    if json_output:
        _echo_json(run)
        return
    score = "证据不足" if run.analysis_score is None else f"{run.analysis_score:.1f}"
    click.echo(f"{run.symbol}  {run.profile.value}  {run.status.value}  score={score}")
    click.echo(f"run_id={run.run_id} snapshot={run.snapshot_hash}")
    if run.verdict is not None:
        click.echo(f"{run.verdict.label.value}: {run.verdict.summary}")
    for warning in run.warnings:
        click.echo(f"warning[{warning.code}]: {warning.message}", err=True)


@cli.command()
@click.argument("symbol")
@click.option(
    "--freshness",
    type=click.Choice([item.value for item in FetchMode], case_sensitive=False),
    default=FetchMode.CACHE_PREFERRED.value,
    show_default=True,
)
@click.option("--force-refresh", is_flag=True)
@click.option("--json", "json_output", is_flag=True)
@click.pass_obj
def quote(
    runtime: _CliRuntime,
    symbol: str,
    freshness: str,
    force_refresh: bool,
    json_output: bool,
) -> None:
    """读取一只证券的规范化行情和缓存来源。"""

    try:
        result = runtime.client.get_quote(
            symbol,
            freshness=freshness,
            force_refresh=force_refresh,
        )
    except Exception as exc:
        raise _click_error(exc) from exc
    if not result.succeeded or result.data is None:
        raise click.ClickException(result.error_code or "DATA_UNAVAILABLE")
    if json_output:
        _echo_json(result)
        return
    item = result.data
    cache = result.cache_info
    click.echo(
        f"{item.symbol}  {item.name}  {item.price:.2f}  {item.change_pct:+.2f}%  "
        f"cache={cache.state.value}/{cache.tier.value} source={item.source.value}"
    )


@cli.command()
@click.option("--limit", type=click.IntRange(1, 100), default=20, show_default=True)
@click.option("--json", "json_output", is_flag=True)
@click.pass_obj
def scan(runtime: _CliRuntime, limit: int, json_output: bool) -> None:
    """运行已人工激活的生产机会策略。"""

    try:
        result = runtime.client.scan(limit=limit)
    except Exception as exc:
        raise _click_error(exc) from exc
    if json_output:
        _echo_json(result)
    elif result.status is RunStatus.SUCCEEDED:
        click.echo(f"strategy={result.strategy_version} date={result.data_date}")
        for item in result.items:
            click.echo(f"{item.rank:>2}  {item.symbol}  {item.name}  {item.score:.2f}")
    if result.status is not RunStatus.SUCCEEDED:
        raise click.ClickException(result.error_code or "SCAN_FAILED")


@cli.command()
@click.argument("symbols")
@click.option(
    "--freshness",
    type=click.Choice([item.value for item in FetchMode], case_sensitive=False),
    default=FetchMode.CACHE_PREFERRED.value,
    show_default=True,
)
@click.option("--json", "json_output", is_flag=True)
@click.pass_obj
def compare(runtime: _CliRuntime, symbols: str, freshness: str, json_output: bool) -> None:
    """比较 2–20 只证券的同口径行情快照（逗号分隔）。"""

    requested = tuple(dict.fromkeys(item.strip() for item in symbols.split(",") if item.strip()))
    if not 2 <= len(requested) <= 20:
        raise click.UsageError("compare requires between 2 and 20 unique symbols")
    rows: list[dict[str, Any]] = []
    for symbol in requested:
        try:
            result = runtime.client.get_quote(symbol, freshness=freshness)
        except Exception as exc:
            raise _click_error(exc) from exc
        if not result.succeeded or result.data is None:
            raise click.ClickException(f"{symbol}: {result.error_code or 'DATA_UNAVAILABLE'}")
        item = result.data
        rows.append(
            {
                "symbol": item.symbol,
                "name": item.name,
                "price": item.price,
                "change_pct": item.change_pct,
                "pe": item.pe,
                "pb": item.pb,
                "source": item.source.value,
            }
        )
    if json_output:
        _echo_json(rows)
        return
    for row in rows:
        click.echo(
            f"{row['symbol']}  {row['name']:<10}  {row['price']:>8.2f}  "
            f"{row['change_pct']:+.2f}%  PE={row['pe'] or '-'}  PB={row['pb'] or '-'}"
        )


@cli.command()
@click.option("--add", type=str, help="新增或更新六位证券代码。")
@click.option("--remove", type=str, help="删除六位证券代码。")
@click.option("--name", default="", help="新增证券名称。")
@click.option("--market", type=click.Choice(["SH", "SZ", "BJ"]), default=None)
@click.option("--tag", "tags", multiple=True, help="自选标签；可重复。")
@click.option("--json", "json_output", is_flag=True)
@click.pass_obj
def watchlist(
    runtime: _CliRuntime,
    add: str | None,
    remove: str | None,
    name: str,
    market: str | None,
    tags: tuple[str, ...],
    json_output: bool,
) -> None:
    """查看或维护业务数据库中的 owner 自选列表。"""

    if add and remove:
        raise click.UsageError("--add and --remove are mutually exclusive")
    container = runtime.container
    store = container.durable_store
    if store is None:
        raise click.ClickException("DURABLE_STORE_UNAVAILABLE")
    now = container.clock.now()
    if add:
        symbol = _validated_symbol(add)
        existing = {item.symbol: item for item in store.list_watchlist(_OWNER_ID)}.get(symbol)
        entry = WatchlistEntry(
            symbol=symbol,
            name=name,
            market=market or _infer_market(symbol),
            owner_id=_OWNER_ID,
            created_at=existing.created_at if existing else now,
            updated_at=now,
            tags=tags,
        )
        store.upsert_watchlist(entry)
        _audit(runtime, "watchlist.upsert", symbol)
    if remove:
        symbol = _validated_symbol(remove)
        if not store.delete_watchlist(_OWNER_ID, symbol):
            raise click.ClickException("WATCHLIST_NOT_FOUND")
        _audit(runtime, "watchlist.delete", symbol)
    items = store.list_watchlist(_OWNER_ID)
    if json_output:
        _echo_json(items)
        return
    if not items:
        click.echo("自选列表为空")
        return
    for item in items:
        click.echo(f"{item.symbol}  {item.name or '-'}  {item.market}  {','.join(item.tags)}")


@cli.command()
@click.option("--json", "json_output", is_flag=True)
@click.pass_obj
def strategy(runtime: _CliRuntime, json_output: bool) -> None:
    """显示当前选定策略及其人工激活状态。"""

    container = runtime.container
    store = container.durable_store
    if store is None:
        raise click.ClickException("DURABLE_STORE_UNAVAILABLE")
    selected = container.settings.strategy.selected
    active = store.get_active_strategy(selected)
    data = {
        "selected": selected,
        "active": active is not None,
        "version": active.version if active else None,
        "manifest_hash": active.manifest_hash if active else None,
    }
    if json_output:
        _echo_json(data)
        return
    if active is None:
        click.echo(f"{selected}: unavailable (NO_ACTIVE_STRATEGY)")
    else:
        click.echo(f"{selected}:{active.version} active manifest={active.manifest_hash}")


@cli.command()
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", type=click.IntRange(1, 65535), default=8100, show_default=True)
def serve(host: str, port: int) -> None:
    """启动单 worker FastAPI 服务。"""

    import uvicorn

    uvicorn.run("diting.web.app:app", host=host, port=port, workers=1)


def _audit(runtime: _CliRuntime, action: str, target: str) -> None:
    container = runtime.container
    assert container.durable_store is not None
    container.durable_store.append_audit(
        AuditEvent(
            actor="cli:local",
            action=action,
            target=target,
            created_at=container.clock.now(),
        )
    )


def _is_symbol(value: str) -> bool:
    return len(value) == 6 and value.isdigit()


def _validated_symbol(value: str) -> str:
    normalized = value.strip()
    if not _is_symbol(normalized):
        raise click.BadParameter("symbol must contain exactly six digits")
    return normalized


def _infer_market(symbol: str) -> str:
    if symbol.startswith(("4", "8")):
        return "BJ"
    if symbol.startswith(("5", "6", "9")):
        return "SH"
    return "SZ"


def _click_error(exc: Exception) -> click.ClickException:
    return click.ClickException(f"{type(exc).__name__}: {exc}")


def _echo_json(value: Any) -> None:
    payload = asdict(value) if hasattr(value, "__dataclass_fields__") else value
    click.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=_json_default))


def _json_default(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(f"cannot serialize {type(value).__name__}")


if __name__ == "__main__":  # pragma: no cover
    cli()
