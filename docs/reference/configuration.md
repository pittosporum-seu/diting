# Configuration reference

Diting loads exactly one frozen `AppConfig` at the composition root. Precedence is:

```text
explicit overrides > environment variables > YAML > defaults
```

Unknown YAML/override fields fail validation. Secrets are rejected in YAML and must come from the
environment. `config/diting.yaml` is the non-secret project template; `config/.env.example` documents
deployment variables without real values.

## Runtime and storage

| Environment | Model field | Default |
|---|---|---|
| `DITING_ENVIRONMENT` | `runtime.environment` | `development` |
| `DITING_PUBLIC_READONLY` | `runtime.public_readonly` | `false` |
| `DITING_LOG` | `runtime.log_level` | `WARNING` |
| `DITING_DB_PATH` | `database.business_path` | `diting.db` |
| `DITING_CACHE_DB_PATH` | `database.cache_path` | `diting_cache.db` |
| `DITING_REPORT_OUTPUT_DIR` | `report.output_dir` | `output` |

`diting.db` is durable business state. `diting_cache.db` is disposable L2 data/Provider state and
must not be used as a business source of truth.

## Owner security

| Environment | Meaning |
|---|---|
| `DITING_OWNER_TOKEN_HASH` | PBKDF2 hash accepted by the login endpoint; never the raw token |
| `DITING_SESSION_SECRET` | Random secret used to sign the 12-hour session cookie |
| `DITING_ALLOWED_ORIGINS` | Comma-separated exact browser Origins accepted for writes |

Generate values offline:

```bash
uv run python - <<'PY'
import secrets
from diting.security.auth import hash_owner_token

raw = secrets.token_urlsafe(32)
print("Store this raw Owner token offline:", raw)
print("DITING_OWNER_TOKEN_HASH=" + hash_owner_token(raw))
print("DITING_SESSION_SECRET=" + secrets.token_urlsafe(48))
PY
```

Do not paste the output into Git, logs, tickets or notifications. Production sets
`DITING_PUBLIC_READONLY=true`; package/library defaults remain private (`false`).

## Data and AI

| Environment | Model field | Notes |
|---|---|---|
| `MX_APIKEY` | `credentials.mx_api_key` | Enables mx-data when its Provider entry requires the key |
| `DITING_AI_ENABLED` | `ai.enabled` | AI engines also require `AI_API_KEY` |
| `AI_MODEL` | `ai.model` | LiteLLM `provider/model` name |
| `AI_API_KEY` | `ai.api_key` | Secret; environment only |
| `DITING_SANDBOX_ENABLED` | `ai.sandbox_enabled` | Research capability; default false |

Provider order and max batch sizes are strict YAML fields. mx-data's production maximum is four
symbols per batch. Analysis, LLM and scan concurrency defaults are 4, 2 and 1 with a bounded queue
of 100.

## Programmatic overrides

```python
from diting import Diting

client = Diting.from_config(
    "config/diting.yaml",
    overrides={
        "runtime.public_readonly": False,
        "pipeline": {"max_workers": 2},
    },
)
```

Overrides use dotted field paths or nested mappings. They are validated by the same strict model.
