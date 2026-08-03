# MetricFoundry Catalogs

MetricFoundry is PipeProof's optional semantic-metrics layer. It runs against rows that passed the data contract, keeping metric definitions versioned beside the reliability evidence that produced their inputs.

## Catalog Shape

```yaml
name: commerce_core
version: "1.0"
source:
  table: accepted
  time_column: ordered_at
dimensions: [region, channel]
metrics:
  - name: orders
    type: count
  - name: revenue
    type: sum
    column: order_value
    tests:
      - test: non_negative
        severity: error
  - name: paid_orders
    type: count
    filters:
      - column: status
        operator: eq
        value: paid
  - name: paid_rate
    type: ratio
    numerator: paid_orders
    denominator: orders
    format: percent
```

## Metric Types

| Type | Required fields | Behavior |
|---|---|---|
| `count` | none | Counts accepted rows |
| `count_distinct` | `column` | Counts unique non-null values |
| `sum` | `column` | Sums numeric values |
| `average` | `column` | Calculates the numeric mean |
| `minimum` | `column` | Returns the smallest numeric value |
| `maximum` | `column` | Returns the largest numeric value |
| `ratio` | `numerator`, `denominator` | Divides two governed metrics with zero protection |

## Filters

Supported operators are `eq`, `ne`, `in`, `not_in`, `gt`, `gte`, `lt`, `lte`, `is_null`, and `not_null`. Values are escaped by the SQL compiler; catalog identifiers must match a conservative SQL-safe pattern.

## Tests

Metric tests run on computed output and retain their observed value:

- `not_null`
- `non_negative`
- `minimum`
- `maximum`

Tests may use `severity: warning` or `severity: error`. Error-level failures fail the PipeProof run; warning-level failures degrade it.

## SQL Compilation

The same catalog compiles to DuckDB, PostgreSQL, and BigQuery SQL. Compilation is deterministic and does not connect to an external warehouse. PipeProof also executes the equivalent metric logic locally against the accepted pandas dataframe, so the public demo has no warehouse dependency.

```bash
pipeproof metrics compile data/sample/nyc_311_metrics.yaml --dialect bigquery --group-by borough
```

## Lineage

Every run emits `metrics_lineage.json` and `metrics_lineage.mmd`. Edges connect source columns to governed metrics and connect numerator/denominator metrics to ratios. This is intentionally small and portable so downstream catalogs, documentation systems, or graph tools can consume it.
