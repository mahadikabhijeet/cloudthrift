"""
pillar-b/engine/mock_data.py — Synthetic audit findings for smoke testing.

Generates a realistic AuditReport without any AWS credentials.
Covers original modules plus Sprint 1–2 checks (TA/CO/COH-style ingest,
idle NAT, VPC endpoints, S3 hygiene, ECR, CloudWatch logs, RI expiry).

Usage:
    python pillar-b/engine/main.py --mock --account-id demo-account
"""
from __future__ import annotations

from datetime import datetime, timezone

from shared.findings_schema import AuditReport, Category, Finding, Severity


def generate_mock_report(account_id: str, region: str = "us-east-1") -> AuditReport:
    report = AuditReport(
        account_id=account_id,
        account_name="Acme Corp (MOCK)",
        generated_at=datetime.now(timezone.utc),
    )
    report.findings = _mock_findings(region)
    return report


def _mock_findings(region: str) -> list[Finding]:
    return [
        # ── Module 1: Infrastructure Hygiene ──────────────────────────
        Finding(
            id="HYGIENE-EBS-vol-0abc1234",
            title="Unattached EBS volume (safe to delete)",
            description=(
                "Volume vol-0abc1234 (500 GiB gp2) has been unattached for 47 days. "
                "CloudTrail found no DetachVolume event in the last 30 days."
            ),
            severity=Severity.HIGH,
            category=Category.INFRA_HYGIENE,
            service="EC2/EBS",
            region=region,
            resource_id="vol-0abc1234",
            estimated_monthly_savings_usd=50.00,
            recommendation="Snapshot then delete this volume.",
            metadata={
                "volume_id": "vol-0abc1234", "size_gib": 500,
                "volume_type": "gp2", "safe_to_delete": True,
                "recent_detach_in_cloudtrail": False,
            },
        ),
        Finding(
            id="HYGIENE-GP2-vol-0def5678",
            title="gp2 EBS volume — migrate to gp3 for 20% savings",
            description=(
                "Volume vol-0def5678 (1000 GiB) uses the legacy gp2 type. "
                "Migrating to gp3 saves $20.00/month with no performance regression."
            ),
            severity=Severity.LOW,
            category=Category.INFRA_HYGIENE,
            service="EC2/EBS",
            region=region,
            resource_id="vol-0def5678",
            estimated_monthly_savings_usd=20.00,
            recommendation="Run: aws ec2 modify-volume --volume-type gp3 --volume-id vol-0def5678",
            metadata={
                "volume_id": "vol-0def5678", "size_gib": 1000,
                "current_type": "gp2", "recommended_type": "gp3",
                "current_attached_instance_ids": ["i-0aaa111bbb222"],
                "estimated_monthly_savings_usd": 20.00,
            },
        ),
        Finding(
            id="HYGIENE-SNAP-snap-0deadbeef",
            title="Orphaned EBS snapshot (aged 134 days)",
            description=(
                "Snapshot snap-0deadbeef (200 GiB) is 134 days old, "
                "not associated with any AMI, and has no exclusion tags."
            ),
            severity=Severity.LOW,
            category=Category.INFRA_HYGIENE,
            service="EC2/EBS",
            region=region,
            resource_id="snap-0deadbeef",
            estimated_monthly_savings_usd=10.00,
            recommendation="Review and delete if no longer needed for disaster-recovery.",
            metadata={"snapshot_id": "snap-0deadbeef", "size_gib": 200, "age_days": 134},
        ),
        Finding(
            id="HYGIENE-EIP-eipalloc-0abc999",
            title="Unassociated Elastic IP",
            description="Elastic IP 54.123.45.67 is not associated with any resource.",
            severity=Severity.LOW,
            category=Category.INFRA_HYGIENE,
            service="EC2",
            region=region,
            resource_id="eipalloc-0abc999",
            estimated_monthly_savings_usd=3.65,
            recommendation="Release this Elastic IP if it is no longer required.",
            metadata={"public_ip": "54.123.45.67", "allocation_id": "eipalloc-0abc999"},
        ),
        Finding(
            id="HYGIENE-ELB-legacy-api-lb",
            title="Load balancer with no healthy targets",
            description=(
                "Load balancer legacy-api-lb (application) has no healthy registered "
                "targets but incurs ~$16/month."
            ),
            severity=Severity.HIGH,
            category=Category.INFRA_HYGIENE,
            service="ELB",
            region=region,
            resource_id="arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/legacy-api-lb/abc",
            estimated_monthly_savings_usd=16.20,
            recommendation="Delete the load balancer or register and health-check targets.",
            metadata={"lb_name": "legacy-api-lb", "lb_type": "application", "scheme": "internet-facing"},
        ),

        # ── Module 2: Compute Strategy ────────────────────────────────
        Finding(
            id="COMPUTE-ASG-SPOT-web-api-asg",
            title="ASG 'web-api-asg' running 100% On-Demand — Spot Fleet candidate",
            description=(
                "Auto Scaling Group 'web-api-asg' has 8 On-Demand instances behind "
                "an ALB with no stateful tags. Switching to Spot could reduce compute costs by 60–80%."
            ),
            severity=Severity.HIGH,
            category=Category.COMPUTE_STRATEGY,
            service="EC2/ASG",
            region=region,
            resource_id="web-api-asg",
            estimated_monthly_savings_usd=0.0,
            recommendation="Apply the spot_fleet_recommendation in metadata to the ASG MixedInstancesPolicy.",
            metadata={
                "asg_name": "web-api-asg",
                "on_demand_instance_count": 8,
                "current_instance_types": ["m5.xlarge"],
                "spot_fleet_recommendation": {
                    "AllocationStrategy": "capacity-optimized",
                    "OnDemandBaseCapacity": 1,
                    "OnDemandPercentageAboveBaseCapacity": 0,
                    "InstanceOverrides": [{"InstanceType": "m5.xlarge"}, {"InstanceType": "m6g.xlarge"}],
                    "SpotInterruptionHandling": {
                        "approach": "EventBridge rule for EC2 Spot Instance Interruption Notice",
                        "notice_window_minutes": 2,
                        "recommended_actions": [
                            "Publish EventBridge rule: source=aws.ec2, detail-type=EC2 Spot Instance Interruption Warning",
                            "Lambda target: call ELB DeregisterTargets for the interrupted instance",
                        ],
                    },
                },
            },
        ),
        Finding(
            id="COMPUTE-IDLE-i-0fff000aaa",
            title="Idle EC2 instance",
            description="Instance i-0fff000aaa (m5.2xlarge) averaged 1.3% CPU over 14 days.",
            severity=Severity.HIGH,
            category=Category.COMPUTE_STRATEGY,
            service="EC2",
            region=region,
            resource_id="i-0fff000aaa",
            estimated_monthly_savings_usd=0.0,
            recommendation="Right-size to a smaller instance type or terminate if unused.",
            metadata={"instance_type": "m5.2xlarge", "avg_cpu_pct": 1.3, "lookback_days": 14},
        ),
        Finding(
            id="COMPUTE-STOPPED-i-0bbb222ccc",
            title="Stopped EC2 instance with attached EBS storage",
            description="Instance i-0bbb222ccc (c5.4xlarge) is stopped but its EBS volumes are still billing.",
            severity=Severity.MEDIUM,
            category=Category.COMPUTE_STRATEGY,
            service="EC2",
            region=region,
            resource_id="i-0bbb222ccc",
            estimated_monthly_savings_usd=0.0,
            recommendation="Snapshot the root volume and terminate, or restart if actively needed.",
            metadata={"instance_type": "c5.4xlarge"},
        ),
        Finding(
            id="COMPUTE-GRAVITON-i-0ddd333eee",
            title="Graviton upgrade opportunity (~20% better price-performance)",
            description="Instance i-0ddd333eee runs m5.large (x86). Equivalent m6g.large offers ~20% lower cost.",
            severity=Severity.LOW,
            category=Category.COMPUTE_STRATEGY,
            service="EC2",
            region=region,
            resource_id="i-0ddd333eee",
            estimated_monthly_savings_usd=0.0,
            recommendation="Test workload on m6g.large and migrate.",
            metadata={"current_type": "m5.large", "recommended_type": "m6g.large"},
        ),

        # ── Module 3: Network & Storage ───────────────────────────────
        Finding(
            id="NETWORK-NAT-BLEED-us-east-1",
            title="NAT Gateway data-processing charges detected",
            description=(
                "NAT Gateway data-processing cost: $312.40 in the last 30 days (~$312.40/month). "
                "Likely cause: EC2 instances pulling container images via NAT instead of VPC Endpoints."
            ),
            severity=Severity.HIGH,
            category=Category.NETWORK_STORAGE,
            service="VPC/NAT",
            region=region,
            resource_id="nat-gateway-us-east-1",
            estimated_monthly_savings_usd=187.44,
            recommendation="Add VPC Interface Endpoints for ECR, S3, and Secrets Manager.",
            metadata={
                "cost_last_30d_usd": 312.40,
                "estimated_monthly_usd": 312.40,
                "recommended_action": "Add VPC Endpoints for S3, ECR, Secrets Manager",
            },
        ),
        Finding(
            id="NETWORK-INTERAZ-us-east-1",
            title="Inter-AZ data transfer charges — flag for architectural review",
            description=(
                "Inter-AZ data transfer: $1,840.00 in the last 30 days (~$1,840.00/month). "
                "EXCEEDS $500/month threshold — recommend architectural review."
            ),
            severity=Severity.CRITICAL,
            category=Category.NETWORK_STORAGE,
            service="VPC",
            region=region,
            resource_id="inter-az-transfer-us-east-1",
            estimated_monthly_savings_usd=920.00,
            recommendation=(
                "Co-locate services in the same AZ. Use ElastiCache to reduce cross-AZ DB reads. "
                "Escalate to architecture review — spend exceeds $500/month."
            ),
            metadata={
                "cost_last_30d_usd": 1840.00,
                "estimated_monthly_usd": 1840.00,
                "exceeds_alert_threshold": True,
                "alert_threshold_usd": 500.0,
                "recommended_action": "architectural_review",
            },
        ),
        Finding(
            id="STORAGE-S3-TIERING-acme-app-data",
            title="S3 bucket 'acme-app-data' missing tiering lifecycle policy",
            description=(
                "Bucket 'acme-app-data' has no lifecycle rules. Objects accumulate indefinitely "
                "in Standard storage. Applying Intelligent-Tiering + GIR could reduce costs by 40–68%."
            ),
            severity=Severity.MEDIUM,
            category=Category.NETWORK_STORAGE,
            service="S3",
            region=region,
            resource_id="acme-app-data",
            estimated_monthly_savings_usd=0.0,
            recommendation="Apply the lifecycle_configuration in metadata.",
            metadata={
                "bucket_name": "acme-app-data",
                "has_lifecycle_policy": False,
                "tiering_strategy": {
                    "small_objects_lt_1mb": "S3 Standard-IA after 30 days",
                    "large_objects_gte_1mb": "S3 Glacier Instant Retrieval after 30 days",
                    "intelligent_tiering": "Enable on bucket for automatic optimisation",
                },
            },
        ),

        # ── Module 4: Database Tuning ─────────────────────────────────
        Finding(
            id="DB-NONPROD-acme-staging-db",
            title="Non-prod RDS instance 'acme-staging-db' — weekend stop/start candidate",
            description=(
                "RDS instance acme-staging-db (db.m5.xlarge, postgres) appears non-production "
                "(Multi-AZ=False, Environment=staging tag). Stopping over weekends saves ~$136.80/month."
            ),
            severity=Severity.HIGH,
            category=Category.DATABASE_TUNING,
            service="RDS",
            region=region,
            resource_id="acme-staging-db",
            estimated_monthly_savings_usd=136.80,
            recommendation="Deploy the weekend_automation_blueprint in metadata.",
            metadata={
                "db_instance_id": "acme-staging-db",
                "instance_class": "db.m5.xlarge",
                "engine": "postgres",
                "multi_az": False,
                "matched_env_tags": {"environment": "staging"},
                "hourly_price_usd": 0.342,
                "weekend_stopped_hours": 60,
                "estimated_monthly_savings_usd": 136.80,
                "weekend_automation_blueprint": {
                    "AllocationStrategy": "N/A",
                    "schedules": {
                        "stop":  {"cron": "cron(0 20 ? * FRI *)", "description": "Stop — Friday 20:00 UTC"},
                        "start": {"cron": "cron(0 8 ? * MON *)",  "description": "Start — Monday 08:00 UTC"},
                    },
                    "savings_calculation": {
                        "hourly_price_usd": 0.342,
                        "hours_stopped_per_weekend": 60,
                        "weekends_per_month": 4,
                        "estimated_monthly_savings_usd": 136.80,
                        "estimated_annual_savings_usd": 1641.60,
                        "note": "Storage costs excluded — billed regardless of instance state.",
                    },
                },
            },
        ),
        Finding(
            id="DB-IDLE-acme-dev-mysql",
            title="Idle RDS instance",
            description="RDS instance acme-dev-mysql (db.t3.large, mysql) averaged 0.1 connections over 14 days.",
            severity=Severity.HIGH,
            category=Category.DATABASE_TUNING,
            service="RDS",
            region=region,
            resource_id="acme-dev-mysql",
            estimated_monthly_savings_usd=0.0,
            recommendation="Stop or delete. Consider Aurora Serverless v2 for intermittent workloads.",
            metadata={"instance_class": "db.t3.large", "engine": "mysql", "avg_connections": 0.1},
        ),
        Finding(
            id="DB-SINGLEAZ-acme-prod-pg",
            title="Production RDS instance without Multi-AZ",
            description="RDS instance acme-prod-pg is tagged Environment=prod but has Multi-AZ disabled.",
            severity=Severity.CRITICAL,
            category=Category.DATABASE_TUNING,
            service="RDS",
            region=region,
            resource_id="acme-prod-pg",
            estimated_monthly_savings_usd=0.0,
            recommendation="Enable Multi-AZ for production RDS to meet availability SLAs.",
            metadata={"instance_class": "db.r5.2xlarge", "engine": "postgres", "env_tag": "prod"},
        ),

        # ── Sprint 1: AWS-native recommendations (ingest-style) ───────
        Finding(
            id="TA-Qch7DwouX1-vol-0ghost111",
            title="Trusted Advisor: Underutilized Amazon EBS Volumes",
            description="AWS Trusted Advisor flagged vol-0ghost111 under check 'Underutilized Amazon EBS Volumes'. Status: warning.",
            severity=Severity.MEDIUM,
            category=Category.INFRA_HYGIENE,
            service="EC2/EBS",
            region=region,
            resource_id="vol-0ghost111",
            estimated_monthly_savings_usd=24.00,
            recommendation="Review Trusted Advisor check 'Underutilized Amazon EBS Volumes' and remediate vol-0ghost111.",
            metadata={
                "source": "trusted_advisor",
                "ta_check_id": "Qch7DwouX1",
                "ta_check_name": "Underutilized Amazon EBS Volumes",
                "ta_status": "warning",
            },
        ),
        Finding(
            id="CO-EC2-i-0underutil99",
            title="Compute Optimizer: rightsizing i-0underutil99 (m5.xlarge → m5.large)",
            description="Compute Optimizer recommends underprovisioned for i-0underutil99 (currently m5.xlarge). Estimated savings: $85.00/month.",
            severity=Severity.MEDIUM,
            category=Category.COMPUTE_STRATEGY,
            service="EC2",
            region=region,
            resource_id="i-0underutil99",
            estimated_monthly_savings_usd=85.00,
            recommendation="Validate workload metrics for i-0underutil99, then apply rightsizing to m5.large.",
            metadata={
                "source": "compute_optimizer",
                "finding": "Underprovisioned",
                "current_instance_type": "m5.xlarge",
                "recommended_instance_type": "m5.large",
            },
        ),
        Finding(
            id="COH-i-0underutil99-Rightsize",
            title="Cost Optimization Hub: Rightsize i-0underutil99",
            description="Cost Optimization Hub recommends Rightsize for i-0underutil99.",
            severity=Severity.MEDIUM,
            category=Category.COMPUTE_STRATEGY,
            service="Ec2Instance",
            region=region,
            resource_id="i-0underutil99",
            estimated_monthly_savings_usd=85.00,
            recommendation="Implement Cost Optimization Hub recommendation: Rightsize.",
            metadata={
                "source": "cost_optimization_hub",
                "coh_recommendation_id": "coh-mock-001",
                "action_type": "Rightsize",
            },
        ),

        # ── Sprint 2: Custom cost checks ──────────────────────────────
        Finding(
            id="NETWORK-NAT-IDLE-nat-0idle12345",
            title="Idle NAT Gateway nat-0idle12345",
            description="NAT Gateway nat-0idle12345 processed no traffic in the last 7 days but incurs ~$32.40/month.",
            severity=Severity.HIGH,
            category=Category.NETWORK_STORAGE,
            service="VPC/NAT",
            region=region,
            resource_id="nat-0idle12345",
            estimated_monthly_savings_usd=32.40,
            recommendation="Delete this NAT Gateway if no private subnets route through it.",
            metadata={"nat_gateway_id": "nat-0idle12345", "lookback_days": 7, "bytes_processed": 0},
        ),
        Finding(
            id="NETWORK-VPCE-IDLE-vpce-0abc98765",
            title="Inactive VPC interface endpoint vpce-0abc98765",
            description="Interface endpoint vpce-0abc98765 (com.amazonaws.us-east-1.ecr.api) processed no traffic in 14 days.",
            severity=Severity.MEDIUM,
            category=Category.NETWORK_STORAGE,
            service="VPC/PrivateLink",
            region=region,
            resource_id="vpce-0abc98765",
            estimated_monthly_savings_usd=14.40,
            recommendation="Delete endpoint vpce-0abc98765 if ECR is no longer accessed from this VPC.",
            metadata={"vpc_endpoint_id": "vpce-0abc98765", "service_name": "com.amazonaws.us-east-1.ecr.api"},
        ),
        Finding(
            id="STORAGE-S3-MULTIPART-acme-uploads",
            title="S3 bucket 'acme-uploads' has stale incomplete multipart uploads",
            description="Bucket 'acme-uploads' has 3 multipart upload(s) older than 7 days.",
            severity=Severity.LOW,
            category=Category.NETWORK_STORAGE,
            service="S3",
            region=region,
            resource_id="acme-uploads",
            estimated_monthly_savings_usd=0.0,
            recommendation="Add AbortIncompleteMultipartUpload lifecycle rule after 7 days.",
            metadata={"bucket_name": "acme-uploads", "stale_upload_count": 3},
        ),
        Finding(
            id="STORAGE-S3-VERSIONING-acme-backups",
            title="S3 bucket 'acme-backups' has versioning without lifecycle",
            description="Bucket 'acme-backups' has versioning enabled but no lifecycle policy.",
            severity=Severity.MEDIUM,
            category=Category.NETWORK_STORAGE,
            service="S3",
            region=region,
            resource_id="acme-backups",
            estimated_monthly_savings_usd=0.0,
            recommendation="Expire noncurrent versions after 90 days.",
            metadata={"bucket_name": "acme-backups", "versioning_enabled": True},
        ),
        Finding(
            id="HYGIENE-ECR-web-api",
            title="ECR repository 'web-api' has no lifecycle policy",
            description="ECR repository 'web-api' has no lifecycle policy. Old images accumulate storage charges.",
            severity=Severity.LOW,
            category=Category.INFRA_HYGIENE,
            service="ECR",
            region=region,
            resource_id="web-api",
            estimated_monthly_savings_usd=0.0,
            recommendation="Expire untagged images after 7 days.",
            metadata={"repository_name": "web-api"},
        ),
        Finding(
            id="OBS-LOGS-/aws/lambda/api-handler",
            title="CloudWatch log group '/aws/lambda/api-handler' has infinite retention",
            description="Log group '/aws/lambda/api-handler' has no retention policy (4.2 GiB stored).",
            severity=Severity.MEDIUM,
            category=Category.NETWORK_STORAGE,
            service="CloudWatch Logs",
            region=region,
            resource_id="/aws/lambda/api-handler",
            estimated_monthly_savings_usd=12.60,
            recommendation="Set retention to 30 days.",
            metadata={"log_group_name": "/aws/lambda/api-handler", "stored_gib": 4.2},
        ),
        Finding(
            id="SP-RI-EXPIRE-ri-0abc123456789",
            title="EC2 Reserved Instance expiring in 21 days",
            description="Reserved Instance ri-0abc123456789 (2x m5.large) expires in 21 days.",
            severity=Severity.HIGH,
            category=Category.SAVINGS_PLANS,
            service="EC2",
            region=region,
            resource_id="ri-0abc123456789",
            estimated_monthly_savings_usd=0.0,
            recommendation="Renew the RI or migrate to a Savings Plan before expiry.",
            metadata={"reserved_instance_id": "ri-0abc123456789", "days_until_expiry": 21},
        ),
    ]
