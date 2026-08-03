"""Baseline-to-batch drift detection."""

from __future__ import annotations

import math

from pipeproof.models import BatchProfile, DataContract, DriftSignal


def _categorical_distance(left: dict[str, int], right: dict[str, int]) -> float:
    left_total = sum(left.values()) or 1
    right_total = sum(right.values()) or 1
    keys = set(left) | set(right)
    return 0.5 * sum(
        abs(left.get(key, 0) / left_total - right.get(key, 0) / right_total)
        for key in keys
    )


def detect_drift(
    baseline: BatchProfile, current: BatchProfile, contract: DataContract
) -> list[DriftSignal]:
    """Detect schema, volume, null-rate, and distribution drift."""

    signals: list[DriftSignal] = []
    baseline_columns = baseline.column_map()
    current_columns = current.column_map()

    row_change = abs(current.row_count - baseline.row_count) / max(baseline.row_count, 1)
    if row_change > contract.max_row_count_change:
        signals.append(
            DriftSignal(
                signal="row_count",
                column=None,
                score=round(row_change, 4),
                threshold=contract.max_row_count_change,
                severity="warning",
                message=(
                    f"Batch volume changed {row_change:.0%} from the baseline "
                    f"({baseline.row_count} to {current.row_count} rows)."
                ),
            )
        )

    for name in sorted(set(baseline_columns) | set(current_columns)):
        left = baseline_columns.get(name)
        right = current_columns.get(name)
        if left is None or right is None:
            signals.append(
                DriftSignal(
                    signal="schema",
                    column=name,
                    score=1.0,
                    threshold=0.0,
                    severity="error",
                    message=f"Column '{name}' was {'added' if left is None else 'removed'}.",
                )
            )
            continue
        if left.dtype != right.dtype:
            signals.append(
                DriftSignal(
                    signal="data_type",
                    column=name,
                    score=1.0,
                    threshold=0.0,
                    severity="error",
                    message=f"'{name}' changed type from {left.dtype} to {right.dtype}.",
                )
            )

        null_change = abs(right.null_rate - left.null_rate)
        if null_change > contract.max_null_rate_change:
            signals.append(
                DriftSignal(
                    signal="null_rate",
                    column=name,
                    score=round(null_change, 4),
                    threshold=contract.max_null_rate_change,
                    severity="error" if null_change > 0.25 else "warning",
                    message=(
                        f"'{name}' null rate moved from {left.null_rate:.1%} "
                        f"to {right.null_rate:.1%}."
                    ),
                )
            )

        id_like = name == "id" or name.endswith("_id") or name in {"unique_key", "record_id"}
        if (
            left.dtype in {"integer", "number"}
            and not id_like
            and left.mean is not None
            and right.mean is not None
        ):
            scale = left.stddev or max(abs(left.mean) * 0.05, 1.0)
            score = abs(right.mean - left.mean) / scale
            if math.isfinite(score) and score > contract.numeric_drift_threshold:
                signals.append(
                    DriftSignal(
                        signal="numeric_distribution",
                        column=name,
                        score=round(score, 4),
                        threshold=contract.numeric_drift_threshold,
                        severity="warning" if score < 2 else "error",
                        message=f"'{name}' mean shifted {score:.2f} baseline standard deviations.",
                    )
                )
        elif left.dtype in {"string", "boolean"}:
            score = _categorical_distance(left.top_values, right.top_values)
            if score > contract.categorical_drift_threshold:
                signals.append(
                    DriftSignal(
                        signal="categorical_distribution",
                        column=name,
                        score=round(score, 4),
                        threshold=contract.categorical_drift_threshold,
                        severity="warning",
                        message=f"'{name}' category mix changed materially ({score:.2f} distance).",
                    )
                )
    return signals
