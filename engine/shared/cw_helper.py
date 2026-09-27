"""
shared/cw_helper.py — Batched CloudWatch metric queries.

Uses get_metric_data (up to 500 metrics per call) instead of
get_metric_statistics (1 metric per call), cutting API call count drastically.

InternalFailure handling strategy:
  Large single batches can still trigger CloudWatch InternalFailure even when
  under the 500-metric limit. The helper therefore splits work into sub-batches
  of _SUB_BATCH_SIZE (default 50) and retries each sub-batch independently with
  exponential backoff + jitter. This isolates failures to a small slice of
  resources and usually succeeds within 1-2 retries.
"""
from __future__ import annotations

import random
import time
from datetime import datetime

_SUB_BATCH_SIZE = 50    # metrics per get_metric_data call (well under 500 limit)
_MAX_RETRIES    = 5     # per sub-batch: total attempts before giving up


def batch_metric_averages(
    cw_client,
    namespace: str,
    metric_name: str,
    dimension_name: str,
    dimension_values: list[str],
    start: datetime,
    end: datetime,
    period: int = 86400,
    stat: str = "Average",
    aggregate: str = "avg",
) -> dict[str, float]:
    """
    Batch-query CloudWatch for the average of one metric across many resources.

    Returns {dimension_value: avg} only for resources that have data.
    Resources with no CloudWatch data are absent from the result (caller skips them).

    Resilience: each sub-batch of 50 metrics is retried independently with
    exponential backoff + jitter on InternalFailure / throttling. A failed
    sub-batch is skipped with a warning so the rest of the audit continues.

    Args:
        cw_client:        boto3 CloudWatch client
        namespace:        e.g. "AWS/EC2", "AWS/RDS"
        metric_name:      e.g. "CPUUtilization", "DatabaseConnections"
        dimension_name:   e.g. "InstanceId", "DBInstanceIdentifier"
        dimension_values: list of resource IDs to query
        start / end:      datetime objects (timezone-aware UTC)
        period:           data-point granularity in seconds (default 86400 = daily)
        stat:             "Average", "Sum", "Maximum", etc.
        aggregate:        "avg" (mean of datapoints) or "sum" (total across period)
    """
    if not dimension_values:
        return {}

    results: dict[str, float] = {}

    for batch_start in range(0, len(dimension_values), _SUB_BATCH_SIZE):
        batch   = dimension_values[batch_start : batch_start + _SUB_BATCH_SIZE]
        id_map  = {f"m{i}": v for i, v in enumerate(batch)}
        queries = [
            {
                "Id": mid,
                "MetricStat": {
                    "Metric": {
                        "Namespace":  namespace,
                        "MetricName": metric_name,
                        "Dimensions": [{"Name": dimension_name, "Value": dim_val}],
                    },
                    "Period": period,
                    "Stat":   stat,
                },
                "ReturnData": True,
            }
            for mid, dim_val in id_map.items()
        ]

        batch_results = _fetch_with_retry(
            cw_client, queries, start, end,
            label=f"{namespace}/{metric_name} ({len(batch)} resources)",
        )
        for mid, vals in batch_results.items():
            if aggregate == "sum":
                results[id_map[mid]] = sum(vals)
            else:
                results[id_map[mid]] = sum(vals) / len(vals)

    return results


def _fetch_with_retry(
    cw_client,
    queries: list[dict],
    start: datetime,
    end: datetime,
    label: str,
) -> dict[str, list[float]]:
    """
    Fetch one sub-batch from get_metric_data with retry + jitter.

    Returns {metric_id: [values]} — empty dict if all retries fail.
    """
    value_lists: dict[str, list[float]] = {}

    for attempt in range(_MAX_RETRIES):
        next_token: str | None = None
        page_results: dict[str, list[float]] = {}
        failed = False

        while True:
            kwargs: dict = {
                "MetricDataQueries": queries,
                "StartTime": start,
                "EndTime":   end,
            }
            if next_token:
                kwargs["NextToken"] = next_token

            try:
                resp = cw_client.get_metric_data(**kwargs)
            except Exception as exc:
                err = str(exc)
                retryable = any(k in err for k in (
                    "InternalFailure", "InternalError", "ServiceUnavailable",
                    "Throttling", "ThrottlingException", "RequestLimitExceeded",
                ))
                if retryable and attempt < _MAX_RETRIES - 1:
                    wait = (2 ** attempt) + random.uniform(0, 1)
                    print(
                        f"[cw_helper] {label} — attempt {attempt+1}/{_MAX_RETRIES} "
                        f"failed ({type(exc).__name__}), retrying in {wait:.1f}s..."
                    )
                    time.sleep(wait)
                    failed = True
                    break
                else:
                    print(
                        f"[cw_helper] {label} — giving up after {attempt+1} attempts: "
                        f"{exc}  Skipping these resources; audit continues."
                    )
                    return {}   # permanent failure — return empty, caller skips

            for item in resp.get("MetricDataResults", []):
                vals = item.get("Values", [])
                if vals:
                    page_results.setdefault(item["Id"], []).extend(vals)

            next_token = resp.get("NextToken")
            if not next_token:
                break

        if not failed:
            value_lists = page_results
            break

    return value_lists
