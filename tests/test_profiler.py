from __future__ import annotations

import pandas as pd

from pipeproof.contracts import contract_to_yaml, generate_contract
from pipeproof.profiler import profile_batch


def test_profile_and_contract_inference() -> None:
    frame = pd.DataFrame(
        {
            "record_id": [1, 2, 3],
            "created_at": ["2026-01-01", "2026-01-02", "2026-01-03"],
            "channel": ["api", "api", "file"],
            "email": ["a@example.com", "b@example.com", "c@example.com"],
            "amount": [10.0, 12.5, 9.5],
        }
    )

    profile = profile_batch(frame)
    contract = generate_contract(profile, "orders")

    assert profile.row_count == 3
    assert profile.column_map()["created_at"].dtype == "datetime"
    assert profile.column_map()["email"].pii_hint == "email"
    assert contract.column_map()["record_id"].unique is True
    assert contract.column_map()["record_id"].maximum is None
    assert contract.column_map()["amount"].maximum == 12.5
    assert 'name: "orders"' in contract_to_yaml(contract)
