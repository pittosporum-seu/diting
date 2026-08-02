# Diting v0.8 interface contracts

This reference summarizes stable public entry points. HTTP field-level truth is the
[runtime-generated OpenAPI document](../api/diting-openapi.yaml); Python types live in
`src/diting/schema.py` and ports in `src/diting/ports.py`.

## Python

```python
from diting import AnalysisProfile, Diting, FetchMode

with Diting.from_config(path=None, overrides=None) as client:
    quote = client.get_quote(
        "002475",
        freshness=FetchMode.CACHE_PREFERRED,
        force_refresh=False,
    )
    run = client.analyze(
        "002475",
        profile=AnalysisProfile.STANDARD,
        force_refresh=False,
        engines=None,
    )
    scan = client.scan(limit=20)
```

| Method | Return | Failure semantics |
|---|---|---|
| `get_quote` | `DataResult[RealtimeQuote]` | typed `error_code`, warnings and trace; never starts analysis |
| `analyze` | `AnalysisRun` | failed engines remain EngineRun failures; insufficient consensus has null score |
| `scan` | `ScanResult` | no active strategy is a failed empty result with `NO_ACTIVE_STRATEGY` |
| `close` | `None` | idempotently closes owned workers/adapters |

Symbols are exactly six digits. `freshness` accepts `cache_preferred`, `fresh_required` or
`cache_only`; profiles are `standard` and `deep`.

## CLI

```text
diting [--config FILE] analyze CODE [--profile standard|deep] [--force-refresh] [--engine NAME] [--json]
diting CODE                         # standard analyze shorthand
diting [--config FILE] quote CODE [--freshness MODE] [--force-refresh] [--json]
diting [--config FILE] compare CODE,CODE [--freshness MODE] [--json]
diting [--config FILE] scan [--limit 1..100] [--json]
diting [--config FILE] watchlist [--add CODE | --remove CODE] [...]
diting [--config FILE] strategy [--json]
diting [--config FILE] serve [--host HOST] [--port PORT]
```

`l0`, `l1`, `l2`, `run` and `init` are permanently removed and return `CLI_COMMAND_REMOVED`.

## HTTP

- Internal FastAPI root: `/api/v1/*`.
- Production gateway root: `/api/diting/v1/*`.
- Unversioned `/api/*`: `410 API_VERSION_REMOVED`.
- All v1 JSON uses `ApiEnvelope[T]` with `api_version`, `request_id`, `server_time`, `data`, `meta`
  and `error`.

Anonymous availability is controlled by `runtime.public_readonly`. Health/session endpoints remain
available; configured public mode exposes search, quote, completed analysis, dashboard and active
opportunities. Owner-only operations include analysis/scan creation, jobs, watchlist, preferences,
cache administration, diagnostics and strategy lifecycle transitions.

Owner login uses `POST /api/v1/auth/session`; the service returns a 12-hour HttpOnly,
SameSite=Strict cookie and a CSRF token in the response body. Browser writes require the cookie,
exact allowed Origin and `X-CSRF-Token`. Production cookies are Secure.

## Data result metadata

Every data result carries:

```text
data, data_time, cache_info, provider_traces, warnings, request_hash, error_code
```

Cache mode and force-refresh behavior are described in the Accepted design. Cache keys include data
type, symbol, period/adjustment/date range and schema version; analysis/scan identities add their
frozen strategy/config/engine dimensions.

## Contract maintenance

```bash
uv run python scripts/validate-api.py --write  # intentional runtime model change
uv run python scripts/validate-api.py --check  # required CI comparison
```

Do not hand-edit the generated YAML. Change FastAPI/Pydantic models, regenerate, inspect the diff and
update this summary when public semantics change.
