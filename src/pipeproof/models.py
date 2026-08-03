"""Typed models shared across the PipeProof pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class ColumnProfile:
    """Statistical and structural summary of one input column."""

    name: str
    dtype: str
    row_count: int
    null_count: int
    null_rate: float
    unique_count: int
    unique_rate: float
    minimum: Any = None
    maximum: Any = None
    mean: float | None = None
    stddev: float | None = None
    top_values: dict[str, int] = field(default_factory=dict)
    pii_hint: str | None = None


@dataclass(slots=True)
class BatchProfile:
    """Profile for a complete tabular batch."""

    row_count: int
    column_count: int
    columns: list[ColumnProfile]
    fingerprint: str

    def column_map(self) -> dict[str, ColumnProfile]:
        """Return profiles keyed by column name."""

        return {column.name: column for column in self.columns}


@dataclass(slots=True)
class ColumnContract:
    """Validation rules for a single column."""

    name: str
    dtype: str
    nullable: bool = True
    unique: bool = False
    minimum: float | str | None = None
    maximum: float | str | None = None
    allowed_values: list[str] = field(default_factory=list)
    pattern: str | None = None
    pii_hint: str | None = None


@dataclass(slots=True)
class DataContract:
    """Versioned contract inferred from an accepted baseline batch."""

    name: str
    version: str
    created_at: str
    baseline_rows: int
    columns: list[ColumnContract]
    max_row_count_change: float = 0.35
    max_null_rate_change: float = 0.10
    numeric_drift_threshold: float = 0.75
    categorical_drift_threshold: float = 0.25

    def column_map(self) -> dict[str, ColumnContract]:
        """Return contract columns keyed by name."""

        return {column.name: column for column in self.columns}

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""

        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DataContract":
        """Build a contract from a dictionary."""

        columns = [ColumnContract(**item) for item in payload.pop("columns")]
        return cls(columns=columns, **payload)


@dataclass(slots=True)
class CheckResult:
    """Outcome of one schema or data-quality check."""

    check: str
    passed: bool
    severity: str
    message: str
    column: str | None = None
    observed: Any = None
    expected: Any = None


@dataclass(slots=True)
class DriftSignal:
    """Observed difference between baseline and current batches."""

    signal: str
    column: str | None
    score: float
    threshold: float
    severity: str
    message: str


@dataclass(slots=True)
class ValidationSummary:
    """Aggregate validation result for one current batch."""

    status: str
    accepted_rows: int
    quarantined_rows: int
    checks: list[CheckResult]
