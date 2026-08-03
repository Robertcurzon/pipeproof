"""Data-contract inference and serialization."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pipeproof.models import BatchProfile, ColumnContract, DataContract


def generate_contract(profile: BatchProfile, name: str = "incoming_batch") -> DataContract:
    """Generate a conservative contract from an accepted baseline profile."""

    columns: list[ColumnContract] = []
    for item in profile.columns:
        id_like = item.name == "id" or item.name.endswith("_id") or item.name in {
            "unique_key",
            "record_id",
        }
        allowed_values: list[str] = []
        if item.dtype in {"string", "boolean"} and 0 < item.unique_count <= 12:
            allowed_values = sorted(item.top_values)
        pattern = None
        if item.pii_hint == "email":
            pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"

        bounded_measure = item.dtype in {"integer", "number"} and not id_like

        columns.append(
            ColumnContract(
                name=item.name,
                dtype=item.dtype,
                nullable=item.null_rate > 0,
                unique=id_like and item.unique_rate == 1.0,
                minimum=item.minimum if bounded_measure else None,
                maximum=item.maximum if bounded_measure else None,
                allowed_values=allowed_values,
                pattern=pattern,
                pii_hint=item.pii_hint,
            )
        )

    return DataContract(
        name=name,
        version="1.0.0",
        created_at=datetime.now(UTC).isoformat(),
        baseline_rows=profile.row_count,
        columns=columns,
    )


def _scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def contract_to_yaml(contract: DataContract) -> str:
    """Serialize a contract into readable YAML without runtime side effects."""

    lines = [
        f"name: {_scalar(contract.name)}",
        f"version: {_scalar(contract.version)}",
        f"created_at: {_scalar(contract.created_at)}",
        f"baseline_rows: {contract.baseline_rows}",
        "drift_policy:",
        f"  max_row_count_change: {contract.max_row_count_change}",
        f"  max_null_rate_change: {contract.max_null_rate_change}",
        f"  numeric_drift_threshold: {contract.numeric_drift_threshold}",
        f"  categorical_drift_threshold: {contract.categorical_drift_threshold}",
        "columns:",
    ]
    for column in contract.columns:
        lines.extend(
            [
                f"  - name: {_scalar(column.name)}",
                f"    dtype: {_scalar(column.dtype)}",
                f"    nullable: {_scalar(column.nullable)}",
                f"    unique: {_scalar(column.unique)}",
            ]
        )
        if column.minimum is not None:
            lines.append(f"    minimum: {_scalar(column.minimum)}")
        if column.maximum is not None:
            lines.append(f"    maximum: {_scalar(column.maximum)}")
        if column.allowed_values:
            values = ", ".join(_scalar(value) for value in column.allowed_values)
            lines.append(f"    allowed_values: [{values}]")
        if column.pattern:
            lines.append(f"    pattern: {_scalar(column.pattern)}")
        if column.pii_hint:
            lines.append(f"    pii_hint: {_scalar(column.pii_hint)}")
    return "\n".join(lines) + "\n"


def save_contract(contract: DataContract, path: str | Path) -> None:
    """Write a generated data contract to disk."""

    Path(path).write_text(contract_to_yaml(contract), encoding="utf-8")


def load_contract(path: str | Path) -> DataContract:
    """Load a PipeProof YAML contract."""

    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - exercised in installed package
        raise RuntimeError("PyYAML is required to load contract files.") from exc

    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    drift_policy = payload.pop("drift_policy", {})
    payload.update(drift_policy)
    return DataContract.from_dict(payload)


def contract_as_dict(contract: DataContract) -> dict[str, Any]:
    """Return the contract as a serializable dictionary."""

    return asdict(contract)
