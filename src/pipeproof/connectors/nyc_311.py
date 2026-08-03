"""Incremental-friendly connector for NYC Open Data 311 requests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd


ENDPOINT = "https://data.cityofnewyork.us/resource/erm2-nwe9.json"
DEFAULT_COLUMNS = [
    "unique_key",
    "created_date",
    "closed_date",
    "agency",
    "complaint_type",
    "descriptor",
    "borough",
    "status",
]


def fetch_nyc_311(
    output_path: str | Path,
    *,
    days: int = 7,
    limit: int = 2_000,
    timeout: int = 30,
) -> Path:
    """Fetch recent, non-sensitive NYC 311 records into a CSV snapshot."""

    since = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00.000")
    params = {
        "$select": ",".join(DEFAULT_COLUMNS),
        "$where": f"created_date >= '{since}'",
        "$order": "created_date DESC",
        "$limit": min(max(limit, 1), 50_000),
    }
    request = Request(
        f"{ENDPOINT}?{urlencode(params)}",
        headers={"User-Agent": "PipeProof/0.1 public-data-demo"},
    )
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed public endpoint
        payload = json.loads(response.read().decode("utf-8"))
    if not payload:
        raise RuntimeError("NYC Open Data returned no records for the selected window.")
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(payload).to_csv(path, index=False)
    return path
