"""
Pillar B — Module 4: Database Tuning (audit_db.py)

Goal: Stop non-prod billing leakage over weekends and nights.

Tasks:
  4.1  Non-prod RDS identification by tags and identifier keywords
  4.2  Weekend stop/start automation blueprint JSON + savings calculation

All AWS API calls use boto3 paginators.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import boto3

from shared.findings_schema import Category, Finding, Severity
from shared.cw_helper import batch_metric_averages

# Tag keys and identifier substrings that mark non-production databases
NON_PROD_ENV_KEYS     = {"environment", "env", "stage", "tier"}
NON_PROD_ENV_VALUES   = {"dev", "development", "staging", "stage", "qa", "test", "testing", "sandbox"}
NON_PROD_ID_KEYWORDS  = {"dev", "develop", "stg", "staging", "qa", "test", "sandbox"}

# Weekend schedule (UTC): stop Friday 20:00, start Monday 08:00
WEEKEND_STOP_CRON  = "cron(0 20 ? * FRI *)"
WEEKEND_START_CRON = "cron(0 8 ? * MON *)"
WEEKEND_STOPPED_HOURS = 60   # Fri 20:00 → Mon 08:00 = 60 hours
WEEKS_PER_MONTH       = 4

# Approximate on-demand hourly prices for common RDS instance types (us-east-1, Single-AZ)
# Updated periodically; for production use call pricing.get_products() instead.
RDS_HOURLY_PRICE_USD: dict[str, float] = {
    "db.t3.micro":    0.017,
    "db.t3.small":    0.034,
    "db.t3.medium":   0.068,
    "db.t3.large":    0.136,
    "db.t3.xlarge":   0.272,
    "db.t3.2xlarge":  0.544,
    "db.t4g.micro":   0.016,
    "db.t4g.small":   0.032,
    "db.t4g.medium":  0.065,
    "db.t4g.large":   0.130,
    "db.m5.large":    0.171,
    "db.m5.xlarge":   0.342,
    "db.m5.2xlarge":  0.684,
    "db.m5.4xlarge":  1.368,
    "db.m6g.large":   0.156,
    "db.m6g.xlarge":  0.312,
    "db.m6g.2xlarge": 0.624,
    "db.r5.large":    0.240,
    "db.r5.xlarge":   0.480,
    "db.r5.2xlarge":  0.960,
    "db.r6g.large":   0.216,
    "db.r6g.xlarge":  0.432,
}
DEFAULT_HOURLY_PRICE = 0.10   # conservative fallback when type not in table

DB_IDLE_CONNECTIONS_THRESHOLD = 1.0
DB_LOOKBACK_DAYS = 14


class DatabaseTuningModule:
    def __init__(self, session: boto3.Session, regions: list[str] | None = None,
                 teaser: bool = False, covered_resource_ids: set[str] | None = None) -> None:
        self.session = session
        self.region  = session.region_name
        self.regions = regions or [self.region]
        self.teaser  = teaser
        self.covered_resource_ids = {r.lower().strip() for r in (covered_resource_ids or set())}

    def run(self) -> list[Finding]:
        findings: list[Finding] = []
        findings.extend(self._check_nonprod_rds())
        if not self.teaser:
            findings.extend(self._check_idle_rds_instances())
        findings.extend(self._check_single_az_production_dbs())
        return findings

    # ------------------------------------------------------------------
    # Task 4.1 + 4.2 — Non-prod RDS identification + weekend blueprint
    # ------------------------------------------------------------------

    def _check_nonprod_rds(self) -> list[Finding]:
        findings: list[Finding] = []
        for region in self.regions:
            rds = self.session.client("rds", region_name=region)
            for page in rds.get_paginator("describe_db_instances").paginate():
                for db in page["DBInstances"]:
                    if db["DBInstanceStatus"] != "available":
                        continue
                    if db.get("MultiAZ", False):
                        continue
                    db_id  = db["DBInstanceIdentifier"]
                    db_arn = db["DBInstanceArn"]
                    tags_raw = rds.list_tags_for_resource(ResourceName=db_arn)["TagList"]
                    tags = {t["Key"].lower(): t["Value"].lower() for t in tags_raw}
                    if not (_is_nonprod_by_tags(tags) or _is_nonprod_by_identifier(db_id)):
                        continue
                    instance_class  = db["DBInstanceClass"]
                    hourly_price    = RDS_HOURLY_PRICE_USD.get(instance_class, DEFAULT_HOURLY_PRICE)
                    monthly_savings = round(hourly_price * WEEKEND_STOPPED_HOURS * WEEKS_PER_MONTH, 2)
                    findings.append(Finding(
                        id=f"DB-NONPROD-{db_id}",
                        title=f"Non-prod RDS '{db_id}' — weekend stop/start candidate",
                        description=(
                            f"RDS instance {db_id} ({instance_class}, {db['Engine']}, {region}) "
                            f"identified as non-production (Multi-AZ=False + env tags/identifier). "
                            f"Weekend stop (Fri 20:00 → Mon 08:00 UTC) saves ~${monthly_savings:.2f}/month."
                        ),
                        severity=Severity.HIGH,
                        category=Category.DATABASE_TUNING,
                        service="RDS",
                        region=region,
                        resource_id=db_id,
                        estimated_monthly_savings_usd=monthly_savings,
                        recommendation=(
                            "Deploy the weekend_automation_blueprint in metadata as an "
                            "EventBridge + Lambda schedule. Storage costs excluded from savings."
                        ),
                        metadata={
                            "db_instance_id":   db_id,
                            "db_instance_arn":  db_arn,
                            "instance_class":   instance_class,
                            "engine":           db["Engine"],
                            "engine_version":   db.get("EngineVersion", ""),
                            "multi_az":         False,
                            "matched_env_tags": {k: v for k, v in tags.items() if k in NON_PROD_ENV_KEYS},
                            "weekend_automation_blueprint": _build_weekend_blueprint(db_arn, db_id, instance_class, hourly_price),
                        },
                    ))
        return findings

    # ------------------------------------------------------------------
    # Idle RDS (connection-count check)
    # ------------------------------------------------------------------

    def _check_idle_rds_instances(self) -> list[Finding]:
        findings: list[Finding] = []
        end   = datetime.now(timezone.utc)
        start = end - timedelta(days=DB_LOOKBACK_DAYS)
        for region in self.regions:
            rds = self.session.client("rds", region_name=region)
            cw  = self.session.client("cloudwatch", region_name=region)

            # Collect all available instances first, then batch-query CloudWatch.
            dbs: list[dict] = []
            for page in rds.get_paginator("describe_db_instances").paginate():
                for db in page["DBInstances"]:
                    if db["DBInstanceStatus"] == "available":
                        dbs.append(db)

            dbs = [
                db for db in dbs
                if db["DBInstanceIdentifier"].lower() not in self.covered_resource_ids
            ]

            if not dbs:
                continue

            avg_conn_by_id = batch_metric_averages(
                cw, "AWS/RDS", "DatabaseConnections", "DBInstanceIdentifier",
                [db["DBInstanceIdentifier"] for db in dbs],
                start, end,
            )

            for db in dbs:
                db_id    = db["DBInstanceIdentifier"]
                avg_conn = avg_conn_by_id.get(db_id)
                if avg_conn is None:
                    continue
                if avg_conn < DB_IDLE_CONNECTIONS_THRESHOLD:
                    findings.append(Finding(
                        id=f"DB-IDLE-{db_id}",
                        title=f"Idle RDS instance — {db_id}",
                        description=(
                            f"RDS instance {db_id} ({db['DBInstanceClass']}, {db['Engine']}, {region}) "
                            f"averaged {avg_conn:.2f} connections over {DB_LOOKBACK_DAYS} days."
                        ),
                        severity=Severity.HIGH,
                        category=Category.DATABASE_TUNING,
                        service="RDS",
                        region=region,
                        resource_id=db_id,
                        estimated_monthly_savings_usd=0.0,
                        recommendation="Stop or delete if not actively used. Consider Aurora Serverless v2 for intermittent workloads.",
                        metadata={
                            "instance_class":  db["DBInstanceClass"],
                            "engine":          db["Engine"],
                            "avg_connections": round(avg_conn, 2),
                            "lookback_days":   DB_LOOKBACK_DAYS,
                        },
                    ))
        return findings

    # ------------------------------------------------------------------
    # Single-AZ production databases
    # ------------------------------------------------------------------

    def _check_single_az_production_dbs(self) -> list[Finding]:
        """Flag prod-tagged RDS instances without Multi-AZ — reliability risk, not a cost saving."""
        findings: list[Finding] = []
        for region in self.regions:
            rds = self.session.client("rds", region_name=region)
            for page in rds.get_paginator("describe_db_instances").paginate():
                for db in page["DBInstances"]:
                    if db["DBInstanceStatus"] != "available":
                        continue
                    if db.get("MultiAZ", False):
                        continue
                    db_id  = db["DBInstanceIdentifier"]
                    db_arn = db["DBInstanceArn"]
                    tags   = {
                        t["Key"].lower(): t["Value"].lower()
                        for t in rds.list_tags_for_resource(ResourceName=db_arn)["TagList"]
                    }
                    env_val = tags.get("environment", tags.get("env", ""))
                    if env_val in ("prod", "production"):
                        findings.append(Finding(
                            id=f"DB-SINGLEAZ-{db_id}",
                            title=f"Production RDS without Multi-AZ — {db_id}",
                            description=(
                                f"RDS instance {db_id} ({db['DBInstanceClass']}, {region}) is tagged "
                                f"Environment={env_val} but has Multi-AZ disabled — single point of failure."
                            ),
                            severity=Severity.CRITICAL,
                            category=Category.DATABASE_TUNING,
                            service="RDS",
                            region=region,
                            resource_id=db_id,
                            estimated_monthly_savings_usd=0.0,
                            recommendation="Enable Multi-AZ for production RDS to meet availability SLAs.",
                            metadata={
                                "instance_class": db["DBInstanceClass"],
                                "engine":         db["Engine"],
                                "env_tag":        env_val,
                            },
                        ))
        return findings


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _is_nonprod_by_tags(tags: dict[str, str]) -> bool:
    for key in NON_PROD_ENV_KEYS:
        value = tags.get(key, "")
        if any(kw in value for kw in NON_PROD_ENV_VALUES):
            return True
    return False


def _is_nonprod_by_identifier(db_id: str) -> bool:
    db_lower = db_id.lower()
    return any(kw in db_lower for kw in NON_PROD_ID_KEYWORDS)


def _build_weekend_blueprint(
    db_arn: str,
    db_id:  str,
    instance_class: str,
    hourly_price: float,
) -> dict:
    """
    Task 4.2 — Generate the EventBridge + Lambda automation blueprint.

    Savings calculation per spec:
      (Instance Hourly Price × 60 hours stopped per weekend) × 4 weeks/month
      Storage costs are excluded (billed regardless of state).
    """
    monthly_savings = round(hourly_price * WEEKEND_STOPPED_HOURS * WEEKS_PER_MONTH, 2)
    annual_savings  = round(monthly_savings * 12, 2)

    return {
        "description": (
            "EventBridge + Lambda automation to stop this RDS instance on Friday evenings "
            "and restart it Monday mornings, eliminating weekend compute charges."
        ),
        "target_rds_arns": [db_arn],
        "target_rds_ids":  [db_id],
        "schedules": {
            "stop":  {
                "cron":        WEEKEND_STOP_CRON,
                "description": "Stop instance — Friday 20:00 UTC",
                "action":      "rds:StopDBInstance",
            },
            "start": {
                "cron":        WEEKEND_START_CRON,
                "description": "Start instance — Monday 08:00 UTC",
                "action":      "rds:StartDBInstance",
            },
        },
        "savings_calculation": {
            "instance_class":              instance_class,
            "hourly_price_usd":            hourly_price,
            "hours_stopped_per_weekend":   WEEKEND_STOPPED_HOURS,
            "weekends_per_month":          WEEKS_PER_MONTH,
            "estimated_monthly_savings_usd": monthly_savings,
            "estimated_annual_savings_usd":  annual_savings,
            "note": (
                "Storage costs (EBS, provisioned IOPS) are excluded — "
                "they are billed regardless of whether the instance is running."
            ),
        },
        "lambda_policy_required": {
            "Effect":   "Allow",
            "Action":   ["rds:StopDBInstance", "rds:StartDBInstance"],
            "Resource": [db_arn],
        },
        "deployment_hint": (
            "Deploy via CloudFormation or Terraform using AWS::Events::Rule "
            "with a ScheduleExpression and an AWS::Lambda::Function target."
        ),
    }
