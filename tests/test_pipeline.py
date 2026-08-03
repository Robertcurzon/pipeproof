from __future__ import annotations

from pathlib import Path

from pipeproof.metrics import demo_metric_catalog
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


def test_pipeline_persists_metric_catalog_values_sql_and_lineage(tmp_path: Path) -> None:
    result = run_pipeline(
        ROOT / "data/sample/nyc_311_incident.csv",
        ROOT / "data/sample/nyc_311_baseline.csv",
        metric_catalog=demo_metric_catalog(),
        metric_group_by=["borough"],
        store_root=tmp_path,
        dataset_name="nyc_311",
    )

    saved = ArtifactStore(tmp_path).load_run(result.run_id)
    run_dir = tmp_path / result.run_id
    assert result.metrics_count == 5
    assert saved["metrics"]["catalog"]["name"] == "nyc_311_operations"
    assert saved["metrics"]["group_by"] == ["borough"]
    assert (run_dir / "metrics.sql").read_text(encoding="utf-8").count("SELECT") == 3
    assert (run_dir / "metrics_lineage.mmd").read_text(encoding="utf-8").startswith("flowchart LR")
