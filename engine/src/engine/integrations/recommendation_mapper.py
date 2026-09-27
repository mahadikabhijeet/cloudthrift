"""
Map AWS-native recommendations (Trusted Advisor, Compute Optimizer, COH) to Finding.
"""
from __future__ import annotations

import re
from typing import Any

from shared.findings_schema import Category, Finding, Severity

# Trusted Advisor checks safe for teaser mode (API-only, no CloudWatch/CE).
TEASER_TA_NAME_KEYWORDS = (
    "elastic ip",
    "load balancer",
    "ebs",
    "stopped",
    "nat gateway",
    "snapshot",
    "s3",
)

_CATEGORY_RULES: list[tuple[tuple[str, ...], Category]] = [
    (("savings plan", "reserved instance", "reserved node", "reserved capacity"), Category.SAVINGS_PLANS),
    (("rds", "aurora", "database", "redshift", "elasticache", "memorydb", "dynamodb"), Category.DATABASE_TUNING),
    (("s3", "nat", "transfer", "vpc endpoint", "network firewall", "route 53"), Category.NETWORK_STORAGE),
    (("ebs", "snapshot", "elastic ip", "load balancer", "ecr"), Category.INFRA_HYGIENE),
    (("ec2", "lambda", "fargate", "ecs", "auto scaling", "graviton"), Category.COMPUTE_STRATEGY),
]


def category_for_check_name(name: str) -> Category:
    lowered = name.lower()
    for keywords, category in _CATEGORY_RULES:
        if any(kw in lowered for kw in keywords):
            return category
    return Category.COMPUTE_STRATEGY


def category_for_service(service: str) -> Category:
    return category_for_check_name(service)


def severity_from_status(status: str) -> Severity:
    normalized = (status or "").lower()
    if normalized in ("error", "critical"):
        return Severity.HIGH
    if normalized in ("warning", "warn"):
        return Severity.MEDIUM
    return Severity.LOW


def _parse_float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        cleaned = re.sub(r"[^\d.\-]", "", str(value))
        return max(0.0, float(cleaned)) if cleaned else 0.0
    except (TypeError, ValueError):
        return 0.0


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-")[:48] or "resource"


def finding_from_trusted_advisor(
    check_id: str,
    check_name: str,
    resource: dict[str, Any],
    column_names: list[str],
) -> Finding | None:
    """Convert one TA flagged resource into a Finding."""
    meta_values = resource.get("metadata") or []
    meta_dict = {
        column_names[i]: meta_values[i]
        for i in range(min(len(column_names), len(meta_values)))
    }

    resource_id = (
        resource.get("resourceId")
        or meta_dict.get("Resource ID")
        or meta_dict.get("Volume ID")
        or meta_dict.get("Instance ID")
        or meta_dict.get("Load Balancer Name")
        or meta_dict.get("DB Instance Name")
        or meta_dict.get("Function Name")
        or meta_dict.get("Allocation ID")
        or "unknown"
    )
    if resource_id == "unknown":
        for value in meta_values:
            if value and value not in ("-", "N/A"):
                resource_id = value
                break

    region = (
        meta_dict.get("Region")
        or meta_dict.get("Region/AZ", "").split("/")[0]
        or meta_dict.get("Availability Zone", "").rstrip("abcdefghijklmnopqrstuvwxyz")
        or "global"
    )

    savings = _parse_float(
        meta_dict.get("Estimated Monthly Savings")
        or meta_dict.get("Estimated Savings")
        or meta_dict.get("Monthly Savings")
    )

    status = resource.get("status", "warning")
    category = category_for_check_name(check_name)
    service = check_name.split(" for ")[0].replace("Amazon ", "").replace("AWS ", "")[:40]

    return Finding(
        id=f"TA-{_slug(check_id)}-{_slug(str(resource_id))}",
        title=f"Trusted Advisor: {check_name}",
        description=(
            f"AWS Trusted Advisor flagged {resource_id} under check '{check_name}'. "
            f"Status: {status}."
        ),
        severity=severity_from_status(status),
        category=category,
        service=service or "AWS",
        region=region,
        resource_id=str(resource_id),
        estimated_monthly_savings_usd=savings,
        recommendation=f"Review Trusted Advisor check '{check_name}' and remediate {resource_id}.",
        metadata={
            "source": "trusted_advisor",
            "ta_check_id": check_id,
            "ta_check_name": check_name,
            "ta_status": status,
            "ta_columns": meta_dict,
            "is_suppressed": resource.get("isSuppressed", False),
        },
    )


def finding_from_compute_optimizer_ec2(rec: dict[str, Any]) -> Finding | None:
    instance_arn = rec.get("instanceArn", "")
    instance_id = instance_arn.rsplit("/", 1)[-1] if instance_arn else "unknown"
    current = rec.get("currentInstanceType", "unknown")
    finding_types = rec.get("finding", [])
    if not finding_types:
        return None

    primary = finding_types[0]
    options = rec.get("recommendationOptions") or []
    savings = 0.0
    recommended = current
    if options:
        savings = _parse_float(options[0].get("savingsOpportunity", {}).get("estimatedMonthlySavings", {}).get("value"))
        recommended = options[0].get("instanceType", recommended)

    region = rec.get("instanceArn", "").split(":")[3] if ":" in rec.get("instanceArn", "") else "unknown"

    return Finding(
        id=f"CO-EC2-{instance_id}",
        title=f"Compute Optimizer: rightsizing {instance_id} ({current} → {recommended})",
        description=(
            f"Compute Optimizer recommends {primary.lower()} for {instance_id} "
            f"(currently {current}). Estimated savings: ${savings:.2f}/month."
        ),
        severity=Severity.MEDIUM if savings >= 50 else Severity.LOW,
        category=Category.COMPUTE_STRATEGY,
        service="EC2",
        region=region,
        resource_id=instance_id,
        estimated_monthly_savings_usd=savings,
        recommendation=(
            f"Validate workload metrics for {instance_id}, then apply rightsizing "
            f"to {recommended} or terminate if underutilized."
        ),
        metadata={
            "source": "compute_optimizer",
            "finding": primary,
            "current_instance_type": current,
            "recommended_instance_type": recommended,
            "utilization_metrics": rec.get("utilizationMetrics", []),
        },
    )


def finding_from_compute_optimizer_ebs(rec: dict[str, Any]) -> Finding | None:
    volume_arn = rec.get("volumeArn", "")
    volume_id = volume_arn.rsplit("/", 1)[-1] if volume_arn else "unknown"
    finding_types = rec.get("finding", [])
    if not finding_types:
        return None

    options = rec.get("volumeRecommendationOptions") or []
    savings = 0.0
    recommended = rec.get("currentConfiguration", {}).get("volumeType", "gp3")
    if options:
        cfg = options[0].get("configuration", {})
        recommended = cfg.get("volumeType", recommended)
        savings = _parse_float(
            options[0].get("savingsOpportunity", {}).get("estimatedMonthlySavings", {}).get("value")
        )

    region = volume_arn.split(":")[3] if ":" in volume_arn else "unknown"

    return Finding(
        id=f"CO-EBS-{volume_id}",
        title=f"Compute Optimizer: EBS optimization for {volume_id}",
        description=(
            f"Compute Optimizer flagged volume {volume_id} ({finding_types[0]}). "
            f"Estimated savings: ${savings:.2f}/month."
        ),
        severity=Severity.LOW if savings < 25 else Severity.MEDIUM,
        category=Category.INFRA_HYGIENE,
        service="EC2/EBS",
        region=region,
        resource_id=volume_id,
        estimated_monthly_savings_usd=savings,
        recommendation=f"Review EBS configuration for {volume_id} and apply Compute Optimizer guidance.",
        metadata={
            "source": "compute_optimizer",
            "finding": finding_types[0],
            "recommended_volume_type": recommended,
        },
    )


def finding_from_compute_optimizer_lambda(rec: dict[str, Any]) -> Finding | None:
    fn_arn = rec.get("functionArn", "")
    fn_name = fn_arn.rsplit(":", 1)[-1] if fn_arn else "unknown"
    finding_types = rec.get("finding", [])
    if not finding_types:
        return None

    options = rec.get("memorySizeRecommendationOptions") or []
    savings = 0.0
    current_mem = rec.get("currentMemorySize", 0)
    recommended_mem = current_mem
    if options:
        recommended_mem = options[0].get("memorySize", current_mem)
        savings = _parse_float(
            options[0].get("savingsOpportunity", {}).get("estimatedMonthlySavings", {}).get("value")
        )

    region = fn_arn.split(":")[3] if ":" in fn_arn else "unknown"

    return Finding(
        id=f"CO-LAMBDA-{fn_name}",
        title=f"Compute Optimizer: Lambda memory for {fn_name}",
        description=(
            f"Compute Optimizer recommends adjusting memory for {fn_name} "
            f"({current_mem} MB → {recommended_mem} MB). "
            f"Estimated savings: ${savings:.2f}/month."
        ),
        severity=Severity.LOW if savings < 10 else Severity.MEDIUM,
        category=Category.COMPUTE_STRATEGY,
        service="Lambda",
        region=region,
        resource_id=fn_name,
        estimated_monthly_savings_usd=savings,
        recommendation=f"Test {fn_name} at {recommended_mem} MB memory and validate latency before applying.",
        metadata={
            "source": "compute_optimizer",
            "finding": finding_types[0],
            "current_memory_mb": current_mem,
            "recommended_memory_mb": recommended_mem,
        },
    )


def finding_from_compute_optimizer_rds(rec: dict[str, Any]) -> Finding | None:
    db_arn = rec.get("resourceArn", "")
    db_id = rec.get("instanceIdentifier") or (
        db_arn.rsplit(":", 1)[-1] if db_arn else "unknown"
    )
    finding_types = rec.get("finding", [])
    if not finding_types:
        return None

    options = rec.get("recommendationOptions") or []
    savings = 0.0
    current_type = rec.get("currentDBInstanceClass", "unknown")
    recommended_type = current_type
    if options:
        cfg = options[0].get("dbInstanceConfiguration", {})
        recommended_type = cfg.get("dbInstanceClass", recommended_type)
        savings = _parse_float(
            options[0].get("savingsOpportunity", {}).get("estimatedMonthlySavings", {}).get("value")
        )

    region = db_arn.split(":")[3] if ":" in db_arn else "unknown"

    return Finding(
        id=f"CO-RDS-{db_id}",
        title=f"Compute Optimizer: RDS rightsizing for {db_id}",
        description=(
            f"Compute Optimizer recommends {finding_types[0].lower()} for RDS instance "
            f"{db_id} ({current_type} → {recommended_type}). "
            f"Estimated savings: ${savings:.2f}/month."
        ),
        severity=Severity.MEDIUM if savings >= 50 else Severity.LOW,
        category=Category.DATABASE_TUNING,
        service="RDS",
        region=region,
        resource_id=str(db_id),
        estimated_monthly_savings_usd=savings,
        recommendation=(
            f"Review RDS metrics for {db_id} and apply rightsizing during a maintenance window."
        ),
        metadata={
            "source": "compute_optimizer",
            "finding": finding_types[0],
            "current_instance_class": current_type,
            "recommended_instance_class": recommended_type,
        },
    )


def finding_from_compute_optimizer_ecs(rec: dict[str, Any]) -> Finding | None:
    service_arn = rec.get("serviceArn", "")
    service_name = service_arn.rsplit("/", 1)[-1] if service_arn else "unknown"
    finding_types = rec.get("finding", [])
    if not finding_types:
        return None

    options = rec.get("serviceRecommendationOptions") or []
    savings = 0.0
    if options:
        savings = _parse_float(
            options[0].get("savingsOpportunity", {}).get("estimatedMonthlySavings", {}).get("value")
        )

    region = service_arn.split(":")[3] if ":" in service_arn else "unknown"
    cluster_arn = rec.get("clusterArn", "")
    cluster_name = cluster_arn.rsplit("/", 1)[-1] if cluster_arn else "unknown"

    return Finding(
        id=f"CO-ECS-{cluster_name}-{service_name}",
        title=f"Compute Optimizer: Fargate/ECS optimization for {service_name}",
        description=(
            f"Compute Optimizer flagged ECS service {service_name} in cluster {cluster_name} "
            f"({finding_types[0]}). Estimated savings: ${savings:.2f}/month."
        ),
        severity=Severity.MEDIUM if savings >= 50 else Severity.LOW,
        category=Category.COMPUTE_STRATEGY,
        service="ECS/Fargate",
        region=region,
        resource_id=service_name,
        estimated_monthly_savings_usd=savings,
        recommendation=(
            f"Review task CPU/memory configuration for {service_name} and apply "
            "Compute Optimizer rightsizing recommendations."
        ),
        metadata={
            "source": "compute_optimizer",
            "finding": finding_types[0],
            "cluster_name": cluster_name,
            "service_arn": service_arn,
        },
    )


def finding_from_cost_optimization_hub(rec: dict[str, Any]) -> Finding | None:
    resource_id = rec.get("resourceId") or rec.get("resourceArn", "unknown")
    if isinstance(resource_id, str) and "/" in resource_id:
        resource_id = resource_id.rsplit("/", 1)[-1]

    action = rec.get("actionType", "Optimize")
    service = rec.get("currentResourceType", "AWS")
    region = rec.get("region", "global")
    savings_raw = rec.get("estimatedMonthlySavings")
    if isinstance(savings_raw, dict):
        savings = _parse_float(savings_raw.get("value"))
    else:
        savings = _parse_float(savings_raw)

    detail = (
        rec.get("recommendationDetail")
        or f"Cost Optimization Hub recommends {action} for {resource_id}."
    )
    return Finding(
        id=f"COH-{_slug(str(resource_id))}-{_slug(action)}",
        title=f"Cost Optimization Hub: {action} {resource_id}",
        description=detail,
        severity=Severity.MEDIUM if savings >= 50 else Severity.LOW,
        category=category_for_service(str(service)),
        service=str(service),
        region=region,
        resource_id=str(resource_id),
        estimated_monthly_savings_usd=savings,
        recommendation=f"Implement Cost Optimization Hub recommendation: {action}.",
        metadata={
            "source": "cost_optimization_hub",
            "coh_recommendation_id": rec.get("recommendationId"),
            "action_type": action,
            "implementation_effort": rec.get("implementationEffort"),
            "restart_needed": rec.get("restartNeeded"),
        },
    )
