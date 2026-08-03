# PipeProof Data Contracts

PipeProof contracts describe what an incoming batch must look like before its accepted rows can be published. Contracts are generated from a baseline and stored as YAML beside every run.

## Inference Rules

PipeProof infers:

| Signal | Contract behavior |
|---|---|
| Integer, numeric, boolean, datetime, or string type | Values are coerced and non-conforming rows are quarantined |
| No baseline nulls | Column becomes non-nullable |
| Unique ID-like field | Duplicate values are quarantined |
| Numeric measure | Baseline minimum and maximum become initial bounds |
| Low-cardinality string | Baseline categories become accepted values |
| Email-like column name | Email pattern check is added |
| PII-like column name | A non-blocking classification hint is recorded |

Identifiers and datetimes do not receive baseline maximum constraints. New IDs and future timestamps are expected in normal incremental feeds.

## Example

```yaml
name: "customer_orders"
version: "1.0.0"
created_at: "2026-08-02T18:00:00+00:00"
baseline_rows: 25000
drift_policy:
  max_row_count_change: 0.35
  max_null_rate_change: 0.1
  numeric_drift_threshold: 0.75
  categorical_drift_threshold: 0.25
columns:
  - name: "order_id"
    dtype: "integer"
    nullable: false
    unique: true
  - name: "order_total"
    dtype: "number"
    nullable: false
    unique: false
    minimum: 0.0
    maximum: 18250.0
  - name: "channel"
    dtype: "string"
    nullable: false
    unique: false
    allowed_values: ["partner", "product", "sales"]
```

## Drift Scores

- **Row count:** absolute percentage change from baseline volume.
- **Null rate:** absolute change in each column's null percentage.
- **Numeric distribution:** absolute mean change measured in baseline standard deviations.
- **Categorical distribution:** total variation distance across the most frequent values.
- **Schema:** added, removed, or logically changed columns.

Drift is reported separately from row-level validity. A batch can contain individually valid rows while still representing an operationally suspicious population change.

## Contract Lifecycle

The initial release generates version `1.0.0` for every new baseline. The contract file is intentionally reviewable in Git. Teams should treat a relaxed constraint as a code change: inspect the evidence, confirm the source behavior is legitimate, update the contract, and rerun the batch before publication.
