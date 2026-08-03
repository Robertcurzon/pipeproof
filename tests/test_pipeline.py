from __future__ import annotations

from pathlib import Path

from pipeproof.pipeline import run_pipeline
from pipeproof.store import ArtifactStore


ROOT = Path(__file__).resolve().parents[1]


def test_pipeline_persists_reproducible_artifacts(tmp_path: Path) -> None:
    result = run_pipeline(
        ROOT / "data/sample/nyc_311_incident.csv",
        ROOT / "data/sample/nyc_311_baseline.csv",
        store_root=tmp_path,
        dataset_name="nyc_311",
    )

    assert result.status == "failed"
    assert 20 <= result.health_score <= 70
    assert result.accepted_rows == 6
    saved = ArtifactStore(tmp_path).load_run(result.run_id)
    assert saved["manifest"]["quarantined_rows"] == 6
    assert saved["contract_yaml"].startswith('name: "nyc_311"')
    assert saved["investigation"]["risk"] == "High"
