from __future__ import annotations

from pathlib import Path

from starlette.testclient import TestClient

import web.app as web_app
from pipeproof.metrics import demo_metric_catalog
from pipeproof.store import ArtifactStore


def test_health_endpoint() -> None:
    with TestClient(web_app.app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "pipeproof"}


def test_upload_workflow_creates_run_and_cleans_raw_files(
    tmp_path: Path, monkeypatch
) -> None:
    run_root = tmp_path / "runs"
    upload_root = tmp_path / "uploads"
    monkeypatch.setattr(web_app, "STORE_ROOT", run_root)
    monkeypatch.setattr(web_app, "UPLOAD_ROOT", upload_root)
    monkeypatch.setattr(web_app, "store", ArtifactStore(run_root))
    sample_root = Path(__file__).resolve().parents[1] / "data/sample"

    with TestClient(web_app.app) as client:
        response = client.post(
            "/analyze",
            data={"dataset_name": "web_test"},
            files={
                "baseline": (
                    "baseline.csv",
                    (sample_root / "nyc_311_baseline.csv").read_bytes(),
                    "text/csv",
                ),
                "current": (
                    "current.csv",
                    (sample_root / "nyc_311_incident.csv").read_bytes(),
                    "text/csv",
                ),
            },
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/?run=")
    assert len(ArtifactStore(run_root).list_runs()) == 1
    assert not list(upload_root.glob("*"))


def test_metric_compile_api_returns_sql_and_lineage() -> None:
    catalog = demo_metric_catalog().to_dict()
    with TestClient(web_app.app) as client:
        response = client.post(
            "/api/metrics/compile",
            json={"catalog": catalog, "dialect": "bigquery", "group_by": ["borough"]},
        )

    assert response.status_code == 200
    payload = response.json()
    assert "FLOAT64" in payload["sql"]
    assert payload["lineage_mermaid"].startswith("flowchart LR")
