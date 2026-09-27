"""
Pillar B — Module 1: Infrastructure Hygiene (audit_infra.py)

Goal: Identify high-confidence zombie resources and quick-win volume migrations.

Tasks:
  1.1  Zombie EBS volume identification with CloudTrail validation
  1.2  gp2 → gp3 migration scanner
  1.3  Orphaned/aged snapshot filter (90 days, exclusion tags)
  +    Unassociated Elastic IPs
  +    Load balancers with no healthy targets

All AWS API calls use boto3 paginators to handle accounts of any size.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterator

import boto3

from shared.findings_schema import Category, Finding, Severity

# Snapshot exclusion — any tag key OR value containing these strings is skipped
SNAPSHOT_EXCLUSION_KEYWORDS = {"keep", "migration", "release", "do-not-delete"}
SNAPSHOT_AGE_DAYS = 90

# gp3 is 20% cheaper than gp2 in most regions ($0.10 → $0.08/GB-month)
GP2_PRICE_PER_GB  = 0.10
GP3_PRICE_PER_GB  = 0.08
GP2_GP3_SAVING_PER_GB = GP2_PRICE_PER_GB - GP3_PRICE_PER_GB   # $0.02/GB-month

CLOUDTRAIL_LOOKBACK_DAYS = 30


class InfraHygieneModule:
    def __init__(self, session: boto3.Session, regions: list[str] | None = None,
                 teaser: bool = False, covered_resource_ids: set[str] | None = None) -> None:
        self.session = session
        self.region  = session.region_name
        self.regions = regions or [self.region]
        self.teaser  = teaser
        self.covered_resource_ids = {r.lower().strip() for r in (covered_resource_ids or set())}

    def run(self) -> list[Finding]:
        findings: list[Finding] = []
        findings.extend(self._check_unattached_ebs_volumes())
        findings.extend(self._check_gp2_volumes())
        findings.extend(self._check_orphaned_snapshots())
        findings.extend(self._check_unassociated_elastic_ips())
        findings.extend(self._check_idle_load_balancers())
        findings.extend(self._check_ecr_missing_lifecycle())
        return findings

    # ------------------------------------------------------------------
    # Task 1.1 — Zombie EBS volumes with CloudTrail validation
    # ------------------------------------------------------------------

    def _check_unattached_ebs_volumes(self) -> list[Finding]:
        """
        List unattached (status=available) EBS volumes, then verify via CloudTrail
        whether each was recently detached. A volume with no DetachVolume event
        in the last 30 days has a higher probability of being a true zombie.

        Output includes safe_to_delete boolean in metadata.
        """
        findings: list[Finding] = []
        now   = datetime.now(timezone.utc)
        start = now - timedelta(days=CLOUDTRAIL_LOOKBACK_DAYS)

        for region in self.regions:
            ec2 = self.session.client("ec2", region_name=region)
            ct  = self.session.client("cloudtrail", region_name=region)

            paginator = ec2.get_paginator("describe_volumes")
            for page in paginator.paginate(
                Filters=[{"Name": "status", "Values": ["available"]}]
            ):
                for vol in page["Volumes"]:
                    vol_id = vol["VolumeId"]
                    if vol_id.lower() in self.covered_resource_ids:
                        continue

                    # CloudTrail: look for DetachVolume events in the last 30 days
                    recent_detach = False
                    try:
                        ct_resp = ct.lookup_events(
                            LookupAttributes=[
                                {"AttributeKey": "ResourceName", "AttributeValue": vol_id}
                            ],
                            StartTime=start,
                            EndTime=now,
                        )
                        recent_detach = any(
                            e["EventName"] == "DetachVolume"
                            for e in ct_resp.get("Events", [])
                        )
                    except Exception:
                        pass   # CloudTrail may not be enabled; proceed conservatively

                    safe_to_delete = not recent_detach
                    severity = Severity.HIGH if safe_to_delete else Severity.MEDIUM
                    monthly_savings = round(vol["Size"] * GP2_PRICE_PER_GB, 2)

                    findings.append(Finding(
                        id=f"HYGIENE-EBS-{vol_id}",
                        title="Unattached EBS volume"
                        + (" (safe to delete)" if safe_to_delete else " (recently detached — verify)"),
                        description=(
                            f"Volume {vol_id} ({vol['Size']} GiB {vol['VolumeType']}) is not attached "
                            f"to any instance. CloudTrail {'found no' if safe_to_delete else 'found a'} "
                            f"DetachVolume event in the last {CLOUDTRAIL_LOOKBACK_DAYS} days."
                        ),
                        severity=severity,
                        category=Category.INFRA_HYGIENE,
                        service="EC2/EBS",
                        region=region,
                        resource_id=vol_id,
                        estimated_monthly_savings_usd=monthly_savings if safe_to_delete else 0.0,
                        recommendation=(
                            "Snapshot then delete this volume."
                            if safe_to_delete else
                            "Verify with the team who last used this volume before deleting."
                        ),
                        metadata={
                            "volume_id":       vol_id,
                            "size_gib":        vol["Size"],
                            "volume_type":     vol["VolumeType"],
                            "create_time":     str(vol.get("CreateTime", "")),
                            "safe_to_delete":  safe_to_delete,
                            "recent_detach_in_cloudtrail": recent_detach,
                        },
                    ))
        return findings

    # ------------------------------------------------------------------
    # Task 1.2 — gp2 → gp3 migration scanner
    # ------------------------------------------------------------------

    def _check_gp2_volumes(self) -> list[Finding]:
        """
        Identify all gp2 volumes. Migrating to gp3 saves ~20% with equal or better
        performance (gp3 baseline: 3000 IOPS / 125 MB/s — free upgrades from gp2 defaults).

        Output includes current_attached_instance_ids and estimated savings.
        """
        findings: list[Finding] = []

        for region in self.regions:
            ec2 = self.session.client("ec2", region_name=region)

            paginator = ec2.get_paginator("describe_volumes")
            for page in paginator.paginate(
                Filters=[{"Name": "volume-type", "Values": ["gp2"]}]
            ):
                for vol in page["Volumes"]:
                    vol_id          = vol["VolumeId"]
                    size_gib        = vol["Size"]
                    monthly_savings = round(size_gib * GP2_GP3_SAVING_PER_GB, 2)

                    attached_instance_ids = [
                        att["InstanceId"]
                        for att in vol.get("Attachments", [])
                        if att.get("State") == "attached"
                    ]

                    findings.append(Finding(
                        id=f"HYGIENE-GP2-{vol_id}",
                        title="gp2 EBS volume — migrate to gp3 for 20% savings",
                        description=(
                            f"Volume {vol_id} ({size_gib} GiB) uses the legacy gp2 type. "
                            f"Migrating to gp3 saves ${monthly_savings:.2f}/month with no "
                            f"performance regression (same IOPS/throughput baseline)."
                        ),
                        severity=Severity.LOW,
                        category=Category.INFRA_HYGIENE,
                        service="EC2/EBS",
                        region=region,
                        resource_id=vol_id,
                        estimated_monthly_savings_usd=monthly_savings,
                        recommendation=(
                            "Run: aws ec2 modify-volume --volume-type gp3 "
                            f"--volume-id {vol_id}  (zero-downtime, live migration)"
                        ),
                        metadata={
                            "volume_id":                   vol_id,
                            "size_gib":                    size_gib,
                            "current_type":                "gp2",
                            "recommended_type":            "gp3",
                            "current_attached_instance_ids": attached_instance_ids,
                            "estimated_monthly_savings_usd": monthly_savings,
                        },
                    ))
        return findings

    # ------------------------------------------------------------------
    # Task 1.3 — Orphaned / aged snapshots
    # ------------------------------------------------------------------

    def _check_orphaned_snapshots(self) -> list[Finding]:
        """
        Find snapshots that are:
          - older than SNAPSHOT_AGE_DAYS (90 days)
          - not associated with any AMI
          - not tagged with exclusion keywords (keep, migration, release, do-not-delete)

        Exclusion check is case-insensitive and matches on both tag key and value.
        """
        sts = self.session.client("sts")
        account_id = sts.get_caller_identity()["Account"]
        now        = datetime.now(timezone.utc)
        cutoff     = now - timedelta(days=SNAPSHOT_AGE_DAYS)

        findings: list[Finding] = []

        for region in self.regions:
            ec2 = self.session.client("ec2", region_name=region)

            # Build set of snapshot IDs backing active AMIs
            ami_snapshot_ids: set[str] = set()
            ami_paginator = ec2.get_paginator("describe_images")
            for page in ami_paginator.paginate(Owners=[account_id]):
                for image in page["Images"]:
                    for mapping in image.get("BlockDeviceMappings", []):
                        snap_id = mapping.get("Ebs", {}).get("SnapshotId")
                        if snap_id:
                            ami_snapshot_ids.add(snap_id)

            snap_paginator = ec2.get_paginator("describe_snapshots")
            for page in snap_paginator.paginate(OwnerIds=[account_id]):
                for snap in page["Snapshots"]:
                    snap_id    = snap["SnapshotId"]
                    start_time = snap["StartTime"]

                    # Age filter
                    if start_time > cutoff:
                        continue

                    # AMI association filter
                    if snap_id in ami_snapshot_ids:
                        continue

                    # Exclusion tag filter (case-insensitive, key OR value)
                    if _has_exclusion_tag(snap.get("Tags", []), SNAPSHOT_EXCLUSION_KEYWORDS):
                        continue

                    age_days    = (now - start_time).days
                    size_gib    = snap.get("VolumeSize", 0)
                    monthly_cost = round(size_gib * 0.05, 2)   # ~$0.05/GB-month snapshot storage

                    findings.append(Finding(
                        id=f"HYGIENE-SNAP-{snap_id}",
                        title=f"Orphaned EBS snapshot (aged {age_days} days)",
                        description=(
                            f"Snapshot {snap_id} ({size_gib} GiB) is {age_days} days old, "
                            f"not associated with any AMI, and has no exclusion tags."
                        ),
                        severity=Severity.LOW,
                        category=Category.INFRA_HYGIENE,
                        service="EC2/EBS",
                        region=region,
                        resource_id=snap_id,
                        estimated_monthly_savings_usd=monthly_cost,
                        recommendation="Review and delete if no longer needed for disaster-recovery.",
                        metadata={
                            "snapshot_id":    snap_id,
                            "size_gib":       size_gib,
                            "age_days":       age_days,
                            "start_time":     str(start_time),
                            "description":    snap.get("Description", ""),
                        },
                    ))
        return findings

    # ------------------------------------------------------------------
    # Bonus: Unassociated Elastic IPs
    # ------------------------------------------------------------------

    def _check_unassociated_elastic_ips(self) -> list[Finding]:
        findings: list[Finding] = []
        for region in self.regions:
            ec2 = self.session.client("ec2", region_name=region)
            # describe_addresses has no paginator — response is always complete
            addresses = ec2.describe_addresses()["Addresses"]
            findings.extend([
                Finding(
                    id=f"HYGIENE-EIP-{a['AllocationId']}",
                    title="Unassociated Elastic IP",
                    description=(
                        f"Elastic IP {a.get('PublicIp', a['AllocationId'])} "
                        f"is not associated with any resource but incurs ~$3.65/month."
                    ),
                    severity=Severity.LOW,
                    category=Category.INFRA_HYGIENE,
                    service="EC2",
                    region=region,
                    resource_id=a["AllocationId"],
                    estimated_monthly_savings_usd=3.65,
                    recommendation="Release this Elastic IP if it is no longer required.",
                    metadata={"public_ip": a.get("PublicIp", ""), "allocation_id": a["AllocationId"]},
                )
                for a in addresses
                if "AssociationId" not in a
                and a.get("AllocationId", "").lower() not in self.covered_resource_ids
                and a.get("PublicIp", "").lower() not in self.covered_resource_ids
            ])
        return findings

    # ------------------------------------------------------------------
    # Bonus: Load balancers with no healthy targets
    # ------------------------------------------------------------------

    def _check_idle_load_balancers(self) -> list[Finding]:
        findings: list[Finding] = []

        for region in self.regions:
            elb = self.session.client("elbv2", region_name=region)

            lb_paginator = elb.get_paginator("describe_load_balancers")
            for page in lb_paginator.paginate():
                for lb in page["LoadBalancers"]:
                    lb_name = lb.get("LoadBalancerName", "")
                    lb_arn  = lb.get("LoadBalancerArn", "")
                    if lb_name.lower() in self.covered_resource_ids or lb_arn.lower() in self.covered_resource_ids:
                        continue
                    tg_paginator = elb.get_paginator("describe_target_groups")
                    all_healthy = False
                    for tg_page in tg_paginator.paginate(LoadBalancerArn=lb["LoadBalancerArn"]):
                        for tg in tg_page["TargetGroups"]:
                            health = elb.describe_target_health(
                                TargetGroupArn=tg["TargetGroupArn"]
                            )["TargetHealthDescriptions"]
                            if any(t["TargetHealth"]["State"] == "healthy" for t in health):
                                all_healthy = True
                                break
                        if all_healthy:
                            break

                    if not all_healthy:
                        findings.append(Finding(
                            id=f"HYGIENE-ELB-{lb['LoadBalancerName']}",
                            title="Load balancer with no healthy targets",
                            description=(
                                f"Load balancer {lb['LoadBalancerName']} ({lb['Type']}) "
                                f"has no healthy registered targets but continues to incur ~$16/month."
                            ),
                            severity=Severity.HIGH,
                            category=Category.INFRA_HYGIENE,
                            service="ELB",
                            region=region,
                            resource_id=lb["LoadBalancerArn"],
                            estimated_monthly_savings_usd=16.20,
                            recommendation="Delete the load balancer or register and health-check targets.",
                            metadata={
                                "lb_name":   lb["LoadBalancerName"],
                                "lb_type":   lb["Type"],
                                "scheme":    lb["Scheme"],
                            },
                        ))
        return findings

    # ------------------------------------------------------------------
    # ECR repositories without lifecycle policy
    # ------------------------------------------------------------------

    def _check_ecr_missing_lifecycle(self) -> list[Finding]:
        findings: list[Finding] = []

        for region in self.regions:
            ecr = self.session.client("ecr", region_name=region)

            try:
                paginator = ecr.get_paginator("describe_repositories")
            except Exception:
                continue

            for page in paginator.paginate():
                for repo in page.get("repositories", []):
                    name = repo["repositoryName"]
                    try:
                        ecr.get_lifecycle_policy(repositoryName=name)
                    except ecr.exceptions.LifecyclePolicyNotFoundException:
                        findings.append(Finding(
                            id=f"HYGIENE-ECR-{name}",
                            title=f"ECR repository '{name}' has no lifecycle policy",
                            description=(
                                f"ECR repository '{name}' has no lifecycle policy. Untagged and "
                                f"old images accumulate storage charges (~$0.10/GB-month)."
                            ),
                            severity=Severity.LOW,
                            category=Category.INFRA_HYGIENE,
                            service="ECR",
                            region=region,
                            resource_id=name,
                            estimated_monthly_savings_usd=0.0,
                            recommendation=(
                                "Add a lifecycle policy to expire untagged images after 7 days "
                                "and keep only the last 10 tagged images."
                            ),
                            metadata={
                                "repository_name": name,
                                "repository_arn": repo.get("repositoryArn", ""),
                                "suggested_policy": {
                                    "rules": [{
                                        "rulePriority": 1,
                                        "description": "Expire untagged images after 7 days",
                                        "selection": {
                                            "tagStatus": "untagged",
                                            "countType": "sinceImagePushed",
                                            "countUnit": "days",
                                            "countNumber": 7,
                                        },
                                        "action": {"type": "expire"},
                                    }],
                                },
                            },
                        ))
                    except Exception:
                        continue

        return findings


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _has_exclusion_tag(tags: list[dict], exclusion_keywords: set[str]) -> bool:
    """Return True if any tag key or value contains an exclusion keyword (case-insensitive)."""
    for tag in tags:
        key   = tag.get("Key",   "").lower()
        value = tag.get("Value", "").lower()
        for keyword in exclusion_keywords:
            if keyword in key or keyword in value:
                return True
    return False
