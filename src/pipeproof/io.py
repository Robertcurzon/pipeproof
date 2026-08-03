"""Tabular input loading and normalization."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

SUPPORTED_EXTENSIONS = {".csv", ".parquet", ".json", ".jsonl"}


def normalize_column_name(name: object) -> str:
    """Normalize a source column into a stable snake-case identifier."""

    text = str(name).strip().lower()
    output: list[str] = []
    previous_separator = False
    for character in text:
        if character.isalnum():
            output.append(character)
            previous_separator = False
        elif not previous_separator:
            output.append("_")
            previous_separator = True
    return "".join(output).strip("_") or "unnamed_column"


def load_table(path: str | Path) -> pd.DataFrame:
    """Load a supported tabular file and normalize its column names."""

    source = Path(path)
    suffix = source.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValueError(f"Unsupported file type '{suffix}'. Use one of: {supported}")

    if suffix == ".csv":
        frame = pd.read_csv(source)
    elif suffix == ".parquet":
        frame = pd.read_parquet(source)
    elif suffix == ".jsonl":
        frame = pd.read_json(source, lines=True)
    else:
        frame = pd.read_json(source)

    if frame.empty:
        raise ValueError("The input file contains no data rows.")

    normalized = [normalize_column_name(column) for column in frame.columns]
    if len(set(normalized)) != len(normalized):
        raise ValueError("Column normalization produced duplicate column names.")
    frame.columns = normalized
    return frame
