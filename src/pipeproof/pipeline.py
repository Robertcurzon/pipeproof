"""End-to-end PipeProof pipeline orchestration."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pipeproof.contracts import generate_contract
from pipeproof.drift import detect_drift
from pipeproof.investigator import investigate
from pipeproof.io import load_table
from pipeproof.models import DataContract, DriftSignal
from pipeproof.profiler import profile_batch
from pipeproof.store import ArtifactStore
from pipeproof.validator import validate_frame


@dataclass(slots=True)
class PipelineRun:
    """High-level result returned to CLI, API, and web clients."""

    run_id: str
    status: str
    health_score: int
    accepted_rows: int
    quarantined_rows: int
    drift_signals: int
    artifacts: dict[str, str]
    investigation: dict[str, Any]


def _health_score(
    validation_status: str,
    failed_errors: int,
    failed_warnings: int,
    drift: list[DriftSignal],
) -> int:
    score = 100 - failed_errors * 7 - failed_warnings * 2
    score -= sum(5 if item.severity == "error" else 2 for item in drift)
    if validation_status == "failed":
        score = min(score, 69)
    return max(0, min(100, score))


def run_pipeline(
    current_path: str | Path,
    baseline_path: str | Path | None = None,
    *,
    contract: DataContract | None = None,
    store_root: str | Path = "data/runtime/runs",
    dataset_name: str = "incoming_batch",
) -> PipelineRun:
    """Run ingestion, profiling, contract checks, drift, and persistence."""

    current_source = Path(current_path)
    baseline_source = Path(baseline_path) if baseline_path else current_source
    current_frame = load_table(current_source)
    baseline_frame = load_table(baseline_source)
    baseline_profile = profile_batch(baseline_frame)
    current_profile = profile_batch(current_frame)
    active_contract = contract or generate_contract(baseline_profile, dataset_name)
    accepted, quarantined, validation = validate_frame(current_frame, active_contract)
    drift = detect_drift(baseline_profile, current_profile, active_contract)
    investigation = investigate(validation, drift)

    failed_errors = sum(
        not check.passed and check.severity == "error" for check in validation.checks
    )
    failed_warnings = sum(
        not check.passed and check.severity == "warning" for check in validation.checks
    )
    score = _health_score(validation.status, failed_errors, failed_warnings, drift)
    created_at = datetime.now(UTC)
    run_id = f"{created_at:%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"
    status = validation.status
    if status != "failed" and drift:
        status = "degraded"
    manifest = {
        "run_id": run_id,
        "dataset_name": dataset_name,
        "created_at": created_at.isoformat(),
        "status": status,
        "health_score": score,
        "source_file": current_source.name,
        "baseline_file": baseline_source.name,
        "source_rows": len(current_frame),
        "accepted_rows": len(accepted),
        "quarantined_rows": len(quarantined),
        "failed_checks": failed_errors + failed_warnings,
        "drift_signals": len(drift),
    }
    artifacts = ArtifactStore(store_root).save_run(
        run_id,
        manifest,
        baseline_profile,
        current_profile,
        active_contract,
        validation,
        drift,
        investigation,
        accepted,
        quarantined,
    )
    return PipelineRun(
        run_id=run_id,
        status=status,
        health_score=score,
        accepted_rows=len(accepted),
        quarantined_rows=len(quarantined),
        drift_signals=len(drift),
        artifacts=artifacts,
        investigation=investigation,
    )
