"""
Merge duplicate findings from AWS-native and custom audit modules.

Custom module findings (no metadata.source) take priority over ingested
AWS recommendations for the same resource. Savings estimates use the max.
"""
from __future__ import annotations

from shared.findings_schema import Finding

# Higher number = keep this finding when merging duplicates.
_SOURCE_PRIORITY: dict[str, int] = {
    "custom": 3,
    "compute_optimizer": 2,
    "cost_optimization_hub": 2,
    "trusted_advisor": 1,
}


def _source_key(finding: Finding) -> str:
    return str(finding.metadata.get("source", "custom"))


def _priority(finding: Finding) -> int:
    return _SOURCE_PRIORITY.get(_source_key(finding), 2)


def _canonical_group(finding: Finding) -> str:
    category = finding.category.value if hasattr(finding.category, "value") else str(finding.category)
    svc = (finding.service or "").lower()
    if any(k in svc for k in ("ebs", "volume", "snapshot", "elastic ip", "eip", "load balancer", "elb", "alb", "nlb", "ecr")):
        return "infra_hygiene"
    if any(k in svc for k in ("ec2", "instance", "lambda", "fargate", "ecs", "auto scaling")):
        return "compute_strategy"
    if any(k in svc for k in ("rds", "aurora", "database", "redshift", "elasticache", "dynamodb")):
        return "database_tuning"
    if any(k in svc for k in ("nat", "s3", "vpc", "transfer", "endpoint")):
        return "network_storage"
    if any(k in svc for k in ("savings plan", "reserved")):
        return "savings_plans"
    return category.lower()


def _dedup_key(finding: Finding) -> tuple[str, str]:
    res_id = (finding.resource_id or finding.id).lower().strip()
    if "/" in res_id and not res_id.startswith("http"):
        res_id = res_id.rsplit("/", 1)[-1]
    if ":" in res_id and not res_id.startswith("http"):
        res_id = res_id.rsplit(":", 1)[-1]

    # Standard AWS resource ID prefixes are globally or account-unique
    if any(res_id.startswith(p) for p in ("vol-", "i-", "snap-", "eipalloc-", "nat-", "igw-", "vpc-", "subnet-", "sg-")):
        return ("aws_resource", res_id)

    return (_canonical_group(finding), res_id)


def _merge(existing: Finding, incoming: Finding) -> Finding:
    keep, drop = (existing, incoming) if _priority(existing) >= _priority(incoming) else (incoming, existing)

    merged_savings = max(
        existing.estimated_monthly_savings_usd,
        incoming.estimated_monthly_savings_usd,
    )

    merged_meta = dict(drop.metadata)
    merged_meta.update(keep.metadata)
    merged_meta["also_reported_by"] = sorted({
        *merged_meta.get("also_reported_by", []),
        _source_key(existing),
        _source_key(incoming),
    })

    return keep.model_copy(update={
        "estimated_monthly_savings_usd": merged_savings,
        "metadata": merged_meta,
    })


def deduplicate_findings(findings: list[Finding]) -> list[Finding]:
    """Return deduplicated findings, preferring custom enrichments over AWS ingest."""
    merged: dict[tuple[str, str], Finding] = {}

    for finding in findings:
        key = _dedup_key(finding)
        if key not in merged:
            merged[key] = finding
        else:
            merged[key] = _merge(merged[key], finding)

    return list(merged.values())
