from __future__ import annotations

import pandas as pd
import pytest

from pipeproof.metrics import (
    MetricCatalog,
    compile_metrics_sql,
    demo_metric_catalog,
    execute_metrics,
    metric_lineage,
)


def test_metric_catalog_executes_grouped_metrics_and_ratio() -> None:
    frame = pd.DataFrame(
        {
            "created_date": ["2026-01-01", "2026-01-02", "2026-01-03"],
            "agency": ["A", "A", "B"],
            "complaint_type": ["Noise", "Water", "Noise"],
            "borough": ["QUEENS", "QUEENS", "BRONX"],
            "status": ["Closed", "Open", "Closed"],
            "resolution_hours": [10.0, 30.0, 20.0],
            "channel": ["Web", "Phone", "Web"],
        }
    )
    run = execute_metrics(frame, demo_metric_catalog(), group_by=["borough"])
    queens = run.values.loc[run.values["borough"] == "QUEENS"].iloc[0]

    assert queens["service_requests"] == 2
    assert queens["closed_requests"] == 1
    assert queens["closure_rate"] == 0.5
    assert queens["slow_resolutions"] == 1
    assert not [item for item in run.tests if not item.passed]


def test_sql_compiler_emits_dialect_specific_safe_sql() -> None:
    catalog = demo_metric_catalog()
    postgres = compile_metrics_sql(catalog, dialect="postgres", group_by=["borough"])
    bigquery = compile_metrics_sql(catalog, dialect="bigquery", selected_metrics=["closure_rate"])

    assert 'GROUP BY "borough"' in postgres
    assert "DOUBLE PRECISION" in postgres
    assert "`closure_rate`" in bigquery
    assert "FLOAT64" in bigquery
    assert "NULLIF" in bigquery


def test_catalog_rejects_unsafe_identifiers_and_cycles() -> None:
    with pytest.raises(ValueError, match="safe SQL identifier"):
        MetricCatalog.from_dict(
            {
                "name": "unsafe",
                "source": {"table": "accepted; drop table users"},
                "metrics": [{"name": "rows", "type": "count"}],
            }
        )

    with pytest.raises(ValueError, match="cycle"):
        MetricCatalog.from_dict(
            {
                "name": "cycle",
                "source": {"table": "accepted"},
                "metrics": [
                    {"name": "a", "type": "ratio", "numerator": "b", "denominator": "b"},
                    {"name": "b", "type": "ratio", "numerator": "a", "denominator": "a"},
                ],
            }
        )


def test_lineage_connects_columns_and_metric_dependencies() -> None:
    graph, mermaid = metric_lineage(demo_metric_catalog())
    edges = {(item["from"], item["to"], item["type"]) for item in graph["edges"]}
    assert ("column:status", "metric:closed_requests", "derives") in edges
    assert ("metric:closed_requests", "metric:closure_rate", "numerator") in edges
    assert mermaid.startswith("flowchart LR")
