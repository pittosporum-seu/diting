"""Immutable experiment manifests and fixed mean-reversion promotion gates."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from datetime import date, datetime
from enum import Enum
from typing import Any

from ..application.strategy_registry import StrategyRegistry
from ..enums import StrategyState
from ..infra.errors import AnalysisError
from ..ports import DurableStore
from ..schema import (
    ExperimentManifest,
    ExperimentWindow,
    PromotionDecision,
    PromotionGateCheck,
    StrategyVersion,
)

TRAINING_WINDOW = ExperimentWindow(date(2022, 1, 1), date(2024, 12, 31))
VALIDATION_WINDOW = ExperimentWindow(date(2025, 1, 1), date(2025, 12, 31))
OOS_WINDOW = ExperimentWindow(date(2026, 1, 1), date(2026, 7, 31))


def canonical_manifest_hash(manifest: ExperimentManifest) -> str:
    """Hash every manifest field except the hash field itself."""

    payload = asdict(replace(manifest, manifest_hash=""))
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def seal_manifest(manifest: ExperimentManifest) -> ExperimentManifest:
    """Return a manifest carrying its canonical content hash."""

    return replace(manifest, manifest_hash=canonical_manifest_hash(manifest))


class ExperimentGovernance:
    """Evaluate fixed gates, persist evidence and create validated registry entries."""

    def __init__(self, store: DurableStore, registry: StrategyRegistry) -> None:
        self._store = store
        self._registry = registry

    def evaluate(self, manifest: ExperimentManifest) -> PromotionDecision:
        metrics = manifest.metrics
        checks = (
            _check(
                "MANIFEST_HASH",
                manifest.manifest_hash == canonical_manifest_hash(manifest),
                manifest.manifest_hash,
                "canonical sha256",
            ),
            _check(
                "STRATEGY_NAME",
                manifest.strategy_name == "mean_reversion_v1",
                manifest.strategy_name,
                "mean_reversion_v1",
            ),
            _check(
                "EXPERIMENT_IDENTITY",
                bool(manifest.experiment_id and manifest.title and manifest.hypothesis),
                manifest.experiment_id,
                "non-empty id, title and hypothesis",
            ),
            _check(
                "TRAINING_WINDOW",
                manifest.training_window == TRAINING_WINDOW,
                str(manifest.training_window),
                str(TRAINING_WINDOW),
            ),
            _check(
                "VALIDATION_WINDOW",
                manifest.validation_window == VALIDATION_WINDOW,
                str(manifest.validation_window),
                str(VALIDATION_WINDOW),
            ),
            _check(
                "OOS_WINDOW",
                manifest.oos_window == OOS_WINDOW,
                str(manifest.oos_window),
                str(OOS_WINDOW),
            ),
            _check(
                "DATA_RANGE",
                manifest.data_start <= TRAINING_WINDOW.start
                and manifest.data_end >= OOS_WINDOW.end,
                f"{manifest.data_start}/{manifest.data_end}",
                "covers all windows",
            ),
            _check(
                "PROVIDER_TRACE",
                bool(manifest.providers)
                and all(manifest.providers)
                and _sha256(manifest.provider_trace_hash),
                manifest.provider_trace_hash,
                "providers plus sha256 trace",
            ),
            _check(
                "GATEWAY_REQUESTS",
                bool(manifest.gateway_request_hashes)
                and all(_sha256(value) for value in manifest.gateway_request_hashes),
                str(len(manifest.gateway_request_hashes)),
                "one or more sha256 request hashes",
            ),
            _check(
                "DATA_SNAPSHOT",
                _sha256(manifest.data_snapshot_hash),
                manifest.data_snapshot_hash,
                "sha256",
            ),
            _check("CONFIG_HASH", _sha256(manifest.config_hash), manifest.config_hash, "sha256"),
            _check(
                "CODE_COMMIT",
                len(manifest.code_commit) >= 7,
                manifest.code_commit,
                "git commit (>=7 chars)",
            ),
            _check(
                "ADJUSTMENT",
                manifest.adjustment_method in {"qfq", "hfq", "none"},
                manifest.adjustment_method,
                "qfq|hfq|none",
            ),
            _check(
                "POINT_IN_TIME_UNIVERSE",
                manifest.includes_listing_dates
                and manifest.includes_delisting_dates
                and manifest.survivorship_bias_checked,
                manifest.universe,
                "listing/delisting dates and survivorship check",
            ),
            _check(
                "UNIVERSE_METADATA",
                bool(manifest.universe and manifest.asset_types and manifest.exclusion_rules),
                manifest.universe,
                "universe, asset types and exclusion rules",
            ),
            _check(
                "FACTOR_METADATA",
                bool(manifest.factors)
                and all(
                    item.direction in {-1, 1}
                    and item.formula
                    and item.normalization
                    and item.missing_value_policy
                    for item in manifest.factors
                ),
                str(len(manifest.factors)),
                "typed non-empty factors",
            ),
            _check(
                "RESULT_HASHES",
                bool(manifest.result_hashes)
                and all(path and _sha256(value) for path, value in manifest.result_hashes),
                str(len(manifest.result_hashes)),
                "one or more sha256 result files",
            ),
            _check(
                "REPRODUCE_COMMAND",
                manifest.reproduce_command.startswith("uv run "),
                manifest.reproduce_command,
                "uv run ...",
            ),
            _check("OOS_RANK_IC", metrics.oos_rank_ic >= 0.05, metrics.oos_rank_ic, ">= 0.05"),
            _check("OOS_IC_IR", metrics.oos_ic_ir >= 0.5, metrics.oos_ic_ir, ">= 0.5"),
            _check(
                "BOOTSTRAP_IC_LOWER",
                metrics.bootstrap_ic_lower_95 > 0,
                metrics.bootstrap_ic_lower_95,
                "> 0",
            ),
            _check(
                "NET_EXCESS_20D",
                metrics.net_excess_return_20d >= 0.005,
                metrics.net_excess_return_20d,
                ">= 0.005",
            ),
            _check(
                "PARAMETER_SENSITIVITY",
                metrics.parameter_sensitivity < 0.30,
                metrics.parameter_sensitivity,
                "< 0.30",
            ),
            _check(
                "DATA_COVERAGE", metrics.data_coverage >= 0.90, metrics.data_coverage, ">= 0.90"
            ),
            _check(
                "CROSS_SECTION",
                metrics.minimum_cross_section >= 500,
                metrics.minimum_cross_section,
                ">= 500",
            ),
            _check(
                "PORTFOLIO",
                metrics.top_n == 20 and metrics.holding_days == 20,
                f"top={metrics.top_n},days={metrics.holding_days}",
                "Top20, 20 trading days",
            ),
            _check(
                "TRADING_COST",
                metrics.round_trip_cost_bps == 40,
                metrics.round_trip_cost_bps,
                "40 bps round trip",
            ),
            _check(
                "NO_FUTURE_LEAKAGE",
                not metrics.future_data_leakage,
                metrics.future_data_leakage,
                "false",
            ),
        )
        return PromotionDecision(passed=all(item.passed for item in checks), checks=checks)

    def promote_validated(self, manifest: ExperimentManifest) -> PromotionDecision:
        """Persist a passing manifest and advance only its new draft to validated."""

        decision = self.evaluate(manifest)
        if not decision.passed:
            return decision
        if not self._store.save_experiment_manifest(manifest):
            existing = self._store.get_experiment_manifest(manifest.manifest_hash)
            if existing != manifest:
                raise AnalysisError(
                    "manifest hash already exists with different content",
                    error_code="MANIFEST_HASH_CONFLICT",
                    http_status_code=409,
                )
        self._registry.register(
            StrategyVersion(
                name=manifest.strategy_name,
                version=manifest.strategy_version,
                state=StrategyState.DRAFT,
                manifest_hash=manifest.manifest_hash,
                created_at=manifest.created_at,
            )
        )
        self._registry.mark_validated(manifest.strategy_name, manifest.strategy_version)
        return decision


def _check(code: str, passed: bool, actual: Any, required: str) -> PromotionGateCheck:
    return PromotionGateCheck(code=code, passed=passed, actual=str(actual), required=required)


def _sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value.lower())


def _json_default(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"cannot encode {type(value).__name__}")
