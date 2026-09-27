"""
Pillar B — Module 3: Network & Storage Tiering (audit_net_storage.py)

Goal: Expose hidden data-transfer fees and automate S3 tiering rules.

Tasks:
  3.1  Inter-AZ and NAT Gateway bleed detection via Cost Explorer API
  3.2  S3 Glacier Instant Retrieval (GIR) / Intelligent-Tiering threshold analysis
  3.3  Idle NAT Gateways (CloudWatch — no traffic in 7 days)
  3.4  S3 incomplete multipart uploads + versioned buckets without lifecycle
  3.5  Inactive VPC interface endpoints (CloudWatch — no bytes processed)

All AWS API calls use boto3 paginators where applicable.
Cost Explorer does not use paginators — results are complete per call.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import boto3

from shared.aws_client import scope_ce_filter
from shared.cw_helper import batch_metric_averages
from shared.findings_schema import Category, Finding, Severity

CE_LOOKBACK_DAYS = 30

# Flag inter-AZ spend above this threshold for architectural review
INTER_AZ_ALERT_THRESHOLD_USD = 500.0

# Recommended S3 tiering thresholds (per spec)
S3_SMALL_OBJECT_BYTES   = 1 * 1024 * 1024   # 1 MB
S3_GIR_TRANSITION_DAYS  = 30                 # days of infrequent access before GIR

# NAT Gateway: ~$32/month fixed + $0.045/GB processed
NAT_MONTHLY_FIXED_USD = 32.40
NAT_IDLE_LOOKBACK_DAYS = 7

# S3 multipart uploads older than this are flagged
S3_MULTIPART_AGE_DAYS = 7

# VPC interface endpoint fixed cost ~$7.20/month per AZ
VPC_ENDPOINT_MONTHLY_USD = 7.20
VPC_ENDPOINT_IDLE_DAYS = 14


class NetworkStorageModule:
    def __init__(self, session: boto3.Session, regions: list[str] | None = None,
                 teaser: bool = False, billing_session: boto3.Session | None = None,
                 billing_account_id: str = "", covered_resource_ids: set[str] | None = None) -> None:
        self.session = session
        self.region  = session.region_name
        self.regions = regions or [self.region]
        self.teaser  = teaser
        # Cost Explorer (data-transfer bleed) runs through the payer session when
        # supplied, scoped to the target member account via billing_account_id.
        self.billing_session    = billing_session or session
        self.billing_account_id = billing_account_id
        self.covered_resource_ids = {r.lower().strip() for r in (covered_resource_ids or set())}

    def run(self) -> list[Finding]:
        findings: list[Finding] = []
        if not self.teaser:
            findings.extend(self._check_data_transfer_costs())
            findings.extend(self._check_idle_nat_gateways())
            findings.extend(self._check_inactive_vpc_endpoints())
        findings.extend(self._check_s3_bucket_hygiene())
        return findings

    # ------------------------------------------------------------------
    # Task 3.1 — Inter-AZ + NAT Gateway bleed via Cost Explorer
    # ------------------------------------------------------------------

    def _check_data_transfer_costs(self) -> list[Finding]:
        """
        Query Cost Explorer for the last 30 days of:
          - NAT Gateway data-processing charges
            (Service = EC2, UsageType contains 'NatGateway-Bytes')
          - Inter-AZ regional data-transfer charges
            (UsageType contains 'DataTransfer-Regional-Bytes')

        If inter-AZ spend > $500/month, flag for VPC Endpoint review.
        """
        ce  = self.billing_session.client("ce", region_name="us-east-1")
        end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        start = (datetime.now(timezone.utc) - timedelta(days=CE_LOOKBACK_DAYS)).strftime("%Y-%m-%d")

        findings: list[Finding] = []

        # --- NAT Gateway data processing ---
        nat_cost = self._ce_query_cost(
            ce, start, end,
            filter_expr={
                "And": [
                    {
                        "Dimensions": {
                            "Key":    "SERVICE",
                            "Values": ["Amazon Elastic Compute Cloud - Compute"],
                        }
                    },
                    {
                        "Dimensions": {
                            "Key":    "USAGE_TYPE_GROUP",
                            "Values": ["EC2: NAT Gateway - Data Processed"],
                        }
                    },
                ]
            },
        )

        if nat_cost > 0:
            monthly_nat = round(nat_cost * (30 / CE_LOOKBACK_DAYS), 2)
            findings.append(Finding(
                id=f"NETWORK-NAT-BLEED-{self.region}",
                title="NAT Gateway data-processing charges detected",
                description=(
                    f"NAT Gateway data-processing cost: ${nat_cost:.2f} in the last "
                    f"{CE_LOOKBACK_DAYS} days (~${monthly_nat:.2f}/month). "
                    f"Common causes: EC2 instances in private subnets pulling container "
                    f"images or reaching AWS services via NAT instead of VPC Endpoints."
                ),
                severity=Severity.HIGH if monthly_nat > 100 else Severity.MEDIUM,
                category=Category.NETWORK_STORAGE,
                service="VPC/NAT",
                region=self.region,
                resource_id=f"nat-gateway-{self.region}",
                estimated_monthly_savings_usd=monthly_nat * 0.4,   # ~40% reduction with VPC Endpoints
                recommendation=(
                    "Add VPC Interface Endpoints for S3, ECR, and other frequently-used "
                    "AWS services accessed from private subnets. This eliminates NAT "
                    "Gateway data-processing charges for those services."
                ),
                metadata={
                    "cost_last_30d_usd":      round(nat_cost, 2),
                    "estimated_monthly_usd":  monthly_nat,
                    "query_period_days":      CE_LOOKBACK_DAYS,
                    "recommended_action":     "Add VPC Endpoints for S3, ECR, Secrets Manager",
                },
            ))

        # --- Inter-AZ regional data transfer ---
        inter_az_cost = self._ce_query_cost(
            ce, start, end,
            filter_expr={
                "Dimensions": {
                    "Key":    "USAGE_TYPE_GROUP",
                    "Values": ["EC2: Data Transfer - Inter AZ"],
                }
            },
        )

        if inter_az_cost > 0:
            monthly_inter_az = round(inter_az_cost * (30 / CE_LOOKBACK_DAYS), 2)
            severity = (
                Severity.CRITICAL if monthly_inter_az > INTER_AZ_ALERT_THRESHOLD_USD
                else Severity.HIGH if monthly_inter_az > 100
                else Severity.MEDIUM
            )
            arch_review = monthly_inter_az > INTER_AZ_ALERT_THRESHOLD_USD

            findings.append(Finding(
                id=f"NETWORK-INTERAZ-{self.region}",
                title="Inter-AZ data transfer charges"
                + (" — flag for architectural review" if arch_review else ""),
                description=(
                    f"Inter-AZ data transfer: ${inter_az_cost:.2f} in the last "
                    f"{CE_LOOKBACK_DAYS} days (~${monthly_inter_az:.2f}/month). "
                    + (
                        f"EXCEEDS ${INTER_AZ_ALERT_THRESHOLD_USD:.0f}/month threshold — "
                        f"recommend architectural review for service co-location."
                        if arch_review else
                        "Review service placement to reduce cross-AZ traffic."
                    )
                ),
                severity=severity,
                category=Category.NETWORK_STORAGE,
                service="VPC",
                region=self.region,
                resource_id=f"inter-az-transfer-{self.region}",
                estimated_monthly_savings_usd=round(
                    monthly_inter_az * 0.25 if arch_review else monthly_inter_az * 0.15, 2
                ),
                recommendation=(
                    "Co-locate services in the same AZ (e.g. ECS tasks with RDS replicas). "
                    "Use ElastiCache to reduce cross-AZ DB reads. "
                    "Enable VPC Endpoints to avoid AZ hairpinning. "
                    "Note: Multi-AZ RDS/ElastiCache replication and EKS cross-AZ traffic are expected "
                    "and cannot be eliminated by placement changes -- focus on EC2/container traffic patterns."
                    + (" Escalate to architecture review -- spend exceeds $500/month."
                       if arch_review else "")
                ),
                metadata={
                    "cost_last_30d_usd":          round(inter_az_cost, 2),
                    "estimated_monthly_usd":       monthly_inter_az,
                    "exceeds_alert_threshold":     arch_review,
                    "alert_threshold_usd":         INTER_AZ_ALERT_THRESHOLD_USD,
                    "query_period_days":           CE_LOOKBACK_DAYS,
                    "recommended_action":          "architectural_review" if arch_review else "optimize_placement",
                },
            ))

        return findings

    def _ce_query_cost(
        self,
        ce_client,
        start: str,
        end:   str,
        filter_expr: dict,
    ) -> float:
        """Query Cost Explorer and return total UnblendedCost as a float."""
        try:
            resp = ce_client.get_cost_and_usage(
                TimePeriod={"Start": start, "End": end},
                Granularity="MONTHLY",
                Filter=scope_ce_filter(filter_expr, self.billing_account_id),
                Metrics=["UnblendedCost"],
            )
        except Exception as exc:
            print(f"[network_storage] Cost Explorer query failed: {exc}")
            return 0.0

        total = 0.0
        for result in resp.get("ResultsByTime", []):
            amount = result.get("Total", {}).get("UnblendedCost", {}).get("Amount", "0")
            total += float(amount)
        return total

    # ------------------------------------------------------------------
    # Task 3.3 — Idle NAT Gateways (CloudWatch)
    # ------------------------------------------------------------------

    def _check_idle_nat_gateways(self) -> list[Finding]:
        """
        Flag NAT Gateways with zero bytes processed in the last 7 days.
        Matches AWS Trusted Advisor 'Idle NAT gateways' check logic.
        """
        findings: list[Finding] = []
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=NAT_IDLE_LOOKBACK_DAYS)

        for region in self.regions:
            ec2 = self.session.client("ec2", region_name=region)
            cw  = self.session.client("cloudwatch", region_name=region)

            nat_ids: list[str] = []
            for page in ec2.get_paginator("describe_nat_gateways").paginate(
                Filter=[{"Name": "state", "Values": ["available"]}]
            ):
                for nat in page["NatGateways"]:
                    nat_ids.append(nat["NatGatewayId"])

            nat_ids = [
                nid for nid in nat_ids
                if nid.lower() not in self.covered_resource_ids
            ]

            if not nat_ids:
                continue

            bytes_out = batch_metric_averages(
                cw, "AWS/NATGateway", "BytesOutToDestination",
                "NatGatewayId", nat_ids, start, end,
                period=86400, stat="Sum", aggregate="sum",
            )
            bytes_in = batch_metric_averages(
                cw, "AWS/NATGateway", "BytesInFromDestination",
                "NatGatewayId", nat_ids, start, end,
                period=86400, stat="Sum", aggregate="sum",
            )

            for nat_id in nat_ids:
                total_bytes = bytes_out.get(nat_id, 0.0) + bytes_in.get(nat_id, 0.0)
                # No metric data → treat as idle (gateway exists but never used)
                if total_bytes > 0:
                    continue

                findings.append(Finding(
                    id=f"NETWORK-NAT-IDLE-{nat_id}",
                    title=f"Idle NAT Gateway {nat_id}",
                    description=(
                        f"NAT Gateway {nat_id} processed no traffic in the last "
                        f"{NAT_IDLE_LOOKBACK_DAYS} days but incurs ~${NAT_MONTHLY_FIXED_USD:.2f}/month "
                        f"in hourly charges plus data-processing fees."
                    ),
                    severity=Severity.HIGH,
                    category=Category.NETWORK_STORAGE,
                    service="VPC/NAT",
                    region=region,
                    resource_id=nat_id,
                    estimated_monthly_savings_usd=NAT_MONTHLY_FIXED_USD,
                    recommendation=(
                        "Delete this NAT Gateway if no private subnets route through it. "
                        "Verify route tables before removal."
                    ),
                    metadata={
                        "nat_gateway_id": nat_id,
                        "lookback_days": NAT_IDLE_LOOKBACK_DAYS,
                        "bytes_processed": 0,
                    },
                ))

        return findings

    # ------------------------------------------------------------------
    # Task 3.5 — Inactive VPC interface endpoints
    # ------------------------------------------------------------------

    def _check_inactive_vpc_endpoints(self) -> list[Finding]:
        findings: list[Finding] = []
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=VPC_ENDPOINT_IDLE_DAYS)

        for region in self.regions:
            ec2 = self.session.client("ec2", region_name=region)
            cw  = self.session.client("cloudwatch", region_name=region)

            endpoints: list[dict] = []
            for page in ec2.get_paginator("describe_vpc_endpoints").paginate():
                for ep in page["VpcEndpoints"]:
                    if ep.get("VpcEndpointType") == "Interface" and ep.get("State") == "available":
                        endpoints.append(ep)

            if not endpoints:
                continue

            ep_ids = [ep["VpcEndpointId"] for ep in endpoints]
            bytes_processed = batch_metric_averages(
                cw, "AWS/PrivateLinkEndpoints", "BytesProcessed",
                "VPC Endpoint Id", ep_ids, start, end,
                period=86400, stat="Sum", aggregate="sum",
            )

            for ep in endpoints:
                ep_id = ep["VpcEndpointId"]
                if bytes_processed.get(ep_id, 0.0) > 0:
                    continue

                service_name = ep.get("ServiceName", "unknown")
                az_count = len(ep.get("SubnetIds", [])) or 1
                monthly_cost = round(VPC_ENDPOINT_MONTHLY_USD * az_count, 2)

                findings.append(Finding(
                    id=f"NETWORK-VPCE-IDLE-{ep_id}",
                    title=f"Inactive VPC interface endpoint {ep_id}",
                    description=(
                        f"Interface endpoint {ep_id} ({service_name}) processed no traffic "
                        f"in the last {VPC_ENDPOINT_IDLE_DAYS} days but costs "
                        f"~${monthly_cost:.2f}/month across {az_count} AZ(s)."
                    ),
                    severity=Severity.MEDIUM,
                    category=Category.NETWORK_STORAGE,
                    service="VPC/PrivateLink",
                    region=region,
                    resource_id=ep_id,
                    estimated_monthly_savings_usd=monthly_cost,
                    recommendation=(
                        f"Delete endpoint {ep_id} if {service_name} is no longer accessed "
                        "from this VPC, or consolidate to a shared services VPC."
                    ),
                    metadata={
                        "vpc_endpoint_id": ep_id,
                        "service_name": service_name,
                        "subnet_count": az_count,
                        "lookback_days": VPC_ENDPOINT_IDLE_DAYS,
                    },
                ))

        return findings

    # ------------------------------------------------------------------
    # Task 3.2 / 3.4 — S3 bucket hygiene (single pass per bucket)
    # ------------------------------------------------------------------

    def _check_s3_bucket_hygiene(self) -> list[Finding]:
        """
        For each S3 bucket:
          1. Check if a Lifecycle Configuration exists.
          2. If absent, generate a tiering recommendation with two rules:
               - Objects < 1 MB    → S3 Standard-IA after 30 days
               - Objects >= 1 MB   → S3 Glacier Instant Retrieval after 30 days of infrequent access
               - Enable S3 Intelligent-Tiering for automatic optimisation
        """
        s3 = self.session.client("s3")
        findings: list[Finding] = []
        now = datetime.now(timezone.utc)
        multipart_cutoff = now - timedelta(days=S3_MULTIPART_AGE_DAYS)

        buckets = s3.list_buckets().get("Buckets", [])

        for bucket in buckets:
            name = bucket["Name"]
            has_lifecycle = _bucket_has_lifecycle(s3, name)
            versioning_enabled = _bucket_versioning_enabled(s3, name)

            if not has_lifecycle:
                tiering_config = _build_gir_lifecycle_config(name)
                findings.append(Finding(
                    id=f"STORAGE-S3-TIERING-{name}",
                    title=f"S3 bucket '{name}' missing tiering lifecycle policy",
                    description=(
                        f"Bucket '{name}' has no lifecycle rules. Objects accumulate indefinitely "
                        f"in Standard storage. Applying Intelligent-Tiering + GIR transitions "
                        f"could reduce storage costs by 40–68% on infrequently-accessed data."
                    ),
                    severity=Severity.MEDIUM,
                    category=Category.NETWORK_STORAGE,
                    service="S3",
                    region=self.region,
                    resource_id=name,
                    estimated_monthly_savings_usd=0.0,
                    recommendation=(
                        "Apply the lifecycle_configuration in metadata via: "
                        f"aws s3api put-bucket-lifecycle-configuration "
                        f"--bucket {name} --lifecycle-configuration file://config.json"
                    ),
                    metadata={
                        "bucket_name": name,
                        "has_lifecycle_policy": False,
                        "lifecycle_configuration": tiering_config,
                    },
                ))

            if versioning_enabled and not has_lifecycle:
                findings.append(Finding(
                    id=f"STORAGE-S3-VERSIONING-{name}",
                    title=f"S3 bucket '{name}' has versioning without lifecycle",
                    description=(
                        f"Bucket '{name}' has versioning enabled but no lifecycle policy. "
                        f"Old object versions accumulate indefinitely, increasing storage cost."
                    ),
                    severity=Severity.MEDIUM,
                    category=Category.NETWORK_STORAGE,
                    service="S3",
                    region=self.region,
                    resource_id=name,
                    estimated_monthly_savings_usd=0.0,
                    recommendation=(
                        "Add lifecycle rules to expire noncurrent versions after 30–90 days "
                        "and abort incomplete multipart uploads after 7 days."
                    ),
                    metadata={
                        "bucket_name": name,
                        "versioning_enabled": True,
                        "recommended_noncurrent_expiry_days": 90,
                    },
                ))

            stale_uploads = _stale_multipart_uploads(s3, name, multipart_cutoff)
            if stale_uploads:
                findings.append(Finding(
                    id=f"STORAGE-S3-MULTIPART-{name}",
                    title=f"S3 bucket '{name}' has stale incomplete multipart uploads",
                    description=(
                        f"Bucket '{name}' has {len(stale_uploads)} multipart upload(s) older than "
                        f"{S3_MULTIPART_AGE_DAYS} days. Incomplete uploads incur storage charges "
                        f"until aborted."
                    ),
                    severity=Severity.LOW,
                    category=Category.NETWORK_STORAGE,
                    service="S3",
                    region=self.region,
                    resource_id=name,
                    estimated_monthly_savings_usd=0.0,
                    recommendation=(
                        "Add a lifecycle rule: AbortIncompleteMultipartUpload after 7 days. "
                        f"Or run: aws s3api abort-multipart-upload for each upload in metadata."
                    ),
                    metadata={
                        "bucket_name": name,
                        "stale_upload_count": len(stale_uploads),
                        "stale_uploads": stale_uploads[:10],
                        "lifecycle_rule_suggestion": {
                            "ID": "FinOps-AbortIncompleteMultipartUpload",
                            "Status": "Enabled",
                            "Filter": {},
                            "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 7},
                        },
                    },
                ))

        return findings


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _bucket_has_lifecycle(s3_client, bucket_name: str) -> bool:
    try:
        s3_client.get_bucket_lifecycle_configuration(Bucket=bucket_name)
        return True
    except s3_client.exceptions.from_code("NoSuchLifecycleConfiguration"):
        return False
    except Exception:
        return False   # permission denied etc. — treat as unknown, skip


def _bucket_versioning_enabled(s3_client, bucket_name: str) -> bool:
    try:
        resp = s3_client.get_bucket_versioning(Bucket=bucket_name)
        return resp.get("Status") == "Enabled"
    except Exception:
        return False


def _stale_multipart_uploads(
    s3_client,
    bucket_name: str,
    cutoff: datetime,
) -> list[dict]:
    stale: list[dict] = []
    try:
        paginator = s3_client.get_paginator("list_multipart_uploads")
        for page in paginator.paginate(Bucket=bucket_name):
            for upload in page.get("Uploads", []):
                initiated = upload.get("Initiated")
                if not initiated:
                    continue
                init_dt = initiated if initiated.tzinfo else initiated.replace(tzinfo=timezone.utc)
                if init_dt < cutoff:
                    stale.append({
                        "key": upload.get("Key", ""),
                        "upload_id": upload.get("UploadId", ""),
                        "initiated": str(initiated),
                    })
    except Exception:
        pass
    return stale


def _build_gir_lifecycle_config(bucket_name: str) -> dict:
    """
    Build the S3 Lifecycle Configuration JSON matching the spec:
      - Rule 1: Objects < 1 MB  → Standard-IA after 30 days
      - Rule 2: Objects >= 1 MB → Glacier Instant Retrieval after 30 days
      - Intelligent-Tiering enabled via separate bucket configuration call

    Note: S3 lifecycle rules cannot filter by object size for Standard→IA transitions
    directly; size filtering is available for Intelligent-Tiering storage class analysis.
    The recommended approach is to enable S3 Intelligent-Tiering which automatically
    handles the tiering decision per object.
    """
    return {
        "Rules": [
            {
                "ID":     "FinOps-StandardIA-SmallObjects",
                "Status": "Enabled",
                "Filter": {
                    "ObjectSizeGreaterThan": 0,
                    "ObjectSizeLessThan":    S3_SMALL_OBJECT_BYTES,
                },
                "Transitions": [
                    {
                        "Days":         S3_GIR_TRANSITION_DAYS,
                        "StorageClass": "STANDARD_IA",
                    }
                ],
            },
            {
                "ID":     "FinOps-GIR-LargeObjects",
                "Status": "Enabled",
                "Filter": {
                    "ObjectSizeGreaterThan": S3_SMALL_OBJECT_BYTES,
                },
                "Transitions": [
                    {
                        "Days":         S3_GIR_TRANSITION_DAYS,
                        "StorageClass": "GLACIER_IR",
                    }
                ],
            },
            {
                "ID":     "FinOps-IntelligentTiering",
                "Status": "Enabled",
                "Filter": {},
                "Transitions": [
                    {
                        "Days":         0,
                        "StorageClass": "INTELLIGENT_TIERING",
                    }
                ],
            },
        ],
        "_note": (
            "Apply with: aws s3api put-bucket-lifecycle-configuration "
            f"--bucket {bucket_name} --lifecycle-configuration file://this-file.json"
        ),
    }
