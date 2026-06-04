# Evidence Trace — app-02

**Cycle.** `cycle_20260604_143726_ddaeaf53`
**Recommendation row.** `65`
**Refs cited.** 11 (11 resolved, 0 dangling)

---

## Recommendation summary

| Field | Value |
|---|---|
| finding_type | `issue_found` |
| primary_tier | `compute` |
| secondary_tier | `None` |
| action_category | `scaling_policy_change` |
| headline | Replace fixed 6× m5.large fleet with predictive auto-scaling (baseline 4, peak 9) to eliminate 80 SLA breaches at recurring weekday 10:00/15:00 peaks while saving ~$1,476/month. |

---

## Specialist findings chain

Top-level `recommendation.evidence_refs` cites these specialist findings, each of which cites its own observations (one hop deeper).

### Specialist finding row 62 — compute_analyst

- **finding_type:** `issue_found`
- **primary_tier:** `compute`
- **confidence:** 0.97
- **headline:** Fixed 6× m5.large fleet with no auto-scaling saturates CPU (90-96%) at recurring weekday 10:00 and 15:00 peaks, causing 80 SLA latency breaches (up to 572ms vs 300ms target).
- **evidence_refs cited by this specialist:**

  - ✓ `ref=43` type=`observation` tool=`get_summary_statistics`
  - ✓ `ref=45` type=`observation` tool=`get_summary_statistics`
  - ✓ `ref=47` type=`observation` tool=`get_summary_statistics`
  - ✓ `ref=49` type=`observation` tool=`get_configuration`
  - ✓ `ref=51` type=`observation` tool=`get_sla_target`
  - ✓ `ref=53` type=`observation` tool=`get_monthly_cost`
  - ✓ `ref=55` type=`observation` tool=`get_metric_distribution`
  - ✓ `ref=57` type=`observation` tool=`get_time_pattern`
  - ✓ `ref=59` type=`observation` tool=`detect_threshold_breaches`
  - ✓ `ref=61` type=`observation` tool=`detect_threshold_breaches`

---

## Evidence chain (every cited ref, resolved)

Each entry below is one audit_records row the recommendation cites somewhere. For observation rows, the parent tool_call's args are inlined so the chain reads `tool_call(args) → observation(body) → cited by N sources`.

### ref=43 — `observation` (agent=`compute_analyst`, tool=`get_summary_statistics`)

**Cited by (2 sources):**

- reconciliation.specialist_findings_summary[0].evidence_refs
- reconciliation.drift_check[0].supporting_evidence_refs

**Tool call** (row 42):

```json
{
  "app_name": "app-02",
  "tier": "compute",
  "metric": "cpu_p95"
}
```

**Observation body:**

```json
{
  "tool_name": "get_summary_statistics",
  "result": {
    "app_name": "app-02",
    "tier": "compute",
    "metric": "cpu_p95",
    "statistics": {
      "mean": 38.434375,
      "p50": 33.9,
      "p90": 41.27,
      "p95": 91.13999999999997
    }
  }
}
```

### ref=45 — `observation` (agent=`compute_analyst`, tool=`get_summary_statistics`)

**Cited by (2 sources):**

- reconciliation.specialist_findings_summary[0].evidence_refs
- reconciliation.drift_check[0].supporting_evidence_refs

**Tool call** (row 44):

```json
{
  "app_name": "app-02",
  "tier": "compute",
  "metric": "memory_p95"
}
```

**Observation body:**

```json
{
  "tool_name": "get_summary_statistics",
  "result": {
    "app_name": "app-02",
    "tier": "compute",
    "metric": "memory_p95",
    "statistics": {
      "mean": 50.975,
      "p50": 49.0,
      "p90": 55.60000000000001,
      "p95": 63.8
    }
  }
}
```

### ref=47 — `observation` (agent=`compute_analyst`, tool=`get_summary_statistics`)

**Cited by (2 sources):**

- reconciliation.specialist_findings_summary[0].evidence_refs
- reconciliation.drift_check[0].supporting_evidence_refs

**Tool call** (row 46):

```json
{
  "app_name": "app-02",
  "tier": "compute",
  "metric": "application_p95_latency_ms"
}
```

**Observation body:**

```json
{
  "tool_name": "get_summary_statistics",
  "result": {
    "app_name": "app-02",
    "tier": "compute",
    "metric": "application_p95_latency_ms",
    "statistics": {
      "mean": 222.30290178571428,
      "p50": 194.8,
      "p90": 245.37,
      "p95": 487.46999999999997
    }
  }
}
```

### ref=49 — `observation` (agent=`compute_analyst`, tool=`get_configuration`)

**Cited by (2 sources):**

- reconciliation.specialist_findings_summary[0].evidence_refs
- reconciliation.drift_check[0].supporting_evidence_refs

**Tool call** (row 48):

```json
{
  "app_name": "app-02",
  "tier": "compute"
}
```

**Observation body:**

```json
{
  "tool_name": "get_configuration",
  "result": {
    "app_name": "app-02",
    "tier": "compute",
    "configuration": {
      "present": true,
      "instance_class": "m5.large",
      "instance_count": 6,
      "scaling_policy": "none",
      "auto_scaling_min": null,
      "auto_scaling_max": null
    }
  }
}
```

### ref=51 — `observation` (agent=`compute_analyst`, tool=`get_sla_target`)

**Cited by (2 sources):**

- reconciliation.specialist_findings_summary[0].evidence_refs
- reconciliation.drift_check[0].supporting_evidence_refs

**Tool call** (row 50):

```json
{
  "app_name": "app-02"
}
```

**Observation body:**

```json
{
  "tool_name": "get_sla_target",
  "result": {
    "app_name": "app-02",
    "sla_target": {
      "description": "99.9% availability, P95 < 300ms",
      "p95_ms": 300.0,
      "availability_pct": 99.9
    }
  }
}
```

### ref=53 — `observation` (agent=`compute_analyst`, tool=`get_monthly_cost`)

**Cited by (3 sources):**

- reconciliation.specialist_findings_summary[0].evidence_refs
- reconciliation.drift_check[0].supporting_evidence_refs
- reconciliation.topology_assessment (prose @ char 74)

**Tool call** (row 52):

```json
{
  "app_name": "app-02"
}
```

**Observation body:**

```json
{
  "tool_name": "get_monthly_cost",
  "result": {
    "app_name": "app-02",
    "cost_baseline": {
      "monthly_cost_total_usd": 5200.0,
      "by_tier": {
        "compute": 5200.0,
        "database": 0.0,
        "cache": 0.0,
        "network": 0.0
      }
    }
  }
}
```

### ref=55 — `observation` (agent=`compute_analyst`, tool=`get_metric_distribution`)

**Cited by (2 sources):**

- reconciliation.specialist_findings_summary[0].evidence_refs
- reconciliation.drift_check[0].supporting_evidence_refs

**Tool call** (row 54):

```json
{
  "app_name": "app-02",
  "tier": "compute",
  "metric": "cpu_p95"
}
```

**Observation body:**

```json
{
  "tool_name": "get_metric_distribution",
  "result": {
    "app_name": "app-02",
    "tier": "compute",
    "metric": "cpu_p95",
    "distribution": {
      "min": 30.0,
      "max": 95.9,
      "n_bins": 10,
      "bins": [
        {
          "lo": 30.0,
          "hi": 36.59,
          "count": 846
        },
        {
          "lo": 36.59,
          "hi": 43.18,
          "count": 418
        },
        {
          "lo": 43.18,
          "hi": 49.77,
          "count": 0
        },
        {
          "lo": 49.77,
          "hi": 56.36,
          "count": 0
        },
        {
          "lo": 56.36,
          "hi": 62.95,
          "count": 0
        },
        {
          "lo": 62.95,
          "hi": 69.54,
          "count": 0
        },
        {
          "lo": 69.54,
          "hi": 76.13,
          "count": 0
        },
        {
          "lo": 76.13,
          "hi": 82.72,
          "count": 0
        },
        {
          "lo": 82.72,
          "hi": 89.31,
          "count": 2
        },
        {
          "lo": 89.31,
          "hi": 95.9,
          "count": 78
        }
      ]
    }
  }
}
```

### ref=57 — `observation` (agent=`compute_analyst`, tool=`get_time_pattern`)

**Cited by (2 sources):**

- reconciliation.specialist_findings_summary[0].evidence_refs
- reconciliation.drift_check[0].supporting_evidence_refs

**Tool call** (row 56):

```json
{
  "app_name": "app-02",
  "tier": "compute",
  "metric": "cpu_p95"
}
```

**Observation body:**

```json
{
  "tool_name": "get_time_pattern",
  "result": {
    "app_name": "app-02",
    "tier": "compute",
    "metric": "cpu_p95",
    "time_pattern": {
      "by_hour_of_day": {
        "0": 31.803571428571427,
        "1": 31.65535714285714,
        "2": 31.544642857142858,
        "3": 31.583928571428572,
        "4": 31.742857142857144,
        "5": 32.17321428571429,
        "6": 33.489285714285714,
        "7": 35.46785714285714,
        "8": 37.54642857142857,
        "9": 38.89821428571429,
        "10": 76.49464285714285,
        "11": 39.325,
        "12": 39.06428571428572,
        "13": 39.114285714285714,
        "14": 39.34464285714286,
        "15": 76.40357142857142,
        "16": 39.135714285714286,
        "17": 38.25,
        "18": 36.56071428571428,
        "19": 34.48571428571429,
        "20": 32.910714285714285,
        "21": 32.18035714285714,
        "22": 31.75357142857143,
        "23": 31.49642857142857
      },
      "by_weekday": {
        "0": 40.172916666666666,
        "1": 40.225520833333334,
        "2": 40.93385416666667,
        "3": 40.228125,
        "4": 40.27916666666667,
        "5": 34.1953125,
        "6": 33.00572916666667
      },
      "n_records": 1344
    }
  }
}
```

### ref=59 — `observation` (agent=`compute_analyst`, tool=`detect_threshold_breaches`)

**Cited by (2 sources):**

- reconciliation.specialist_findings_summary[0].evidence_refs
- reconciliation.drift_check[0].supporting_evidence_refs

**Tool call** (row 58):

```json
{
  "app_name": "app-02",
  "tier": "compute",
  "metric": "application_p95_latency_ms",
  "threshold": 300,
  "comparator": "gt"
}
```

**Observation body:**

```json
{
  "tool_name": "detect_threshold_breaches",
  "result": {
    "app_name": "app-02",
    "tier": "compute",
    "metric": "application_p95_latency_ms",
    "threshold": 300.0,
    "comparator": "gt",
    "breach_count": 80,
    "breaches": [
      {
        "timestamp": "2026-05-01T10:00:00Z",
        "value": 498.7
      },
      {
        "timestamp": "2026-05-01T10:15:00Z",
        "value": 541.3
      },
      {
        "timestamp": "2026-05-01T10:30:00Z",
        "value": 563.8
      },
      {
        "timestamp": "2026-05-01T10:45:00Z",
        "value": 548.2
      },
      {
        "timestamp": "2026-05-01T15:00:00Z",
        "value": 487.5
      },
      {
        "timestamp": "2026-05-01T15:15:00Z",
        "value": 532.1
      },
      {
        "timestamp": "2026-05-01T15:30:00Z",
        "value": 571.4
      },
      {
        "timestamp": "2026-05-01T15:45:00Z",
        "value": 549.8
      },
      {
        "timestamp": "2026-05-04T10:00:00Z",
        "value": 487.3
      },
      {
        "timestamp": "2026-05-04T10:15:00Z",
        "value": 521.6
      },
      {
        "timestamp": "2026-05-04T10:30:00Z",
        "value": 548.2
      },
      {
        "timestamp": "2026-05-04T10:45:00Z",
        "value": 503.7
      },
      {
        "timestamp": "2026-05-04T15:00:00Z",
        "value": 472.8
      },
      {
        "timestamp": "2026-05-04T15:15:00Z",
        "value": 508.4
      },
      {
        "timestamp": "2026-05-04T15:30:00Z",
        "value": 556.9
      },
      {
        "timestamp": "2026-05-04T15:45:00Z",
        "value": 531.2
      },
      {
        "timestamp": "2026-05-05T10:00:00Z",
        "value": 498.6
      },
      {
        "timestamp": "2026-05-05T10:15:00Z",
        "value": 541.3
      },
      {
        "timestamp": "2026-05-05T10:30:00Z",
        "value": 563.7
      },
      {
        "timestamp": "2026-05-05T10:45:00Z",
        "value": 521.4
      },
      {
        "timestamp": "2026-05-05T15:00:00Z",
        "value": 472.5
      },
      {
        "timestamp": "2026-05-05T15:15:00Z",
        "value": 528.9
      },
      {
        "timestamp": "2026-05-05T15:30:00Z",
        "value": 571.2
      },
      {
        "timestamp": "2026-05-05T15:45:00Z",
        "value": 507.6
      },
      {
        "timestamp": "2026-05-06T10:00:00Z",
        "value": 487.2
      },
      {
        "timestamp": "2026-05-06T10:15:00Z",
        "value": 512.6
      },
      {
        "timestamp": "2026-05-06T10:30:00Z",
        "value": 531.4
      },
      {
        "timestamp": "2026-05-06T10:45:00Z",
        "value": 503.8
      },
      {
        "timestamp": "2026-05-06T15:00:00Z",
        "value": 478.3
      },
      {
        "timestamp": "2026-05-06T15:15:00Z",
        "value": 498.7
      },
      {
        "timestamp": "2026-05-06T15:30:00Z",
        "value": 524.1
      },
      {
        "timestamp": "2026-05-06T15:45:00Z",
        "value": 509.5
      },
      {
        "timestamp": "2026-05-07T10:00:00Z",
        "value": 487.6
      },
      {
        "timestamp": "2026-05-07T10:15:00Z",
        "value": 531.2
      },
      {
        "timestamp": "2026-05-07T10:30:00Z",
        "value": 558.4
      },
      {
        "timestamp": "2026-05-07T10:45:00Z",
        "value": 544.7
      },
      {
        "timestamp": "2026-05-07T15:00:00Z",
        "value": 462.5
      },
      {
        "timestamp": "2026-05-07T15:15:00Z",
        "value": 508.3
      },
      {
        "timestamp": "2026-05-07T15:30:00Z",
        "value": 551.9
      },
      {
        "timestamp": "2026-05-07T15:45:00Z",
        "value": 527.6
      },
      {
        "timestamp": "2026-05-08T10:00:00Z",
        "value": 498.7
      },
      {
        "timestamp": "2026-05-08T10:15:00Z",
        "value": 521.3
      },
      {
        "timestamp": "2026-05-08T10:30:00Z",
        "value": 511.6
      },
      {
        "timestamp": "2026-05-08T10:45:00Z",
        "value": 534.8
      },
      {
        "timestamp": "2026-05-08T15:00:00Z",
        "value": 487.3
      },
      {
        "timestamp": "2026-05-08T15:15:00Z",
        "value": 514.9
      },
      {
        "timestamp": "2026-05-08T15:30:00Z",
        "value": 538.2
      },
      {
        "timestamp": "2026-05-08T15:45:00Z",
        "value": 506.7
      },
      {
        "timestamp": "2026-05-11T10:00:00Z",
        "value": 487.2
      },
      {
        "timestamp": "2026-05-11T10:15:00Z",
        "value": 512.8
      },
      {
        "timestamp": "2026-05-11T10:30:00Z",
        "value": 541.3
      },
      {
        "timestamp": "2026-05-11T10:45:00Z",
        "value": 523.7
      },
      {
        "timestamp": "2026-05-11T15:00:00Z",
        "value": 478.6
      },
      {
        "timestamp": "2026-05-11T15:15:00Z",
        "value": 503.4
      },
      {
        "timestamp": "2026-05-11T15:30:00Z",
        "value": 531.9
      },
      {
        "timestamp": "2026-05-11T15:45:00Z",
        "value": 516.2
      },
      {
        "timestamp": "2026-05-12T10:00:00Z",
        "value": 498.7
      },
      {
        "timestamp": "2026-05-12T10:15:00Z",
        "value": 541.3
      },
      {
        "timestamp": "2026-05-12T10:30:00Z",
        "value": 563.8
      },
      {
        "timestamp": "2026-05-12T10:45:00Z",
        "value": 519.4
      },
      {
        "timestamp": "2026-05-12T15:00:00Z",
        "value": 487.2
      },
      {
        "timestamp": "2026-05-12T15:15:00Z",
        "value": 548.6
      },
      {
        "timestamp": "2026-05-12T15:30:00Z",
        "value": 571.9
      },
      {
        "timestamp": "2026-05-12T15:45:00Z",
        "value": 512.8
      },
      {
        "timestamp": "2026-05-13T10:00:00Z",
        "value": 438.2
      },
      {
        "timestamp": "2026-05-13T10:15:00Z",
        "value": 487.6
      },
      {
        "timestamp": "2026-05-13T10:30:00Z",
        "value": 531.4
      },
      {
        "timestamp": "2026-05-13T10:45:00Z",
        "value": 558.9
      },
      {
        "timestamp": "2026-05-13T15:00:00Z",
        "value": 445.7
      },
      {
        "timestamp": "2026-05-13T15:15:00Z",
        "value": 498.3
      },
      {
        "timestamp": "2026-05-13T15:30:00Z",
        "value": 543.6
      },
      {
        "timestamp": "2026-05-13T15:45:00Z",
        "value": 571.2
      },
      {
        "timestamp": "2026-05-14T10:00:00Z",
        "value": 498.3
      },
      {
        "timestamp": "2026-05-14T10:15:00Z",
        "value": 541.2
      },
      {
        "timestamp": "2026-05-14T10:30:00Z",
        "value": 563.7
      },
      {
        "timestamp": "2026-05-14T10:45:00Z",
        "value": 572.4
      },
      {
        "timestamp": "2026-05-14T15:00:00Z",
        "value": 487.6
      },
      {
        "timestamp": "2026-05-14T15:15:00Z",
        "value": 528.4
      },
      {
        "timestamp": "2026-05-14T15:30:00Z",
        "value": 557.9
      },
      {
        "timestamp": "2026-05-14T15:45:00Z",
        "value": 569.2
      }
    ]
  }
}
```

### ref=61 — `observation` (agent=`compute_analyst`, tool=`detect_threshold_breaches`)

**Cited by (2 sources):**

- reconciliation.specialist_findings_summary[0].evidence_refs
- reconciliation.drift_check[0].supporting_evidence_refs

**Tool call** (row 60):

```json
{
  "app_name": "app-02",
  "tier": "compute",
  "metric": "cpu_p95",
  "threshold": 80,
  "comparator": "gt"
}
```

**Observation body:**

```json
{
  "tool_name": "detect_threshold_breaches",
  "result": {
    "app_name": "app-02",
    "tier": "compute",
    "metric": "cpu_p95",
    "threshold": 80.0,
    "comparator": "gt",
    "breach_count": 80,
    "breaches": [
      {
        "timestamp": "2026-05-01T10:00:00Z",
        "value": 91.2
      },
      {
        "timestamp": "2026-05-01T10:15:00Z",
        "value": 93.5
      },
      {
        "timestamp": "2026-05-01T10:30:00Z",
        "value": 94.8
      },
      {
        "timestamp": "2026-05-01T10:45:00Z",
        "value": 92.6
      },
      {
        "timestamp": "2026-05-01T15:00:00Z",
        "value": 90.4
      },
      {
        "timestamp": "2026-05-01T15:15:00Z",
        "value": 92.8
      },
      {
        "timestamp": "2026-05-01T15:30:00Z",
        "value": 95.3
      },
      {
        "timestamp": "2026-05-01T15:45:00Z",
        "value": 93.1
      },
      {
        "timestamp": "2026-05-04T10:00:00Z",
        "value": 91.2
      },
      {
        "timestamp": "2026-05-04T10:15:00Z",
        "value": 93.5
      },
      {
        "timestamp": "2026-05-04T10:30:00Z",
        "value": 94.8
      },
      {
        "timestamp": "2026-05-04T10:45:00Z",
        "value": 92.1
      },
      {
        "timestamp": "2026-05-04T15:00:00Z",
        "value": 90.4
      },
      {
        "timestamp": "2026-05-04T15:15:00Z",
        "value": 92.7
      },
      {
        "timestamp": "2026-05-04T15:30:00Z",
        "value": 95.3
      },
      {
        "timestamp": "2026-05-04T15:45:00Z",
        "value": 93.1
      },
      {
        "timestamp": "2026-05-05T10:00:00Z",
        "value": 91.2
      },
      {
        "timestamp": "2026-05-05T10:15:00Z",
        "value": 93.5
      },
      {
        "timestamp": "2026-05-05T10:30:00Z",
        "value": 94.8
      },
      {
        "timestamp": "2026-05-05T10:45:00Z",
        "value": 92.1
      },
      {
        "timestamp": "2026-05-05T15:00:00Z",
        "value": 89.4
      },
      {
        "timestamp": "2026-05-05T15:15:00Z",
        "value": 92.7
      },
      {
        "timestamp": "2026-05-05T15:30:00Z",
        "value": 95.3
      },
      {
        "timestamp": "2026-05-05T15:45:00Z",
        "value": 90.8
      },
      {
        "timestamp": "2026-05-06T10:00:00Z",
        "value": 91.2
      },
      {
        "timestamp": "2026-05-06T10:15:00Z",
        "value": 93.7
      },
      {
        "timestamp": "2026-05-06T10:30:00Z",
        "value": 94.8
      },
      {
        "timestamp": "2026-05-06T10:45:00Z",
        "value": 92.5
      },
      {
        "timestamp": "2026-05-06T15:00:00Z",
        "value": 90.4
      },
      {
        "timestamp": "2026-05-06T15:15:00Z",
        "value": 92.9
      },
      {
        "timestamp": "2026-05-06T15:30:00Z",
        "value": 95.3
      },
      {
        "timestamp": "2026-05-06T15:45:00Z",
        "value": 93.6
      },
      {
        "timestamp": "2026-05-07T10:00:00Z",
        "value": 91.2
      },
      {
        "timestamp": "2026-05-07T10:15:00Z",
        "value": 93.7
      },
      {
        "timestamp": "2026-05-07T10:30:00Z",
        "value": 95.1
      },
      {
        "timestamp": "2026-05-07T10:45:00Z",
        "value": 94.3
      },
      {
        "timestamp": "2026-05-07T15:00:00Z",
        "value": 89.6
      },
      {
        "timestamp": "2026-05-07T15:15:00Z",
        "value": 92.4
      },
      {
        "timestamp": "2026-05-07T15:30:00Z",
        "value": 94.8
      },
      {
        "timestamp": "2026-05-07T15:45:00Z",
        "value": 93.2
      },
      {
        "timestamp": "2026-05-08T10:00:00Z",
        "value": 91.2
      },
      {
        "timestamp": "2026-05-08T10:15:00Z",
        "value": 93.8
      },
      {
        "timestamp": "2026-05-08T10:30:00Z",
        "value": 92.5
      },
      {
        "timestamp": "2026-05-08T10:45:00Z",
        "value": 94.1
      },
      {
        "timestamp": "2026-05-08T15:00:00Z",
        "value": 90.4
      },
      {
        "timestamp": "2026-05-08T15:15:00Z",
        "value": 92.7
      },
      {
        "timestamp": "2026-05-08T15:30:00Z",
        "value": 94.3
      },
      {
        "timestamp": "2026-05-08T15:45:00Z",
        "value": 91.8
      },
      {
        "timestamp": "2026-05-11T10:00:00Z",
        "value": 91.4
      },
      {
        "timestamp": "2026-05-11T10:15:00Z",
        "value": 93.2
      },
      {
        "timestamp": "2026-05-11T10:30:00Z",
        "value": 94.8
      },
      {
        "timestamp": "2026-05-11T10:45:00Z",
        "value": 92.6
      },
      {
        "timestamp": "2026-05-11T15:00:00Z",
        "value": 90.8
      },
      {
        "timestamp": "2026-05-11T15:15:00Z",
        "value": 92.4
      },
      {
        "timestamp": "2026-05-11T15:30:00Z",
        "value": 94.1
      },
      {
        "timestamp": "2026-05-11T15:45:00Z",
        "value": 91.9
      },
      {
        "timestamp": "2026-05-12T10:00:00Z",
        "value": 91.2
      },
      {
        "timestamp": "2026-05-12T10:15:00Z",
        "value": 93.5
      },
      {
        "timestamp": "2026-05-12T10:30:00Z",
        "value": 94.8
      },
      {
        "timestamp": "2026-05-12T10:45:00Z",
        "value": 92.1
      },
      {
        "timestamp": "2026-05-12T15:00:00Z",
        "value": 90.4
      },
      {
        "timestamp": "2026-05-12T15:15:00Z",
        "value": 93.1
      },
      {
        "timestamp": "2026-05-12T15:30:00Z",
        "value": 95.3
      },
      {
        "timestamp": "2026-05-12T15:45:00Z",
        "value": 91.7
      },
      {
        "timestamp": "2026-05-13T10:00:00Z",
        "value": 88.4
      },
      {
        "timestamp": "2026-05-13T10:15:00Z",
        "value": 91.2
      },
      {
        "timestamp": "2026-05-13T10:30:00Z",
        "value": 93.7
      },
      {
        "timestamp": "2026-05-13T10:45:00Z",
        "value": 95.1
      },
      {
        "timestamp": "2026-05-13T15:00:00Z",
        "value": 89.1
      },
      {
        "timestamp": "2026-05-13T15:15:00Z",
        "value": 92.4
      },
      {
        "timestamp": "2026-05-13T15:30:00Z",
        "value": 94.8
      },
      {
        "timestamp": "2026-05-13T15:45:00Z",
        "value": 95.9
      },
      {
        "timestamp": "2026-05-14T10:00:00Z",
        "value": 91.2
      },
      {
        "timestamp": "2026-05-14T10:15:00Z",
        "value": 93.5
      },
      {
        "timestamp": "2026-05-14T10:30:00Z",
        "value": 94.8
      },
      {
        "timestamp": "2026-05-14T10:45:00Z",
        "value": 95.6
      },
      {
        "timestamp": "2026-05-14T15:00:00Z",
        "value": 89.4
      },
      {
        "timestamp": "2026-05-14T15:15:00Z",
        "value": 92.7
      },
      {
        "timestamp": "2026-05-14T15:30:00Z",
        "value": 94.3
      },
      {
        "timestamp": "2026-05-14T15:45:00Z",
        "value": 95.1
      }
    ]
  }
}
```

### ref=62 — `specialist_finding` (agent=`compute_analyst`, tool=`-`)

**Cited by (1 source):**

- recommendation.evidence_refs

**Observation body:**

```json
{
  "specialist": "compute_analyst",
  "finding_type": "issue_found",
  "headline": "Fixed 6\u00d7 m5.large fleet with no auto-scaling saturates CPU (90-96%) at recurring weekday 10:00 and 15:00 peaks, causing 80 SLA latency breaches (up to 572ms vs 300ms target).",
  "primary_tier": "compute",
  "confidence": 0.97,
  "reasoning_summary": "The CPU p95 distribution is strongly bimodal: 1,264 records sit in the 30\u201343% band (healthy baseline), but 80 records spike to 88\u201396% with no values in between, indicating a binary load pattern rather than gradual degradation. Time-pattern analysis pinpoints these spikes to weekday hours 10:00 (avg 76.5%) and 15:00 (avg 76.4%), with all other hours at 31\u201339%. These CPU saturations directly drive 80 application_p95_latency_ms breaches above the 300ms SLA threshold, with values reaching 438\u2013572ms at the exact same timestamps. The fleet is configured as 6\u00d7 m5.large with scaling_policy=none and no ASG bounds, meaning it cannot elastically absorb these predictable recurring demand peaks. Adding time-based or metric-based auto-scaling (or increasing the base instance count) would address the SLA violations at the identified peak windows.",
  "evidence_refs": [
    43,
    45,
    47,
    49,
    51,
    53,
    55,
    57,
    59,
    61
  ]
}
```

