from __future__ import annotations

from pathlib import Path

from pipeproof.contracts import generate_contract
from pipeproof.drift import detect_drift
from pipeproof.io import load_table
from pipeproof.profiler import profile_batch


ROOT = Path(__file__).resolve().parents[1]


def test_drift_detects_volume_type_and_category_changes_but_ignores_id_growth() -> None:
    baseline = profile_batch(load_table(ROOT / "data/sample/nyc_311_baseline.csv"))
    current = profile_batch(load_table(ROOT / "data/sample/nyc_311_incident.csv"))
    signals = detect_drift(baseline, current, generate_contract(baseline, "nyc_311"))

    assert any(signal.signal == "row_count" for signal in signals)
    assert any(signal.column == "resolution_hours" for signal in signals)
    assert any(signal.column == "complaint_type" for signal in signals)
    assert not any(
        signal.column == "unique_key" and signal.signal == "numeric_distribution"
        for signal in signals
    )
