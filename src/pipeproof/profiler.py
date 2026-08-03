"""Schema inference and batch profiling."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

import numpy as np
import pandas as pd

from pipeproof.models import BatchProfile, ColumnProfile


PII_PATTERNS = {
    "email": re.compile(r"(^|_)(email|e_mail)($|_)"),
    "phone": re.compile(r"(^|_)(phone|mobile|telephone)($|_)"),
    "person_name": re.compile(r"(^|_)(name|first_name|last_name|customer_name)($|_)"),
    "address": re.compile(r"(^|_)(address|street|postal|zip)($|_)"),
    "government_id": re.compile(r"(^|_)(ssn|tax_id|passport)($|_)"),
}


def infer_dtype(series: pd.Series) -> str:
    """Infer a portable logical type for a pandas series."""

    non_null = series.dropna()
    if non_null.empty:
        return "string"
    if pd.api.types.is_bool_dtype(non_null):
        return "boolean"
    if pd.api.types.is_integer_dtype(non_null):
        return "integer"
    if pd.api.types.is_numeric_dtype(non_null):
        return "number"
    if pd.api.types.is_datetime64_any_dtype(non_null):
        return "datetime"

    values = non_null.astype(str).str.strip()
    lowered = set(values.str.lower().unique())
    if lowered and lowered <= {"true", "false", "yes", "no", "0", "1"}:
        return "boolean"

    numeric = pd.to_numeric(values, errors="coerce")
    if float(numeric.notna().mean()) >= 0.98:
        return "integer" if np.allclose(numeric.dropna() % 1, 0) else "number"

    name_hint = str(series.name).lower()
    if any(token in name_hint for token in ("date", "time", "timestamp", "_at")):
        parsed = pd.to_datetime(values, errors="coerce", utc=True)
        if float(parsed.notna().mean()) >= 0.90:
            return "datetime"
    return "string"


def detect_pii(column_name: str) -> str | None:
    """Return a conservative PII hint inferred from the column name."""

    for label, pattern in PII_PATTERNS.items():
        if pattern.search(column_name):
            return label
    return None


def _json_value(value: Any) -> Any:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    return value


def profile_batch(frame: pd.DataFrame) -> BatchProfile:
    """Compute structural and distribution statistics for a batch."""

    profiles: list[ColumnProfile] = []
    row_count = len(frame)
    for name in frame.columns:
        series = frame[name]
        dtype = infer_dtype(series)
        non_null = series.dropna()
        null_count = int(series.isna().sum())
        unique_count = int(non_null.nunique(dropna=True))
        minimum: Any = None
        maximum: Any = None
        mean: float | None = None
        stddev: float | None = None

        if dtype in {"integer", "number"}:
            numeric = pd.to_numeric(non_null, errors="coerce").dropna()
            if not numeric.empty:
                minimum = float(numeric.min())
                maximum = float(numeric.max())
                mean = float(numeric.mean())
                stddev = float(numeric.std(ddof=0))
        elif dtype == "datetime":
            dates = pd.to_datetime(non_null, errors="coerce", utc=True).dropna()
            if not dates.empty:
                minimum = dates.min().isoformat()
                maximum = dates.max().isoformat()
        elif not non_null.empty:
            strings = non_null.astype(str)
            minimum = str(strings.min())
            maximum = str(strings.max())

        top_counts = non_null.astype(str).value_counts().head(8)
        top_values = {str(key): int(value) for key, value in top_counts.items()}
        profiles.append(
            ColumnProfile(
                name=name,
                dtype=dtype,
                row_count=row_count,
                null_count=null_count,
                null_rate=round(null_count / row_count, 6),
                unique_count=unique_count,
                unique_rate=round(unique_count / max(len(non_null), 1), 6),
                minimum=_json_value(minimum),
                maximum=_json_value(maximum),
                mean=mean,
                stddev=stddev,
                top_values=top_values,
                pii_hint=detect_pii(name),
            )
        )

    fingerprint_input = [
        {"name": item.name, "dtype": item.dtype, "null_rate": item.null_rate}
        for item in profiles
    ]
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_input, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return BatchProfile(
        row_count=row_count,
        column_count=len(frame.columns),
        columns=profiles,
        fingerprint=fingerprint,
    )
