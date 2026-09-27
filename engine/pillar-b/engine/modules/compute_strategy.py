"""
Pillar B — Module 2: Compute Strategy (audit_compute.py)

Goal: Architect Spot Fleet transition plans with zero-downtime on-demand fallbacks.

Tasks:
  2.1  Stateless workload identification via Auto Scaling Groups
  2.2  Spot Fleet architecture recommendation JSON generator
  +    Idle EC2 instances (CPU < threshold, CloudWatch)
  +    Stopped instances with attached EBS still billing
  +    Graviton upgrade opportunities

All AWS API calls use boto3 paginators.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import boto3

from shared.findings_schema import Category, Finding, Severity
from shared.cw_helper import batch_metric_averages

CPU_IDLE_THRESHOLD_PCT = 5.0
CPU_LOOKBACK_DAYS      = 14

# Keywords that indicate a stateful / database workload — exclude from Spot recommendations
STATEFUL_KEYWORDS = {"db", "database", "stateful", "mysql", "postgres", "oracle", "mongo", "redis"}

X86_TO_GRAVITON = {
    "m5": "m6g", "m5a": "m6g", "m6i": "m6g", "m7i": "m7g",
    "c5": "c6g", "c5a": "c6g", "c6i": "c6g", "c7i": "c7g",
    "r5": "r6g", "r5a": "r6g", "r6i": "r6g", "r7i": "r7g",
}


def _ec2_name(inst: dict) -> str:
    return next((t["Value"] for t in inst.get("Tags", []) if t["Key"] == "Name"), "")


class ComputeStrategyModule:
    def __init__(self, session: boto3.Session, regions: list[str] | None = None,
                 teaser: bool = False, covered_resource_ids: set[str] | None = None) -> None:
        self.session = session
        self.region  = session.region_name
        self.regions = regions or [self.region]
        self.teaser  = teaser
        self.covered_resource_ids = {r.lower().strip() for r in (covered_resource_ids or set())}

    def run(self) -> list[Finding]:
        findings: list[Finding] = []
        findings.extend(self._check_stateless_asgs())
        if not self.teaser:
            findings.extend(self._check_idle_instances())
        findings.extend(self._check_stopped_instances())
        findings.extend(self._check_graviton_opportunities())
        return findings

    # ------------------------------------------------------------------
    # Task 2.1 + 2.2 — Stateless ASG identification + Spot recommendation
    # ------------------------------------------------------------------

    def _check_stateless_asgs(self) -> list[Finding]:
        findings: list[Finding] = []

        for region in self.regions:
            asg_client = self.session.client("autoscaling", region_name=region)
            elb_client = self.session.client("elbv2", region_name=region)

            tg_arns: set[str] = set()
            for page in elb_client.get_paginator("describe_target_groups").paginate():
                for tg in page["TargetGroups"]:
                    tg_arns.add(tg["TargetGroupArn"])

            for page in asg_client.get_paginator("describe_auto_scaling_groups").paginate():
                for asg in page["AutoScalingGroups"]:
                    asg_name = asg["AutoScalingGroupName"]
                    asg_tg_arns = set(asg.get("TargetGroupARNs", []))
                    if not asg_tg_arns.intersection(tg_arns):
                        continue
                    running = [i for i in asg.get("Instances", []) if i.get("LifecycleState") == "InService"]
                    if not running:
                        continue
                    if not all(i.get("InstanceType") and not _is_spot_instance(i) for i in running):
                        continue
                    if _asg_is_stateful(asg):
                        continue
                    instance_types  = list({i["InstanceType"] for i in running})
                    spot_config     = _build_spot_recommendation(asg, instance_types)
                    on_demand_count = len(running)
                    findings.append(Finding(
                        id=f"COMPUTE-ASG-SPOT-{asg_name}",
                        title=f"ASG '{asg_name}' running 100% On-Demand — Spot Fleet candidate",
                        description=(
                            f"Auto Scaling Group '{asg_name}' has {on_demand_count} On-Demand "
                            f"instances behind a load balancer with no stateful tags. "
                            f"Switching to the recommended mixed-instances Spot policy could "
                            f"reduce compute costs by 60–80%."
                        ),
                        severity=Severity.HIGH,
                        category=Category.COMPUTE_STRATEGY,
                        service="EC2/ASG",
                        region=region,
                        resource_id=asg_name,
                        estimated_monthly_savings_usd=0.0,
                        recommendation=(
                            "Apply the spot_fleet_recommendation in metadata to the ASG's "
                            "MixedInstancesPolicy. Deploy the EventBridge rule for 2-minute "
                            "interruption notice to ensure graceful connection draining."
                        ),
                        metadata={
                            "asg_name":                  asg_name,
                            "on_demand_instance_count":  on_demand_count,
                            "current_instance_types":    instance_types,
                            "spot_fleet_recommendation": spot_config,
                        },
                    ))
        return findings

    # ------------------------------------------------------------------
    # Idle EC2 instances
    # ------------------------------------------------------------------

    def _check_idle_instances(self) -> list[Finding]:
        findings: list[Finding] = []
        end   = datetime.now(timezone.utc)
        start = end - timedelta(days=CPU_LOOKBACK_DAYS)

        for region in self.regions:
            ec2 = self.session.client("ec2", region_name=region)
            cw  = self.session.client("cloudwatch", region_name=region)

            # Collect all running instances first, then batch-query CloudWatch.
            # Avoids 1 API call per instance (InternalFailure / throttle on large accounts).
            instances: list[dict] = []
            for page in ec2.get_paginator("describe_instances").paginate(
                Filters=[{"Name": "instance-state-name", "Values": ["running"]}]
            ):
                for res in page["Reservations"]:
                    instances.extend(res["Instances"])

            instances = [
                i for i in instances
                if i["InstanceId"].lower() not in self.covered_resource_ids
            ]

            if not instances:
                continue

            avg_cpu_by_id = batch_metric_averages(
                cw, "AWS/EC2", "CPUUtilization", "InstanceId",
                [i["InstanceId"] for i in instances],
                start, end,
            )

            for inst in instances:
                iid     = inst["InstanceId"]
                avg_cpu = avg_cpu_by_id.get(iid)
                if avg_cpu is None:
                    continue
                if avg_cpu < CPU_IDLE_THRESHOLD_PCT:
                    name  = _ec2_name(inst)
                    label = f"{iid} ({name})" if name else iid
                    findings.append(Finding(
                        id=f"COMPUTE-IDLE-{iid}",
                        title=f"Idle EC2 instance — {label}",
                        description=(
                            f"Instance {iid} ({inst['InstanceType']}) averaged "
                            f"{avg_cpu:.1f}% CPU over {CPU_LOOKBACK_DAYS} days."
                        ),
                        severity=Severity.HIGH,
                        category=Category.COMPUTE_STRATEGY,
                        service="EC2",
                        region=region,
                        resource_id=iid,
                        estimated_monthly_savings_usd=0.0,
                        recommendation="Right-size to a smaller instance type or terminate if unused.",
                        metadata={
                            "instance_type":   inst["InstanceType"],
                            "avg_cpu_pct":     round(avg_cpu, 2),
                            "lookback_days":   CPU_LOOKBACK_DAYS,
                            "instance_name":   name,
                        },
                    ))
        return findings

    # ------------------------------------------------------------------
    # Stopped instances (EBS still billing)
    # ------------------------------------------------------------------

    def _check_stopped_instances(self) -> list[Finding]:
        findings: list[Finding] = []

        for region in self.regions:
            ec2 = self.session.client("ec2", region_name=region)

            paginator = ec2.get_paginator("describe_instances")
            for page in paginator.paginate(
                Filters=[{"Name": "instance-state-name", "Values": ["stopped"]}]
            ):
                for reservation in page["Reservations"]:
                    for inst in reservation["Instances"]:
                        iid   = inst["InstanceId"]
                        if iid.lower() in self.covered_resource_ids:
                            continue
                        name  = _ec2_name(inst)
                        label = f"{iid} ({name})" if name else iid
                        findings.append(Finding(
                            id=f"COMPUTE-STOPPED-{iid}",
                            title=f"Stopped EC2 instance with attached EBS storage — {label}",
                            description=(
                                f"Instance {iid} ({inst['InstanceType']}) is stopped. "
                                f"Attached EBS volumes continue to bill regardless of instance state."
                            ),
                            severity=Severity.MEDIUM,
                            category=Category.COMPUTE_STRATEGY,
                            service="EC2",
                            region=region,
                            resource_id=iid,
                            estimated_monthly_savings_usd=0.0,
                            recommendation="Snapshot the root volume, terminate the instance, or restart it if actively needed.",
                            metadata={
                                "instance_type":  inst["InstanceType"],
                                "instance_name":  name,
                            },
                        ))
        return findings

    # ------------------------------------------------------------------
    # Graviton upgrade opportunities
    # ------------------------------------------------------------------

    def _check_graviton_opportunities(self) -> list[Finding]:
        findings: list[Finding] = []

        for region in self.regions:
            ec2 = self.session.client("ec2", region_name=region)

            paginator = ec2.get_paginator("describe_instances")
            for page in paginator.paginate(
                Filters=[{"Name": "instance-state-name", "Values": ["running"]}]
            ):
                for reservation in page["Reservations"]:
                    for inst in reservation["Instances"]:
                        itype  = inst["InstanceType"]
                        family = itype.split(".")[0]
                        graviton_family = X86_TO_GRAVITON.get(family)
                        if not graviton_family:
                            continue
                        size        = itype.split(".")[1]
                        recommended = f"{graviton_family}.{size}"
                        iid   = inst["InstanceId"]
                        name  = _ec2_name(inst)
                        label = f"{iid} ({name})" if name else iid
                        findings.append(Finding(
                            id=f"COMPUTE-GRAVITON-{iid}",
                            title=f"Graviton upgrade opportunity (~20% better price-performance) — {label}",
                            description=(
                                f"Instance {iid} runs {itype} (x86). "
                                f"Equivalent Graviton type {recommended} offers ~20% lower cost "
                                f"with equal or better performance."
                            ),
                            severity=Severity.LOW,
                            category=Category.COMPUTE_STRATEGY,
                            service="EC2",
                            region=region,
                            resource_id=iid,
                            estimated_monthly_savings_usd=0.0,
                            recommendation=f"Test workload compatibility on {recommended} and migrate.",
                            metadata={
                                "current_type":     itype,
                                "recommended_type": recommended,
                                "instance_name":    name,
                            },
                        ))
        return findings


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _is_spot_instance(instance: dict) -> bool:
    """Spot instances in an ASG have a non-None SpotInstanceRequestId."""
    return bool(instance.get("SpotInstanceRequestId"))


def _asg_is_stateful(asg: dict) -> bool:
    """Return True if any ASG tag key or value contains a stateful keyword."""
    for tag in asg.get("Tags", []):
        key   = tag.get("Key",   "").lower()
        value = tag.get("Value", "").lower()
        if any(kw in key or kw in value for kw in STATEFUL_KEYWORDS):
            return True
    # Also check the ASG name itself
    return any(kw in asg["AutoScalingGroupName"].lower() for kw in STATEFUL_KEYWORDS)


def _build_spot_recommendation(asg: dict, instance_types: list[str]) -> dict:
    """
    Task 2.2 — Generate a Spot Fleet architecture recommendation JSON.

    Parameters follow the spec exactly:
      - AllocationStrategy: capacity-optimized
      - OnDemandBaseCapacity: 1 (baseline to absorb traffic during Spot reclaim)
      - OnDemandPercentageAboveBaseCapacity: 0 (rely entirely on Spot for scaling)
      - SpotInterruptionBehavior: EventBridge rule for 2-minute notice + drain
    """
    # Suggest diversified instance families for better Spot availability
    diversified_overrides = [
        {"InstanceType": itype} for itype in instance_types
    ]
    # Add next-gen equivalent if available
    for itype in list(instance_types):
        family = itype.split(".")[0]
        size   = itype.split(".")[1]
        graviton = X86_TO_GRAVITON.get(family)
        if graviton:
            alt = f"{graviton}.{size}"
            if {"InstanceType": alt} not in diversified_overrides:
                diversified_overrides.append({"InstanceType": alt})

    return {
        "AllocationStrategy":                    "capacity-optimized",
        "OnDemandBaseCapacity":                  1,
        "OnDemandPercentageAboveBaseCapacity":   0,
        "SpotMaxPrice":                          "",   # blank = use On-Demand price as cap
        "InstanceOverrides":                     diversified_overrides,
        "SpotInterruptionHandling": {
            "approach": "EventBridge rule for EC2 Spot Instance Interruption Notice",
            "notice_window_minutes": 2,
            "recommended_actions": [
                "Publish EventBridge rule: source=aws.ec2, detail-type=EC2 Spot Instance Interruption Warning",
                "Lambda target: call ELB DeregisterTargets for the interrupted instance",
                "Lambda target: send SIGTERM to application process for graceful shutdown",
                "Set ASG termination policy to OldestInstance so oldest Spot reclaims first",
            ],
            "eventbridge_pattern": {
                "source":       ["aws.ec2"],
                "detail-type":  ["EC2 Spot Instance Interruption Warning"],
            },
        },
        "source_asg":         asg["AutoScalingGroupName"],
        "current_desired":    asg.get("DesiredCapacity", 0),
        "current_min":        asg.get("MinSize", 0),
        "current_max":        asg.get("MaxSize", 0),
    }
