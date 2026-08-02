# Design document status

## Current baseline

| Document | Status | Purpose |
|---|---|---|
| [v0.8.0-system-design.md](v0.8.0-system-design.md) | **Accepted** | Product boundary, target architecture and decisions |
| [api-contracts.md](api-contracts.md) | Active reference | Python/CLI/HTTP interface summary |
| [development-workflow.md](development-workflow.md) | Active how-to | Current task and gate workflow |
| [issues/](issues/) | Active records | v0.8 implementation slices and acceptance criteria |
| [test-results/](test-results/) | Active evidence | Executed checks, checkpoints and known risks |

The runtime OpenAPI document is generated from FastAPI/Pydantic and lives at
[`docs/api/diting-openapi.yaml`](../api/diting-openapi.yaml). Precise code contracts live in
`src/diting/schema.py`, `src/diting/ports.py` and the strict configuration models.

## Superseded historical designs

The following families are **Superseded** by v0.8 and must not be used as implementation contracts:

| Family | Status | Notes |
|---|---|---|
| `v0.1.0-*`, `v0.2.0-*` | Superseded | Early layer/repository and interaction proposals |
| `030-*`, `product-redesign.md` | Superseded | Intermediate product sketches |
| `v0.6.0-*`, `v0.6.5-*` | Superseded | Legacy service/data-flow implementation |
| `v0.7.0-*`, `v0.7.2-*` | Superseded | Jinja/SPA and unversioned HTTP designs removed in v0.8 |
| `architecture.md`, `overview.md`, `features.md`, `web-design.md` | Superseded | Pre-v0.8 architecture summaries |
| `cache-layer-design.md`, `config-driven-design.md`, `watchlist-db-design.md` | Superseded | Earlier component-specific contracts |
| `frontend-loading-chain.md`, `ux-audit-design.md`, `architecture-review.md` | Historical evidence | Problems and review input, not current behavior |

Research-method background in `docs/02-research/` remains useful, but production strategy state is
tracked only by [`docs/research/INDEX.md`](../research/INDEX.md), manifests and the strategy registry.
