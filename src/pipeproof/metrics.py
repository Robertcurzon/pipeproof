"""Governed semantic metrics, SQL compilation, execution, tests, and lineage."""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd


IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
METRIC_TYPES = {"count", "count_distinct", "sum", "average", "minimum", "maximum", "ratio"}
FILTER_OPERATORS = {"eq", "ne", "in", "not_in", "gt", "gte", "lt", "lte", "is_null", "not_null"}
TEST_TYPES = {"not_null", "non_negative", "minimum", "maximum"}
DIALECTS = {"duckdb", "postgres", "bigquery"}


@dataclass(frozen=True, slots=True)
class MetricFilter:
    """A row filter attached to one governed metric."""

    column: str
    operator: str
    value: Any = None


@dataclass(frozen=True, slots=True)
class MetricTest:
    """A post-computation assertion for one metric."""

    test: str
    value: float | None = None
    severity: str = "warning"


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    """One governed measure in the semantic catalog."""

    name: str
    label: str
    description: str
    type: str
    column: str | None = None
    numerator: str | None = None
    denominator: str | None = None
    filters: tuple[MetricFilter, ...] = ()
    tests: tuple[MetricTest, ...] = ()
    format: str = "number"


@dataclass(slots=True)
class MetricCatalog:
    """Versioned semantic contract for a logical dataset."""

    name: str
    version: str
    source_table: str
    time_column: str | None
    dimensions: list[str]
    metrics: list[MetricDefinition]

    def metric_map(self) -> dict[str, MetricDefinition]:
        """Return metric definitions keyed by name."""

        return {metric.name: metric for metric in self.metrics}

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON/YAML-safe catalog representation."""

        return {
            "name": self.name,
            "version": self.version,
            "source": {"table": self.source_table, "time_column": self.time_column},
            "dimensions": self.dimensions,
            "metrics": [
                {
                    **{key: value for key, value in asdict(metric).items() if key not in {"filters", "tests"}},
                    "filters": [asdict(item) for item in metric.filters],
                    "tests": [asdict(item) for item in metric.tests],
                }
                for metric in self.metrics
            ],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MetricCatalog":
        """Parse a catalog from a mapping and validate its structure."""

        source = payload.get("source", {})
        metrics: list[MetricDefinition] = []
        for raw in payload.get("metrics", []):
            filters = tuple(
                MetricFilter(
                    column=str(item["column"]),
                    operator=str(item["operator"]),
                    value=item.get("value"),
                )
                for item in raw.get("filters", [])
            )
            tests = tuple(
                MetricTest(
                    test=str(item["test"]),
                    value=float(item["value"]) if item.get("value") is not None else None,
                    severity=str(item.get("severity", "warning")),
                )
                for item in raw.get("tests", [])
            )
            name = str(raw["name"])
            metrics.append(
                MetricDefinition(
                    name=name,
                    label=str(raw.get("label", name.replace("_", " ").title())),
                    description=str(raw.get("description", "")),
                    type=str(raw["type"]),
                    column=str(raw["column"]) if raw.get("column") is not None else None,
                    numerator=str(raw["numerator"]) if raw.get("numerator") is not None else None,
                    denominator=str(raw["denominator"]) if raw.get("denominator") is not None else None,
                    filters=filters,
                    tests=tests,
                    format=str(raw.get("format", "number")),
                )
            )
        catalog = cls(
            name=str(payload.get("name", "metrics")),
            version=str(payload.get("version", "1.0")),
            source_table=str(source.get("table", "accepted")),
            time_column=(
                str(source["time_column"]) if source.get("time_column") is not None else None
            ),
            dimensions=[str(value) for value in payload.get("dimensions", [])],
            metrics=metrics,
        )
        validate_catalog(catalog)
        return catalog


@dataclass(frozen=True, slots=True)
class MetricTestResult:
    """Observed outcome of a metric assertion."""

    metric: str
    test: str
    passed: bool
    severity: str
    observed: float | None
    expected: str


@dataclass(slots=True)
class MetricRun:
    """Computed metrics plus reproducible SQL, tests, and lineage."""

    values: pd.DataFrame
    sql: dict[str, str]
    tests: list[MetricTestResult]
    lineage: dict[str, Any]
    lineage_mermaid: str
    catalog: MetricCatalog
    group_by: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        """Return JSON-safe metric run metadata and values."""

        clean_values = self.values.where(pd.notna(self.values), None)
        return {
            "catalog": {"name": self.catalog.name, "version": self.catalog.version},
            "group_by": self.group_by,
            "metric_count": len(self.catalog.metrics),
            "row_count": len(self.values),
            "values": clean_values.to_dict(orient="records"),
            "tests": [asdict(item) for item in self.tests],
            "failed_tests": sum(not item.passed for item in self.tests),
            "sql": self.sql,
            "lineage": self.lineage,
        }


def load_metric_catalog(path: str | Path) -> MetricCatalog:
    """Load a governed metric catalog from YAML."""

    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("PyYAML is required to load metric catalogs") from exc
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Metric catalog root must be a mapping")
    return MetricCatalog.from_dict(payload)


def metric_catalog_to_yaml(catalog: MetricCatalog) -> str:
    """Serialize a catalog as YAML, with JSON as a dependency-free YAML subset fallback."""

    try:
        import yaml
    except ImportError:
        return json.dumps(catalog.to_dict(), indent=2) + "\n"
    return yaml.safe_dump(catalog.to_dict(), sort_keys=False, allow_unicode=False)


def demo_metric_catalog() -> MetricCatalog:
    """Return the built-in NYC 311 semantic catalog without file I/O."""

    return MetricCatalog.from_dict(
        {
            "name": "nyc_311_operations",
            "version": "1.0",
            "source": {"table": "accepted", "time_column": "created_date"},
            "dimensions": ["agency", "complaint_type", "borough", "status", "channel"],
            "metrics": [
                {
                    "name": "service_requests",
                    "label": "Service Requests",
                    "description": "Accepted service-request records.",
                    "type": "count",
                    "tests": [{"test": "minimum", "value": 1, "severity": "error"}],
                },
                {
                    "name": "closed_requests",
                    "label": "Closed Requests",
                    "description": "Requests with a Closed status.",
                    "type": "count",
                    "filters": [{"column": "status", "operator": "eq", "value": "Closed"}],
                    "tests": [{"test": "non_negative"}],
                },
                {
                    "name": "average_resolution_hours",
                    "label": "Average Resolution Hours",
                    "description": "Mean resolution time for accepted requests.",
                    "type": "average",
                    "column": "resolution_hours",
                    "tests": [{"test": "non_negative"}],
                    "format": "duration_hours",
                },
                {
                    "name": "slow_resolutions",
                    "label": "Slow Resolutions",
                    "description": "Requests requiring more than 24 hours.",
                    "type": "count",
                    "filters": [
                        {"column": "resolution_hours", "operator": "gt", "value": 24}
                    ],
                },
                {
                    "name": "closure_rate",
                    "label": "Closure Rate",
                    "description": "Closed requests divided by accepted service requests.",
                    "type": "ratio",
                    "numerator": "closed_requests",
                    "denominator": "service_requests",
                    "tests": [
                        {"test": "minimum", "value": 0},
                        {"test": "maximum", "value": 1},
                    ],
                    "format": "percent",
                },
            ],
        }
    )


def _check_identifier(value: str, label: str) -> None:
    if not IDENTIFIER.fullmatch(value):
        raise ValueError(f"{label} must be a safe SQL identifier: {value}")


def validate_catalog(catalog: MetricCatalog, columns: list[str] | None = None) -> None:
    """Validate names, references, operators, tests, and optional source columns."""

    _check_identifier(catalog.source_table, "source table")
    names = [metric.name for metric in catalog.metrics]
    if not names:
        raise ValueError("Metric catalog must define at least one metric")
    if len(set(names)) != len(names):
        raise ValueError("Metric names must be unique")
    for dimension in catalog.dimensions:
        _check_identifier(dimension, "dimension")
    if catalog.time_column:
        _check_identifier(catalog.time_column, "time column")
    available = set(columns) if columns is not None else None
    metric_map = catalog.metric_map()

    for metric in catalog.metrics:
        _check_identifier(metric.name, "metric name")
        if metric.type not in METRIC_TYPES:
            raise ValueError(f"Unsupported metric type '{metric.type}' for {metric.name}")
        if metric.type in {"count_distinct", "sum", "average", "minimum", "maximum"} and not metric.column:
            raise ValueError(f"Metric {metric.name} requires a column")
        if metric.type == "ratio":
            if metric.numerator not in metric_map or metric.denominator not in metric_map:
                raise ValueError(f"Ratio metric {metric.name} references unknown metrics")
        if metric.column:
            _check_identifier(metric.column, f"column for {metric.name}")
            if available is not None and metric.column not in available:
                raise ValueError(f"Metric {metric.name} references missing column {metric.column}")
        for item in metric.filters:
            _check_identifier(item.column, f"filter column for {metric.name}")
            if item.operator not in FILTER_OPERATORS:
                raise ValueError(f"Unsupported filter operator {item.operator}")
            if available is not None and item.column not in available:
                raise ValueError(f"Metric {metric.name} filters missing column {item.column}")
        for test in metric.tests:
            if test.test not in TEST_TYPES:
                raise ValueError(f"Unsupported metric test {test.test}")
            if test.severity not in {"warning", "error"}:
                raise ValueError("Metric test severity must be warning or error")

    if available is not None:
        missing_dimensions = set(catalog.dimensions) - available
        if missing_dimensions:
            raise ValueError(f"Missing dimension columns: {', '.join(sorted(missing_dimensions))}")
        if catalog.time_column and catalog.time_column not in available:
            raise ValueError(f"Missing time column: {catalog.time_column}")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visiting:
            raise ValueError(f"Metric dependency cycle detected at {name}")
        if name in visited:
            return
        visiting.add(name)
        metric = metric_map[name]
        if metric.type == "ratio":
            visit(metric.numerator or "")
            visit(metric.denominator or "")
        visiting.remove(name)
        visited.add(name)

    for name in names:
        visit(name)


def _quote(identifier: str, dialect: str) -> str:
    _check_identifier(identifier, "SQL identifier")
    marker = "`" if dialect == "bigquery" else '"'
    return f"{marker}{identifier}{marker}"


def _literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Metric filters cannot contain non-finite numbers")
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _filter_sql(filters: tuple[MetricFilter, ...], dialect: str) -> str:
    clauses: list[str] = []
    operators = {"eq": "=", "ne": "!=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
    for item in filters:
        column = _quote(item.column, dialect)
        if item.operator in operators:
            clauses.append(f"{column} {operators[item.operator]} {_literal(item.value)}")
        elif item.operator in {"in", "not_in"}:
            if not isinstance(item.value, list) or not item.value:
                raise ValueError(f"Filter {item.operator} requires a non-empty list")
            keyword = "IN" if item.operator == "in" else "NOT IN"
            clauses.append(f"{column} {keyword} ({', '.join(_literal(value) for value in item.value)})")
        elif item.operator == "is_null":
            clauses.append(f"{column} IS NULL")
        elif item.operator == "not_null":
            clauses.append(f"{column} IS NOT NULL")
    return " AND ".join(clauses) or "TRUE"


def _metric_expression(
    metric: MetricDefinition,
    catalog: MetricCatalog,
    dialect: str,
    stack: tuple[str, ...] = (),
) -> str:
    condition = _filter_sql(metric.filters, dialect)
    column = _quote(metric.column, dialect) if metric.column else None
    if metric.type == "count":
        return "COUNT(*)" if not metric.filters else f"SUM(CASE WHEN {condition} THEN 1 ELSE 0 END)"
    if metric.type == "count_distinct":
        return f"COUNT(DISTINCT {column})" if not metric.filters else f"COUNT(DISTINCT CASE WHEN {condition} THEN {column} END)"
    if metric.type == "sum":
        return f"SUM({column})" if not metric.filters else f"SUM(CASE WHEN {condition} THEN {column} ELSE 0 END)"
    function = {"average": "AVG", "minimum": "MIN", "maximum": "MAX"}.get(metric.type)
    if function:
        return f"{function}({column})" if not metric.filters else f"{function}(CASE WHEN {condition} THEN {column} END)"
    if metric.type == "ratio":
        if metric.name in stack:
            raise ValueError(f"Metric dependency cycle detected at {metric.name}")
        metric_map = catalog.metric_map()
        numerator = _metric_expression(metric_map[metric.numerator or ""], catalog, dialect, (*stack, metric.name))
        denominator = _metric_expression(metric_map[metric.denominator or ""], catalog, dialect, (*stack, metric.name))
        cast_type = {"duckdb": "DOUBLE", "postgres": "DOUBLE PRECISION", "bigquery": "FLOAT64"}[dialect]
        return f"CAST(({numerator}) AS {cast_type}) / NULLIF(({denominator}), 0)"
    raise ValueError(f"Unsupported metric type: {metric.type}")


def compile_metrics_sql(
    catalog: MetricCatalog,
    *,
    dialect: str = "duckdb",
    selected_metrics: list[str] | None = None,
    group_by: list[str] | None = None,
    table_override: str | None = None,
) -> str:
    """Compile a metric query for DuckDB, PostgreSQL, or BigQuery."""

    if dialect not in DIALECTS:
        raise ValueError(f"Unsupported SQL dialect: {dialect}")
    validate_catalog(catalog)
    metric_map = catalog.metric_map()
    names = selected_metrics or [metric.name for metric in catalog.metrics]
    unknown = set(names) - set(metric_map)
    if unknown:
        raise ValueError(f"Unknown metrics: {', '.join(sorted(unknown))}")
    dimensions = group_by or []
    invalid_dimensions = set(dimensions) - set(catalog.dimensions)
    if invalid_dimensions:
        raise ValueError(f"Unknown dimensions: {', '.join(sorted(invalid_dimensions))}")
    table = table_override or catalog.source_table
    select_items = [_quote(dimension, dialect) for dimension in dimensions]
    select_items.extend(
        f"{_metric_expression(metric_map[name], catalog, dialect)} AS {_quote(name, dialect)}"
        for name in names
    )
    sql = "SELECT\n  " + ",\n  ".join(select_items) + f"\nFROM {_quote(table, dialect)}"
    if dimensions:
        quoted = ", ".join(_quote(item, dialect) for item in dimensions)
        sql += f"\nGROUP BY {quoted}\nORDER BY {quoted}"
    return sql + ";"


def _apply_filters(frame: pd.DataFrame, filters: tuple[MetricFilter, ...]) -> pd.DataFrame:
    selected = frame
    for item in filters:
        series = selected[item.column]
        if item.operator == "eq":
            mask = series == item.value
        elif item.operator == "ne":
            mask = series != item.value
        elif item.operator == "in":
            mask = series.isin(item.value)
        elif item.operator == "not_in":
            mask = ~series.isin(item.value)
        elif item.operator == "gt":
            mask = series > item.value
        elif item.operator == "gte":
            mask = series >= item.value
        elif item.operator == "lt":
            mask = series < item.value
        elif item.operator == "lte":
            mask = series <= item.value
        elif item.operator == "is_null":
            mask = series.isna()
        else:
            mask = series.notna()
        selected = selected.loc[mask.fillna(False)]
    return selected


def _metric_value(
    frame: pd.DataFrame,
    metric: MetricDefinition,
    metric_map: dict[str, MetricDefinition],
    stack: tuple[str, ...] = (),
) -> float | int | None:
    selected = _apply_filters(frame, metric.filters)
    if metric.type == "count":
        return len(selected)
    if metric.type == "count_distinct":
        return int(selected[metric.column or ""].nunique(dropna=True))
    if metric.type == "ratio":
        if metric.name in stack:
            raise ValueError(f"Metric dependency cycle detected at {metric.name}")
        numerator = _metric_value(selected, metric_map[metric.numerator or ""], metric_map, (*stack, metric.name))
        denominator = _metric_value(selected, metric_map[metric.denominator or ""], metric_map, (*stack, metric.name))
        if denominator in {None, 0} or numerator is None:
            return None
        return float(numerator) / float(denominator)
    numeric = pd.to_numeric(selected[metric.column or ""], errors="coerce").dropna()
    if numeric.empty:
        return None
    if metric.type == "sum":
        return float(numeric.sum())
    if metric.type == "average":
        return float(numeric.mean())
    if metric.type == "minimum":
        return float(numeric.min())
    if metric.type == "maximum":
        return float(numeric.max())
    raise ValueError(f"Unsupported metric type: {metric.type}")


def _test_metrics(values: pd.DataFrame, catalog: MetricCatalog) -> list[MetricTestResult]:
    results: list[MetricTestResult] = []
    for metric in catalog.metrics:
        if metric.name not in values:
            continue
        numeric = pd.to_numeric(values[metric.name], errors="coerce")
        for test in metric.tests:
            if test.test == "not_null":
                passed = bool(numeric.notna().all())
                observed = float(numeric.isna().sum())
                expected = "0 null values"
            elif test.test == "non_negative":
                passed = bool((numeric.dropna() >= 0).all())
                observed = float(numeric.min()) if numeric.notna().any() else None
                expected = ">= 0"
            elif test.test == "minimum":
                passed = bool((numeric.dropna() >= float(test.value or 0)).all())
                observed = float(numeric.min()) if numeric.notna().any() else None
                expected = f">= {test.value}"
            else:
                passed = bool((numeric.dropna() <= float(test.value or 0)).all())
                observed = float(numeric.max()) if numeric.notna().any() else None
                expected = f"<= {test.value}"
            results.append(MetricTestResult(metric.name, test.test, passed, test.severity, observed, expected))
    return results


def metric_lineage(catalog: MetricCatalog) -> tuple[dict[str, Any], str]:
    """Build machine-readable and Mermaid lineage for the catalog."""

    nodes: list[dict[str, str]] = [
        {"id": f"source:{catalog.source_table}", "label": catalog.source_table, "type": "source"}
    ]
    edges: list[dict[str, str]] = []
    column_nodes: set[str] = set()
    for dimension in catalog.dimensions:
        node_id = f"column:{dimension}"
        column_nodes.add(node_id)
        nodes.append({"id": node_id, "label": dimension, "type": "dimension"})
        edges.append({"from": f"source:{catalog.source_table}", "to": node_id, "type": "contains"})
    for metric in catalog.metrics:
        metric_id = f"metric:{metric.name}"
        nodes.append({"id": metric_id, "label": metric.label, "type": "metric"})
        dependencies = [item.column for item in metric.filters]
        if metric.column:
            dependencies.append(metric.column)
        for column in sorted(set(dependencies)):
            node_id = f"column:{column}"
            if node_id not in column_nodes:
                column_nodes.add(node_id)
                nodes.append({"id": node_id, "label": column, "type": "column"})
                edges.append({"from": f"source:{catalog.source_table}", "to": node_id, "type": "contains"})
            edges.append({"from": node_id, "to": metric_id, "type": "derives"})
        if metric.type == "count" and not dependencies:
            edges.append({"from": f"source:{catalog.source_table}", "to": metric_id, "type": "counts"})
        if metric.type == "ratio":
            edges.append({"from": f"metric:{metric.numerator}", "to": metric_id, "type": "numerator"})
            edges.append({"from": f"metric:{metric.denominator}", "to": metric_id, "type": "denominator"})

    safe_ids = {node["id"]: f"N{index}" for index, node in enumerate(nodes)}
    lines = ["flowchart LR"]
    for node in nodes:
        escaped = node["label"].replace('"', "'")
        lines.append(f'    {safe_ids[node["id"]]}["{escaped}"]')
    for edge in edges:
        lines.append(f'    {safe_ids[edge["from"]]} -->|{edge["type"]}| {safe_ids[edge["to"]]}')
    return {"nodes": nodes, "edges": edges}, "\n".join(lines) + "\n"


def execute_metrics(
    frame: pd.DataFrame,
    catalog: MetricCatalog,
    *,
    group_by: list[str] | None = None,
    selected_metrics: list[str] | None = None,
) -> MetricRun:
    """Execute governed metrics locally and emit SQL for all supported dialects."""

    columns = [str(column) for column in frame.columns]
    validate_catalog(catalog, columns)
    dimensions = group_by or []
    invalid = set(dimensions) - set(catalog.dimensions)
    if invalid:
        raise ValueError(f"Unknown dimensions: {', '.join(sorted(invalid))}")
    metric_map = catalog.metric_map()
    names = selected_metrics or [metric.name for metric in catalog.metrics]
    unknown = set(names) - set(metric_map)
    if unknown:
        raise ValueError(f"Unknown metrics: {', '.join(sorted(unknown))}")

    rows: list[dict[str, Any]] = []
    if dimensions:
        grouper: str | list[str] = dimensions[0] if len(dimensions) == 1 else dimensions
        groups = frame.groupby(grouper, dropna=False, sort=True)
        for keys, subset in groups:
            key_values = (keys,) if len(dimensions) == 1 else tuple(keys)
            row = dict(zip(dimensions, key_values, strict=True))
            row.update({name: _metric_value(subset, metric_map[name], metric_map) for name in names})
            rows.append(row)
    else:
        rows.append({name: _metric_value(frame, metric_map[name], metric_map) for name in names})
    values = pd.DataFrame(rows, columns=[*dimensions, *names])
    tests = _test_metrics(values, catalog)
    lineage, mermaid = metric_lineage(catalog)
    sql = {
        dialect: compile_metrics_sql(
            catalog,
            dialect=dialect,
            selected_metrics=names,
            group_by=dimensions,
        )
        for dialect in sorted(DIALECTS)
    }
    return MetricRun(values, sql, tests, lineage, mermaid, catalog, dimensions)
