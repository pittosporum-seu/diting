# First quote and analysis

This tutorial gets a new checkout to one typed quote and one standard analysis. It does not activate
an opportunity strategy or configure production authentication.

## 1. Install

```bash
git clone https://github.com/pittosporum-seu/diting.git
cd diting
uv sync --extra dev
```

## 2. Read a quote

```bash
uv run diting quote 002475 --freshness cache_preferred
```

The command always goes through the cache middleware. Output includes the normalized price, change,
cache state/tier and Provider source. `--force-refresh` skips cache reads but still writes a
successful result back.

## 3. Run standard analysis

```bash
uv run diting analyze 002475 --profile standard
# shorthand:
uv run diting 002475
```

The application freezes one data snapshot, selects configured engines, persists every EngineRun and
then applies consensus. If evidence is insufficient, the score is displayed as “证据不足”; this is
different from a 50 score.

Without an AI key, deterministic technical and volume-profile engines can still run. Configure AI
only through environment variables if you want strict structured Wyckoff/CANSLIM/Buffett engines.

## 4. Inspect the typed result in Python

```python
from diting import Diting

with Diting.from_config() as client:
    result = client.get_quote("002475")
    print(result.succeeded)
    print(result.cache_info)
    print(result.provider_traces)

    run = client.analyze("002475")
    print(run.snapshot_hash)
    print(run.engine_runs)
    print(run.consensus)
```

## 5. Understand the opportunity result

```bash
uv run diting scan --limit 20
```

On a fresh installation this should report `NO_ACTIVE_STRATEGY`. That is expected: strategy
validation and Owner activation are separate governed operations. Continue with
[the strategy activation how-to](../how-to/activate-strategy.md) only after a complete research
report exists.
