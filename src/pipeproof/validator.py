"""Contract validation with accepted and quarantined row routing."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

import pandas as pd

from pipeproof.models import CheckResult, DataContract, ValidationSummary
from pipeproof.profiler import infer_dtype


def _coerce(series: pd.Series, dtype: str) -> tuple[pd.Series, pd.Series]:
    original_not_null = series.notna()
    if dtype == "integer":
        converted = pd.to_numeric(series, errors="coerce")
        invalid = original_not_null & (converted.isna() | (converted % 1 != 0))
        return converted.astype("Int64"), invalid
    if dtype == "number":
        converted = pd.to_numeric(series, errors="coerce")
        return converted, original_not_null & converted.isna()
    if dtype == "datetime":
        converted = pd.to_datetime(series, errors="coerce", utc=True)
        return converted, original_not_null & converted.isna()
    if dtype == "boolean":
        mapping = {
            "true": True,
            "false": False,
            "yes": True,
            "no": False,
            "1": True,
            "0": False,
        }
        converted = series.map(
            lambda value: mapping.get(str(value).strip().lower()) if pd.notna(value) else pd.NA
        ).astype("boolean")
        return converted, original_not_null & converted.isna()
    return series.astype("string"), pd.Series(False, index=series.index)


def validate_frame(
    frame: pd.DataFrame, contract: DataContract
) -> tuple[pd.DataFrame, pd.DataFrame, ValidationSummary]:
    """Validate a frame and split valid rows from quarantined rows."""

    working = frame.copy()
    checks: list[CheckResult] = []
    row_reasons: dict[Any, list[str]] = defaultdict(list)
    contract_columns = contract.column_map()

    missing_columns = [name for name in contract_columns if name not in working.columns]
    for name in missing_columns:
        checks.append(
            CheckResult(
                check="required_column",
                passed=False,
                severity="error",
                column=name,
                message=f"Required column '{name}' is missing.",
                observed="missing",
                expected="present",
            )
        )

    extra_columns = [name for name in working.columns if name not in contract_columns]
    if extra_columns:
        checks.append(
            CheckResult(
                check="unexpected_columns",
                passed=False,
                severity="warning",
                message=f"Unexpected columns: {', '.join(extra_columns)}.",
                observed=extra_columns,
                expected=list(contract_columns),
            )
        )

    if missing_columns:
        for index in working.index:
            row_reasons[index].append(f"missing columns: {', '.join(missing_columns)}")

    for name, rule in contract_columns.items():
        if name not in working.columns:
            continue
        source = working[name]
        observed_dtype = infer_dtype(source)
        converted, invalid_type = _coerce(source, rule.dtype)
        working[name] = converted
        invalid_count = int(invalid_type.sum())
        checks.append(
            CheckResult(
                check="data_type",
                passed=invalid_count == 0,
                severity="error",
                column=name,
                message=(
                    f"{invalid_count} value(s) cannot be coerced to {rule.dtype}."
                    if invalid_count
                    else f"Values conform to {rule.dtype}."
                ),
                observed=observed_dtype,
                expected=rule.dtype,
            )
        )
        for index in working.index[invalid_type]:
            row_reasons[index].append(f"{name}: invalid {rule.dtype}")

        null_mask = working[name].isna()
        invalid_nulls = null_mask if not rule.nullable else pd.Series(False, index=working.index)
        checks.append(
            CheckResult(
                check="nullability",
                passed=not bool(invalid_nulls.any()),
                severity="error",
                column=name,
                message=(
                    f"{int(invalid_nulls.sum())} null value(s) violate the contract."
                    if bool(invalid_nulls.any())
                    else "Nullability requirement passed."
                ),
                observed=int(null_mask.sum()),
                expected="nullable" if rule.nullable else "not null",
            )
        )
        for index in working.index[invalid_nulls]:
            row_reasons[index].append(f"{name}: null not allowed")

        if rule.unique:
            duplicate_mask = working[name].notna() & working[name].duplicated(keep=False)
            checks.append(
                CheckResult(
                    check="uniqueness",
                    passed=not bool(duplicate_mask.any()),
                    severity="error",
                    column=name,
                    message=(
                        f"{int(duplicate_mask.sum())} row(s) contain duplicate values."
                        if bool(duplicate_mask.any())
                        else "Uniqueness requirement passed."
                    ),
                    observed=int(duplicate_mask.sum()),
                    expected=0,
                )
            )
            for index in working.index[duplicate_mask]:
                row_reasons[index].append(f"{name}: duplicate value")

        if rule.minimum is not None:
            if rule.dtype == "datetime":
                boundary = pd.to_datetime(rule.minimum, utc=True)
            else:
                boundary = float(rule.minimum)
            below = working[name].notna() & (working[name] < boundary)
            checks.append(
                CheckResult(
                    check="minimum",
                    passed=not bool(below.any()),
                    severity="error",
                    column=name,
                    message=f"{int(below.sum())} value(s) fall below {rule.minimum}.",
                    observed=int(below.sum()),
                    expected=f">= {rule.minimum}",
                )
            )
            for index in working.index[below]:
                row_reasons[index].append(f"{name}: below minimum {rule.minimum}")

        if rule.maximum is not None:
            if rule.dtype == "datetime":
                boundary = pd.to_datetime(rule.maximum, utc=True)
            else:
                boundary = float(rule.maximum)
            above = working[name].notna() & (working[name] > boundary)
            checks.append(
                CheckResult(
                    check="maximum",
                    passed=not bool(above.any()),
                    severity="error",
                    column=name,
                    message=f"{int(above.sum())} value(s) exceed {rule.maximum}.",
                    observed=int(above.sum()),
                    expected=f"<= {rule.maximum}",
                )
            )
            for index in working.index[above]:
                row_reasons[index].append(f"{name}: above baseline maximum {rule.maximum}")

        if rule.allowed_values:
            allowed = set(rule.allowed_values)
            invalid_categories = working[name].notna() & ~working[name].astype(str).isin(allowed)
            checks.append(
                CheckResult(
                    check="accepted_values",
                    passed=not bool(invalid_categories.any()),
                    severity="error",
                    column=name,
                    message=(
                        f"{int(invalid_categories.sum())} value(s) are outside the accepted set."
                    ),
                    observed=sorted(working.loc[invalid_categories, name].astype(str).unique()),
                    expected=sorted(allowed),
                )
            )
            for index in working.index[invalid_categories]:
                row_reasons[index].append(f"{name}: unexpected category")

        if rule.pattern:
            pattern = re.compile(rule.pattern)
            strings = working[name].astype("string")
            invalid_pattern = strings.notna() & ~strings.map(
                lambda value, compiled=pattern: (
                    bool(compiled.match(str(value))) if pd.notna(value) else True
                )
            )
            checks.append(
                CheckResult(
                    check="pattern",
                    passed=not bool(invalid_pattern.any()),
                    severity="error",
                    column=name,
                    message=f"{int(invalid_pattern.sum())} value(s) fail the required pattern.",
                    observed=int(invalid_pattern.sum()),
                    expected=rule.pattern,
                )
            )
            for index in working.index[invalid_pattern]:
                row_reasons[index].append(f"{name}: pattern mismatch")

    quarantine_mask = pd.Series(
        [bool(row_reasons[index]) for index in working.index], index=working.index
    )
    accepted = working.loc[~quarantine_mask].copy()
    quarantined = frame.loc[quarantine_mask].copy()
    quarantined["_pipeproof_reasons"] = [
        "; ".join(row_reasons[index]) for index in quarantined.index
    ]

    failed_errors = sum(not check.passed and check.severity == "error" for check in checks)
    failed_warnings = sum(not check.passed and check.severity == "warning" for check in checks)
    status = "failed" if failed_errors else "degraded" if failed_warnings else "passed"
    return accepted, quarantined, ValidationSummary(
        status=status,
        accepted_rows=len(accepted),
        quarantined_rows=len(quarantined),
        checks=checks,
    )
