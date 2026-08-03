"""Filesystem artifact store for reproducible pipeline runs."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

from pipeproof.contracts import save_contract
from pipeproof.models import BatchProfile, DataContract, DriftSignal, ValidationSummary


def _write_frame(frame: pd.DataFrame, path_without_suffix: Path) -> str:
    try:
        path = path_without_suffix.with_suffix(".parquet")
        frame.to_parquet(path, index=False)
    except (ImportError, ValueError):
        path = path_without_suffix.with_suffix(".csv")
        frame.to_csv(path, index=False)
    return path.name


class ArtifactStore:
    """Persist and retrieve immutable run artifacts."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save_run(
        self,
        run_id: str,
        manifest: dict[str, Any],
        baseline_profile: BatchProfile,
        current_profile: BatchProfile,
        contract: DataContract,
        validation: ValidationSummary,
        drift: list[DriftSignal],
        investigation: dict[str, Any],
        accepted: pd.DataFrame,
        quarantined: pd.DataFrame,
    ) -> dict[str, str]:
        """Persist all artifacts produced by one pipeline run."""

        run_dir = self.root / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        accepted_name = _write_frame(accepted, run_dir / "accepted")
        quarantine_name = _write_frame(quarantined, run_dir / "quarantined")
        save_contract(contract, run_dir / "contract.yaml")

        payloads = {
            "baseline_profile.json": asdict(baseline_profile),
            "current_profile.json": asdict(current_profile),
            "validation.json": asdict(validation),
            "drift.json": [asdict(item) for item in drift],
            "investigation.json": investigation,
        }
        manifest = {
            **manifest,
            "artifacts": {
                "accepted": accepted_name,
                "quarantined": quarantine_name,
                "contract": "contract.yaml",
            },
        }
        payloads["manifest.json"] = manifest
        for filename, payload in payloads.items():
            (run_dir / filename).write_text(
                json.dumps(payload, indent=2, default=str), encoding="utf-8"
            )
        return manifest["artifacts"]

    def list_runs(self) -> list[dict[str, Any]]:
        """Return saved run manifests in newest-first order."""

        manifests: list[dict[str, Any]] = []
        for path in self.root.glob("*/manifest.json"):
            try:
                manifests.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        return sorted(manifests, key=lambda item: item.get("created_at", ""), reverse=True)

    def load_run(self, run_id: str) -> dict[str, Any]:
        """Load the JSON artifacts needed by the web interface."""

        run_dir = self.root / run_id
        if not run_dir.is_dir() or run_dir.parent != self.root:
            raise FileNotFoundError(run_id)
        names = [
            "manifest.json",
            "baseline_profile.json",
            "current_profile.json",
            "validation.json",
            "drift.json",
            "investigation.json",
        ]
        result = {
            name.removesuffix(".json"): json.loads((run_dir / name).read_text(encoding="utf-8"))
            for name in names
        }
        result["contract_yaml"] = (run_dir / "contract.yaml").read_text(encoding="utf-8")
        quarantine_path = next(run_dir.glob("quarantined.*"), None)
        if quarantine_path and quarantine_path.suffix == ".parquet":
            quarantine = pd.read_parquet(quarantine_path)
        elif quarantine_path:
            quarantine = pd.read_csv(quarantine_path)
        else:
            quarantine = pd.DataFrame()
        result["quarantine_preview"] = quarantine.head(8).fillna("").to_dict(orient="records")
        return result

    def artifact_path(self, run_id: str, filename: str) -> Path:
        """Resolve a whitelisted artifact path for download."""

        run = self.load_run(run_id)
        allowed = set(run["manifest"].get("artifacts", {}).values())
        if filename not in allowed:
            raise FileNotFoundError(filename)
        path = self.root / run_id / filename
        if not path.is_file():
            raise FileNotFoundError(filename)
        return path
