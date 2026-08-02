"""SQLite durable store for immutable v0.8 snapshots, runs and strategies."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from threading import RLock
from typing import Any

from ..enums import (
    AnalysisProfile,
    EngineRunStatus,
    JobType,
    Rating,
    RunStatus,
    StrategyState,
    VerdictLabel,
)
from ..schema import (
    AnalysisRequest,
    AnalysisRun,
    ConsensusConflict,
    ConsensusResult,
    DataSnapshot,
    DataWarning,
    EngineResult,
    EngineRun,
    Evidence,
    JobRecord,
    OwnerSession,
    Risk,
    ScanResult,
    StrategyVersion,
    Verdict,
)


class SQLiteDurableStore:
    """Transactional SQLite adapter; analysis records are insert-only."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._lock = RLock()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def save_data_snapshot(self, snapshot: DataSnapshot) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO data_snapshots(
                       snapshot_id, symbol, snapshot_hash, payload_json, completeness, created_at
                   ) VALUES(?,?,?,?,?,?)""",
                (
                    snapshot.snapshot_id,
                    snapshot.symbol,
                    snapshot.snapshot_hash,
                    _dump(snapshot),
                    snapshot.completeness,
                    snapshot.created_at.isoformat(),
                ),
            )

    def save_analysis_run(self, run: AnalysisRun) -> None:
        consensus = run.consensus
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT INTO analysis_runs(
                       run_id, symbol, profile, status, snapshot_hash, config_hash,
                       strategy_version, analysis_score, confidence, warnings_json,
                       created_at, completed_at, request_json, snapshot_id,
                       consensus_json, verdict_json, code_version, started_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    run.run_id,
                    run.symbol,
                    run.profile.value,
                    run.status.value,
                    run.snapshot_hash,
                    run.config_hash,
                    run.strategy_version,
                    run.analysis_score,
                    run.confidence,
                    _dump(run.warnings),
                    run.started_at.isoformat(),
                    run.completed_at.isoformat() if run.completed_at else None,
                    _dump(run.request),
                    run.snapshot_id,
                    _dump(consensus) if consensus else None,
                    _dump(run.verdict) if run.verdict else None,
                    run.code_version,
                    run.started_at.isoformat(),
                ),
            )
            for engine_run in run.engine_runs:
                connection.execute(
                    """INSERT INTO engine_runs(
                           run_id, engine_name, engine_version, status, deterministic,
                           score, confidence, result_json, error_code, error_detail,
                           started_at, finished_at, prompt_version, model, duration_ms
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        run.run_id,
                        engine_run.engine_name,
                        engine_run.engine_version,
                        engine_run.status.value,
                        int(engine_run.deterministic),
                        engine_run.engine_score,
                        engine_run.confidence,
                        _dump(engine_run.result) if engine_run.result else None,
                        engine_run.error_code,
                        engine_run.error_detail,
                        engine_run.started_at.isoformat(),
                        engine_run.finished_at.isoformat() if engine_run.finished_at else None,
                        engine_run.prompt_version,
                        engine_run.model,
                        engine_run.duration_ms,
                    ),
                )

    def get_analysis_run(self, run_id: str) -> AnalysisRun | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM analysis_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if row is None:
                return None
            engine_rows = connection.execute(
                "SELECT * FROM engine_runs WHERE run_id=? ORDER BY started_at, engine_name",
                (run_id,),
            ).fetchall()
        request_raw = json.loads(row["request_json"] or "{}")
        request = _parse_request(
            request_raw, fallback_symbol=row["symbol"], fallback=row["profile"]
        )
        consensus = (
            _parse_consensus(json.loads(row["consensus_json"])) if row["consensus_json"] else None
        )
        verdict = _parse_verdict(json.loads(row["verdict_json"])) if row["verdict_json"] else None
        warnings = tuple(_parse_warning(item) for item in json.loads(row["warnings_json"] or "[]"))
        return AnalysisRun(
            run_id=row["run_id"],
            request=request,
            status=RunStatus(row["status"]),
            snapshot_id=row["snapshot_id"],
            snapshot_hash=row["snapshot_hash"],
            config_hash=row["config_hash"],
            strategy_version=row["strategy_version"],
            code_version=row["code_version"],
            started_at=_datetime(row["started_at"] or row["created_at"]),
            engine_runs=tuple(_parse_engine_run(item) for item in engine_rows),
            consensus=consensus,
            verdict=verdict,
            completed_at=_datetime(row["completed_at"]) if row["completed_at"] else None,
            warnings=warnings,
        )

    def create_job(self, job: JobRecord) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO jobs(
                       job_id, job_type, dedupe_key, status, progress, request_json,
                       result_ref, error_code, created_at, started_at, finished_at,
                       deadline_at, cancel_requested
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                _job_values(job),
            )

    def get_job(self, job_id: str) -> JobRecord | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return _parse_job(row) if row is not None else None

    def get_active_job_by_dedupe(self, dedupe_key: str) -> JobRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT * FROM jobs
                   WHERE dedupe_key=? AND status IN ('queued', 'running')
                   ORDER BY created_at LIMIT 1""",
                (dedupe_key,),
            ).fetchone()
        return _parse_job(row) if row is not None else None

    def update_job(self, job: JobRecord) -> None:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """UPDATE jobs SET
                       job_type=?, dedupe_key=?, status=?, progress=?, request_json=?,
                       result_ref=?, error_code=?, created_at=?, started_at=?, finished_at=?,
                       deadline_at=?, cancel_requested=?
                   WHERE job_id=?""",
                (
                    job.job_type.value,
                    job.dedupe_key,
                    job.status.value,
                    job.progress,
                    job.request_json,
                    job.result_ref,
                    job.error_code,
                    job.created_at.isoformat(),
                    job.started_at.isoformat() if job.started_at else None,
                    job.finished_at.isoformat() if job.finished_at else None,
                    job.deadline_at.isoformat() if job.deadline_at else None,
                    int(job.cancel_requested),
                    job.job_id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"job not found: {job.job_id}")

    def interrupt_running_jobs(self, finished_at: datetime) -> int:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """UPDATE jobs
                   SET status='interrupted', error_code='WORKER_RESTARTED', finished_at=?
                   WHERE status='running'""",
                (finished_at.isoformat(),),
            )
            return cursor.rowcount

    def create_owner_session(self, session: OwnerSession) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO owner_sessions(
                       session_id, csrf_hash, created_at, expires_at, revoked_at
                   ) VALUES(?,?,?,?,?)""",
                (
                    session.session_id,
                    session.csrf_hash,
                    session.created_at.isoformat(),
                    session.expires_at.isoformat(),
                    session.revoked_at.isoformat() if session.revoked_at else None,
                ),
            )

    def get_owner_session(self, session_id: str) -> OwnerSession | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM owner_sessions WHERE session_id=?", (session_id,)
            ).fetchone()
        if row is None:
            return None
        return OwnerSession(
            session_id=row["session_id"],
            csrf_hash=row["csrf_hash"],
            created_at=_datetime(row["created_at"]),
            expires_at=_datetime(row["expires_at"]),
            revoked_at=_datetime(row["revoked_at"]) if row["revoked_at"] else None,
        )

    def revoke_owner_session(self, session_id: str, revoked_at: datetime) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """UPDATE owner_sessions SET revoked_at=?
                   WHERE session_id=? AND revoked_at IS NULL""",
                (revoked_at.isoformat(), session_id),
            )
            return cursor.rowcount == 1

    def save_scan_result(self, result: ScanResult) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO scan_results(scan_id, status, payload_json, created_at) "
                "VALUES(?,?,?,?)",
                (result.scan_id, result.status.value, _dump(result), datetime.now().isoformat()),
            )

    def save_strategy(self, strategy: StrategyVersion) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO strategies(
                       name, version, state, manifest_hash, definition_json,
                       created_at, activated_at
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    strategy.name,
                    strategy.version,
                    strategy.state.value,
                    strategy.manifest_hash,
                    _dump(strategy),
                    strategy.created_at.isoformat(),
                    strategy.activated_at.isoformat() if strategy.activated_at else None,
                ),
            )

    def get_active_strategy(self, name: str) -> StrategyVersion | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM strategies WHERE name=? AND state='active'", (name,)
            ).fetchone()
        if row is None:
            return None
        return StrategyVersion(
            name=row["name"],
            version=row["version"],
            state=StrategyState(row["state"]),
            manifest_hash=row["manifest_hash"],
            created_at=_datetime(row["created_at"]),
            activated_at=_datetime(row["activated_at"]) if row["activated_at"] else None,
        )

    def close(self) -> None:
        """Connections are operation-scoped; no persistent handle needs closing."""


def _dump(value: Any) -> str:
    return json.dumps(
        asdict(value) if hasattr(value, "__dataclass_fields__") else value,
        default=_json_default,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _json_default(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"cannot encode {type(value).__name__}")


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _parse_request(raw: dict[str, Any], *, fallback_symbol: str, fallback: str) -> AnalysisRequest:
    return AnalysisRequest(
        symbol=raw.get("symbol", fallback_symbol),
        profile=AnalysisProfile(raw.get("profile", fallback)),
        as_of=_datetime(raw["as_of"]) if raw.get("as_of") else None,
        force_refresh=bool(raw.get("force_refresh", False)),
        requested_engines=tuple(raw["requested_engines"]) if raw.get("requested_engines") else None,
        request_id=raw.get("request_id", ""),
        deadline=_datetime(raw["deadline"]) if raw.get("deadline") else None,
        enable_sandbox=bool(raw.get("enable_sandbox", False)),
    )


def _job_values(job: JobRecord) -> tuple[Any, ...]:
    return (
        job.job_id,
        job.job_type.value,
        job.dedupe_key,
        job.status.value,
        job.progress,
        job.request_json,
        job.result_ref,
        job.error_code,
        job.created_at.isoformat(),
        job.started_at.isoformat() if job.started_at else None,
        job.finished_at.isoformat() if job.finished_at else None,
        job.deadline_at.isoformat() if job.deadline_at else None,
        int(job.cancel_requested),
    )


def _parse_job(row: sqlite3.Row) -> JobRecord:
    return JobRecord(
        job_id=row["job_id"],
        job_type=JobType(row["job_type"]),
        status=RunStatus(row["status"]),
        progress=float(row["progress"]),
        request_json=row["request_json"],
        created_at=_datetime(row["created_at"]),
        dedupe_key=row["dedupe_key"],
        result_ref=row["result_ref"],
        error_code=row["error_code"],
        started_at=_datetime(row["started_at"]) if row["started_at"] else None,
        finished_at=_datetime(row["finished_at"]) if row["finished_at"] else None,
        deadline_at=_datetime(row["deadline_at"]) if row["deadline_at"] else None,
        cancel_requested=bool(row["cancel_requested"]),
    )


def _parse_warning(raw: dict[str, Any]) -> DataWarning:
    return DataWarning(**raw)


def _parse_evidence(raw: dict[str, Any]) -> Evidence:
    return Evidence(**raw)


def _parse_risk(raw: dict[str, Any]) -> Risk:
    return Risk(**raw)


def _parse_engine_result(raw: dict[str, Any]) -> EngineResult:
    return EngineResult(
        engine_name=raw["engine_name"],
        engine_version=raw["engine_version"],
        symbol=raw["symbol"],
        engine_score=raw["engine_score"],
        rating=Rating(raw["rating"]),
        confidence=raw["confidence"],
        narrative=raw["narrative"],
        evidence=tuple(_parse_evidence(item) for item in raw.get("evidence", [])),
        risks=tuple(_parse_risk(item) for item in raw.get("risks", [])),
        metadata=tuple(tuple(item) for item in raw.get("metadata", [])),
    )


def _parse_engine_run(row: sqlite3.Row) -> EngineRun:
    result = _parse_engine_result(json.loads(row["result_json"])) if row["result_json"] else None
    return EngineRun(
        engine_name=row["engine_name"],
        engine_version=row["engine_version"],
        status=EngineRunStatus(row["status"]),
        deterministic=bool(row["deterministic"]),
        started_at=_datetime(row["started_at"]),
        finished_at=_datetime(row["finished_at"]) if row["finished_at"] else None,
        engine_score=row["score"],
        confidence=row["confidence"],
        result=result,
        error_code=row["error_code"],
        error_detail=row["error_detail"],
        prompt_version=row["prompt_version"],
        model=row["model"],
        duration_ms=row["duration_ms"],
    )


def _parse_consensus(raw: dict[str, Any]) -> ConsensusResult:
    return ConsensusResult(
        symbol=raw["symbol"],
        analysis_score=raw.get("analysis_score"),
        confidence=raw["confidence"],
        weight_coverage=raw["weight_coverage"],
        engines_used=tuple(raw.get("engines_used", [])),
        engines_failed=tuple(raw.get("engines_failed", [])),
        conflicts=tuple(ConsensusConflict(**item) for item in raw.get("conflicts", [])),
        weight_snapshot=tuple(tuple(item) for item in raw.get("weight_snapshot", [])),
        insufficient_reason=raw.get("insufficient_reason"),
    )


def _parse_verdict(raw: dict[str, Any]) -> Verdict:
    return Verdict(
        label=VerdictLabel(raw["label"]),
        horizon=raw["horizon"],
        summary=raw["summary"],
        bull_evidence=tuple(_parse_evidence(item) for item in raw.get("bull_evidence", [])),
        bear_evidence=tuple(_parse_evidence(item) for item in raw.get("bear_evidence", [])),
        risks=tuple(_parse_risk(item) for item in raw.get("risks", [])),
        invalidation_conditions=tuple(raw.get("invalidation_conditions", [])),
        confidence=raw.get("confidence", 0.0),
    )
