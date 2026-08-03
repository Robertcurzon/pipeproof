from __future__ import annotations

from pathlib import Path

from pipeproof.contracts import generate_contract
from pipeproof.io import load_table
from pipeproof.profiler import profile_batch
from pipeproof.validator import validate_frame

ROOT = Path(__file__).resolve().parents[1]


def test_incident_rows_are_quarantined_with_reasons() -> None:
    baseline = load_table(ROOT / "data/sample/nyc_311_baseline.csv")
    current = load_table(ROOT / "data/sample/nyc_311_incident.csv")
    contract = generate_contract(profile_batch(baseline), "nyc_311")

    accepted, quarantined, summary = validate_frame(current, contract)

    assert len(accepted) == 6
    assert len(quarantined) == 6
    assert summary.status == "failed"
    assert quarantined["_pipeproof_reasons"].str.contains("duplicate value").any()
    assert quarantined["_pipeproof_reasons"].str.contains("unexpected category").any()
