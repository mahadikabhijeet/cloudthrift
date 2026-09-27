"""
Pillar B -- Module 5: Savings Plans & Reserved Instance Coverage

Goal: Identify gaps in Savings Plans and RI coverage to reduce on-demand spend.

Tasks:
  5.1  Savings Plans coverage (Compute SP — covers EC2, Lambda, Fargate)
  5.2  Reserved Instance coverage: RDS, ElastiCache, Redshift, OpenSearch
  5.3  DynamoDB reserved capacity opportunity
  5.4  EC2 rightsizing recommendations via Cost Explorer

All calls use the Cost Explorer API (always us-east-1).
CE is only accessible from payer/billing accounts -- errors are caught gracefully.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import boto3

from shared.aws_client import scope_ce_filter
from shared.findings_schema import Category, Finding, Severity

CE_LOOKBACK_DAYS = 30

SP_COVERAGE_THRESHOLD_PCT = 70.0
SP_MIN_ON_DEMAND_USD      = 200.0
SP_AVG_DISCOUNT_PCT       = 0.28   # 28% average Compute SP discount

RI_COVERAGE_THRESHOLD_PCT = 60.0
RI_MIN_ON_DEMAND_USD      = 100.0

# Per-service 1-year no-upfront RI discount approximations
RI_DISCOUNT_BY_SERVICE: dict[str, float] = {
    "Amazon Relational Database Service": 0.35,
    "Amazon ElastiCache":                 0.32,
    "Amazon Redshift":                    0.38,
    "Amazon OpenSearch Service":          0.32,
    "Amazon Elasticsearch Service":       0.32,   # legacy name pre-2021 rename
}
RI_DEFAULT_DISCOUNT = 0.30   # fallback for any unlisted service

MAX_RIGHTSIZING_FINDINGS = 20

# Services that support Reserved Instances via get_reservation_coverage
# OpenSearch accounts created before Nov 2021 still report as "Elasticsearch Service"
RI_SERVICES = [
    "Amazon Relational Database Service",
    "Amazon ElastiCache",
    "Amazon Redshift",
    "Amazon OpenSearch Service",
    "Amazon Elasticsearch Service",
]

# DynamoDB: reserved capacity is not tracked by get_reservation_coverage;
# checked separately via total spend.
DYNAMODB_MONTHLY_THRESHOLD_USD = 100.0
DYNAMODB_RESERVED_DISCOUNT_PCT = 0.30   # ~30% for 1-year reserved capacity

# Flag EC2 RIs expiring within this window (days)
EC2_RI_EXPIRY_WARNING_DAYS = 60


class SavingsPlansModule:
    def __init__(self, session: boto3.Session, regions: list[str] | None = None,
                 teaser: bool = False, billing_session: boto3.Session | None = None,
                 billing_account_id: str = "", covered_resource_ids: set[str] | None = None) -> None:
        self.session = session
        self.region  = session.region_name
        # regions param accepted for API consistency but CE is global (us-east-1 only)
        self.regions = regions or [self.region]
        self.teaser  = teaser
        # Cost Explorer is only accessible from the payer/billing account. When a
        # payer session is supplied, CE queries run through it, scoped to the
        # target member account via billing_account_id (LINKED_ACCOUNT filter).
        self.billing_session    = billing_session or session
        self.billing_account_id = billing_account_id
        self.covered_resource_ids = {r.lower().strip() for r in (covered_resource_ids or set())}

    def run(self) -> list[Finding]:
        if self.teaser:
            return []
        findings: list[Finding] = []
        findings.extend(self._check_sp_coverage())
        findings.extend(self._check_ri_coverage())
        findings.extend(self._check_dynamodb_reserved_capacity())
        findings.extend(self._check_rightsizing())
        findings.extend(self._check_ec2_ri_expiration())
        return findings

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ce_client(self):
        return self.billing_session.client("ce", region_name="us-east-1")

    @staticmethod
    def _date_range() -> tuple[str, str]:
        end   = datetime.now(timezone.utc)
        start = end - timedelta(days=CE_LOOKBACK_DAYS)
        return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

    def _ce_total_spend(self, ce, start: str, end: str, service: str) -> float:
        """Return total unblended cost for a service over the date range."""
        try:
            resp = ce.get_cost_and_usage(
                TimePeriod={"Start": start, "End": end},
                Granularity="MONTHLY",
                Filter=scope_ce_filter(
                    {"Dimensions": {"Key": "SERVICE", "Values": [service]}},
                    self.billing_account_id,
                ),
                Metrics=["UnblendedCost"],
            )
            return sum(
                float(r.get("Total", {}).get("UnblendedCost", {}).get("Amount", "0"))
                for r in resp.get("ResultsByTime", [])
            )
        except Exception:
            return 0.0

    # ------------------------------------------------------------------
    # 5.1 -- Savings Plans coverage (EC2 + Lambda + Fargate)
    # ------------------------------------------------------------------

    def _check_sp_coverage(self) -> list[Finding]:
        ce = self._ce_client()
        start, end = self._date_range()
        findings: list[Finding] = []

        # GroupBy SERVICE gives per-service breakdown so Lambda/Fargate are visible
        sp_kwargs: dict = {
            "TimePeriod": {"Start": start, "End": end},
            "Granularity": "MONTHLY",
            "GroupBy": [{"Type": "DIMENSION", "Key": "SERVICE"}],
        }
        sp_filter = scope_ce_filter(None, self.billing_account_id)
        if sp_filter:
            sp_kwargs["Filter"] = sp_filter
        try:
            resp = ce.get_savings_plans_coverage(**sp_kwargs)
        except Exception as exc:
            err = str(exc)
            if "AccessDenied" in err or "UnauthorizedOperation" in err or "Unauthorized" in err:
                print(
                    "[savings_plans] SP coverage check skipped: CE API requires "
                    "payer/billing account access."
                )
            else:
                print(f"[savings_plans] SP coverage check failed: {exc}")
            return findings

        # Aggregate across periods to get per-service totals
        service_spend:    dict[str, float] = {}
        service_coverage: dict[str, list[float]] = {}

        for period in resp.get("SavingsPlansCoverages", []):
            svc = period.get("Attributes", {}).get("SERVICE", "All")
            cov = period.get("Coverage", {})
            coverage_pct  = float(cov.get("CoveragePercentage", "0") or "0")
            on_demand_cost = float(cov.get("OnDemandCost", "0") or "0")

            service_spend.setdefault(svc, 0.0)
            service_spend[svc] += on_demand_cost
            service_coverage.setdefault(svc, [])
            if coverage_pct > 0 or on_demand_cost > 0:
                service_coverage[svc].append(coverage_pct)

        for svc, on_demand_cost in service_spend.items():
            if on_demand_cost < SP_MIN_ON_DEMAND_USD:
                continue
            coverage_pct = (
                sum(service_coverage[svc]) / len(service_coverage[svc])
                if service_coverage.get(svc) else 0.0
            )
            if coverage_pct >= SP_COVERAGE_THRESHOLD_PCT:
                continue

            uncovered_fraction = (SP_COVERAGE_THRESHOLD_PCT - coverage_pct) / 100.0
            estimated_savings  = round(on_demand_cost * uncovered_fraction * SP_AVG_DISCOUNT_PCT, 2)
            monthly_spend      = round(on_demand_cost * (30 / CE_LOOKBACK_DAYS), 2)

            # Human-readable service label
            svc_label = {
                "AWS Lambda":                                 "Lambda",
                "Amazon Elastic Compute Cloud - Compute":    "EC2",
                "AWS Fargate":                               "Fargate",
            }.get(svc, svc)

            findings.append(Finding(
                id=f"SP-COMPUTE-COVERAGE-{svc.replace(' ', '-')}",
                title=(
                    f"Low Savings Plans coverage ({coverage_pct:.1f}%) for {svc_label} — "
                    f"${monthly_spend:.2f}/mo on-demand exposed"
                ),
                description=(
                    f"Compute Savings Plans coverage for {svc_label} is {coverage_pct:.1f}% "
                    f"(threshold: {SP_COVERAGE_THRESHOLD_PCT:.0f}%). "
                    f"On-demand spend over the last {CE_LOOKBACK_DAYS} days: ${on_demand_cost:.2f}. "
                    f"Compute Savings Plans cover EC2, Lambda (duration), and Fargate (vCPU + memory) "
                    f"with an average {SP_AVG_DISCOUNT_PCT*100:.0f}% discount versus on-demand rates. "
                    f"Closing the coverage gap to {SP_COVERAGE_THRESHOLD_PCT:.0f}% could save "
                    f"~${estimated_savings:.2f}/month."
                ),
                severity=Severity.HIGH,
                category=Category.COMPUTE_STRATEGY,
                service=f"Savings Plans / {svc_label}",
                region="global",
                resource_id=f"sp-coverage-{svc_label.lower()}",
                estimated_monthly_savings_usd=estimated_savings,
                recommendation=(
                    "Purchase Compute Savings Plans to cover the on-demand gap. "
                    "A single Compute SP commitment covers EC2, Lambda, and Fargate across "
                    "all regions and instance families. "
                    "Use CE → Savings Plans → Purchase recommendations to size correctly. "
                    "Start with 1-year, no-upfront to minimise commitment risk."
                ),
                metadata={
                    "service":            svc,
                    "coverage_pct":       round(coverage_pct, 1),
                    "on_demand_cost_usd": round(on_demand_cost, 2),
                    "threshold_pct":      SP_COVERAGE_THRESHOLD_PCT,
                    "avg_discount_pct":   SP_AVG_DISCOUNT_PCT * 100,
                    "query_period_days":  CE_LOOKBACK_DAYS,
                    "sp_scope_note": (
                        "Compute Savings Plans apply to EC2 instance hours, "
                        "Lambda duration (GB-seconds), and Fargate vCPU + memory hours."
                    ),
                },
            ))

        return findings

    # ------------------------------------------------------------------
    # 5.2 -- RI coverage: RDS, ElastiCache, Redshift, OpenSearch
    # ------------------------------------------------------------------

    def _check_ri_coverage(self) -> list[Finding]:
        ce = self._ce_client()
        start, end = self._date_range()
        findings: list[Finding] = []

        # One call per service — the SERVICE GroupBy dimension is not supported
        # by get_reservation_coverage for all services (e.g. RDS rejects it).
        for service in RI_SERVICES:
            try:
                resp = ce.get_reservation_coverage(
                    TimePeriod={"Start": start, "End": end},
                    Filter=scope_ce_filter(
                        {"Dimensions": {"Key": "SERVICE", "Values": [service]}},
                        self.billing_account_id,
                    ),
                    Granularity="MONTHLY",
                )
            except Exception as exc:
                err = str(exc)
                if "AccessDenied" in err or "UnauthorizedOperation" in err or "Unauthorized" in err:
                    print(
                        "[savings_plans] RI coverage check skipped: CE API requires "
                        "payer/billing account access."
                    )
                    return findings   # same for all services — bail out entirely
                print(f"[savings_plans] RI coverage for {service} failed: {exc}")
                continue

            # Aggregate coverage and spend across monthly periods for this service
            pct_values:   list[float] = []
            on_demand_total: float    = 0.0

            for period in resp.get("CoveragesByTime", []):
                total    = period.get("Total", {})
                pct      = float(total.get("CoverageHours", {}).get("CoverageHoursPercentage", "0") or "0")
                cost     = float(total.get("OnDemandCost", {}).get("Amount", "0") or "0")
                on_demand_total += cost
                if pct > 0 or cost > 0:
                    pct_values.append(pct)

            if on_demand_total < RI_MIN_ON_DEMAND_USD:
                continue

            coverage_pct = sum(pct_values) / len(pct_values) if pct_values else 0.0
            if coverage_pct >= RI_COVERAGE_THRESHOLD_PCT:
                continue

            discount           = RI_DISCOUNT_BY_SERVICE.get(service, RI_DEFAULT_DISCOUNT)
            uncovered_fraction = (RI_COVERAGE_THRESHOLD_PCT - coverage_pct) / 100.0
            estimated_savings  = round(on_demand_total * uncovered_fraction * discount, 2)
            monthly_spend      = round(on_demand_total * (30 / CE_LOOKBACK_DAYS), 2)
            safe_service       = service.replace(" ", "-").replace("/", "-")

            category = (
                Category.DATABASE_TUNING
                if any(k in service for k in ("Database", "ElastiCache", "Redshift", "OpenSearch", "Elasticsearch"))
                else Category.COMPUTE_STRATEGY
            )

            findings.append(Finding(
                id=f"SP-RI-COVERAGE-{safe_service}",
                title=(
                    f"Low RI coverage ({coverage_pct:.1f}%) for {service} — "
                    f"${monthly_spend:.2f}/mo on-demand exposed"
                ),
                description=(
                    f"Reserved Instance coverage for {service} is {coverage_pct:.1f}% "
                    f"(threshold: {RI_COVERAGE_THRESHOLD_PCT:.0f}%). "
                    f"On-demand spend over {CE_LOOKBACK_DAYS} days: ${on_demand_total:.2f} "
                    f"(~${monthly_spend:.2f}/month). "
                    f"Purchasing RIs at ~{discount*100:.0f}% discount could save "
                    f"~${estimated_savings:.2f}/month."
                ),
                severity=Severity.HIGH,
                category=category,
                service=service,
                region="global",
                resource_id=f"ri-coverage-{safe_service.lower()}",
                estimated_monthly_savings_usd=estimated_savings,
                recommendation=_ri_recommendation(service),
                metadata={
                    "service":            service,
                    "coverage_pct":       round(coverage_pct, 1),
                    "on_demand_cost_usd": round(on_demand_total, 2),
                    "threshold_pct":      RI_COVERAGE_THRESHOLD_PCT,
                    "discount_pct":       discount * 100,
                    "query_period_days":  CE_LOOKBACK_DAYS,
                },
            ))

        return findings

    # ------------------------------------------------------------------
    # 5.3 -- DynamoDB reserved capacity
    # ------------------------------------------------------------------

    def _check_dynamodb_reserved_capacity(self) -> list[Finding]:
        """
        DynamoDB reserved capacity is not tracked by get_reservation_coverage.
        Instead we check total DynamoDB spend and flag if it exceeds the threshold,
        then recommend purchasing reserved capacity (RCU/WCU) for stable workloads.
        Discounts: ~30% for 1-year, ~76% effective for 3-year (capacity units only;
        request charges are billed separately regardless of reservation).
        """
        ce = self._ce_client()
        start, end = self._date_range()
        findings: list[Finding] = []

        try:
            total_spend = self._ce_total_spend(ce, start, end, "Amazon DynamoDB")
        except Exception as exc:
            err = str(exc)
            if "AccessDenied" in err or "UnauthorizedOperation" in err or "Unauthorized" in err:
                print(
                    "[savings_plans] DynamoDB reserved capacity check skipped: "
                    "CE API requires payer/billing account access."
                )
            else:
                print(f"[savings_plans] DynamoDB spend check failed: {exc}")
            return findings

        if total_spend < DYNAMODB_MONTHLY_THRESHOLD_USD * (CE_LOOKBACK_DAYS / 30):
            return findings

        monthly_spend     = round(total_spend * (30 / CE_LOOKBACK_DAYS), 2)
        estimated_savings = round(monthly_spend * DYNAMODB_RESERVED_DISCOUNT_PCT, 2)

        findings.append(Finding(
            id="SP-DYNAMODB-RESERVED-CAPACITY",
            title=(
                f"DynamoDB reserved capacity opportunity — "
                f"${monthly_spend:.2f}/mo spend, ~${estimated_savings:.2f}/mo savings"
            ),
            description=(
                f"DynamoDB spend is ${monthly_spend:.2f}/month. "
                f"Provisioned-mode tables with stable read/write traffic are strong candidates "
                f"for DynamoDB Reserved Capacity: 1-year reservations save ~30%, "
                f"3-year reservations save ~76% on provisioned RCU/WCU charges. "
                f"On-demand and request charges are not covered by reservations."
            ),
            severity=Severity.HIGH if monthly_spend > 500 else Severity.MEDIUM,
            category=Category.DATABASE_TUNING,
            service="DynamoDB",
            region="global",
            resource_id="dynamodb-reserved-capacity",
            estimated_monthly_savings_usd=estimated_savings,
            recommendation=(
                "Identify provisioned-mode DynamoDB tables with stable throughput "
                "(consistent RCU/WCU over 2+ weeks) and purchase Reserved Capacity "
                "via DynamoDB console → Reserved Capacity → Purchase. "
                "Start with 1-year, no-upfront for stable tables. "
                "On-demand mode tables are not eligible — switch to provisioned mode first "
                "if traffic is predictable."
            ),
            metadata={
                "monthly_spend_usd":      monthly_spend,
                "discount_1yr_pct":       30,
                "discount_3yr_pct":       76,
                "estimated_monthly_savings_usd": estimated_savings,
                "query_period_days":      CE_LOOKBACK_DAYS,
                "reservation_scope":      "Provisioned RCU + WCU only; request charges excluded",
            },
        ))

        return findings

    # ------------------------------------------------------------------
    # 5.4 -- EC2 rightsizing recommendations
    # ------------------------------------------------------------------

    def _check_rightsizing(self) -> list[Finding]:
        ce = self._ce_client()
        findings: list[Finding] = []

        rs_kwargs: dict = {"Service": "AmazonEC2"}
        rs_filter = scope_ce_filter(None, self.billing_account_id)
        if rs_filter:
            rs_kwargs["Filter"] = rs_filter
        try:
            resp = ce.get_rightsizing_recommendation(**rs_kwargs)
        except Exception as exc:
            err = str(exc)
            if "AccessDenied" in err or "UnauthorizedOperation" in err or "Unauthorized" in err:
                print(
                    "[savings_plans] Rightsizing check skipped: CE API requires "
                    "payer/billing account access."
                )
            else:
                print(f"[savings_plans] Rightsizing check failed: {exc}")
            return findings

        recommendations = resp.get("RightsizingRecommendations", [])
        count = 0

        for rec in recommendations:
            if count >= MAX_RIGHTSIZING_FINDINGS:
                break

            instance_id    = rec.get("CurrentInstance", {}).get("ResourceId", "unknown")
            savings_detail = rec.get("RightsizingType", "")

            savings_amount = 0.0
            modify_recs = rec.get("ModifyRecommendationDetail", {})
            term_recs   = rec.get("TerminateRecommendationDetail", {})

            if modify_recs:
                target_instances = modify_recs.get("TargetInstances", [])
                if target_instances:
                    savings_amount = float(
                        target_instances[0].get("EstimatedMonthlySavings", "0") or "0"
                    )
            elif term_recs:
                savings_amount = float(
                    term_recs.get("EstimatedMonthlySavings", "0") or "0"
                )

            if savings_amount <= 0:
                continue

            current      = rec.get("CurrentInstance", {})
            current_type = current.get("InstanceType", "unknown")
            rec_region   = current.get("ResourceDetails", {}).get(
                "EC2ResourceDetails", {}
            ).get("Region", "")

            target_type = "terminate"
            if modify_recs and modify_recs.get("TargetInstances"):
                target_details = modify_recs["TargetInstances"][0].get("ResourceDetails", {})
                target_type = target_details.get("EC2ResourceDetails", {}).get(
                    "InstanceType", target_type
                )

            findings.append(Finding(
                id=f"SP-RIGHTSIZE-{instance_id}",
                title=(
                    f"EC2 rightsizing: {instance_id} ({current_type} → {target_type}) "
                    f"saves ~${savings_amount:.2f}/mo"
                ),
                description=(
                    f"Cost Explorer recommends {savings_detail.lower()} instance {instance_id} "
                    f"(currently {current_type}). "
                    f"Estimated monthly savings: ${savings_amount:.2f}."
                ),
                severity=Severity.MEDIUM,
                category=Category.COMPUTE_STRATEGY,
                service="EC2",
                region=rec_region or "global",
                resource_id=instance_id,
                estimated_monthly_savings_usd=savings_amount,
                recommendation=(
                    f"Review utilisation metrics for {instance_id} and apply the "
                    f"rightsizing recommendation ({savings_detail}). "
                    "Validate with the application team before making changes."
                ),
                metadata={
                    "instance_id":       instance_id,
                    "current_type":      current_type,
                    "recommended_type":  target_type,
                    "rightsizing_type":  savings_detail,
                    "estimated_monthly_savings_usd": savings_amount,
                },
            ))
            count += 1

        return findings

    # ------------------------------------------------------------------
    # 5.5 -- EC2 Reserved Instance lease expiration
    # ------------------------------------------------------------------

    def _check_ec2_ri_expiration(self) -> list[Finding]:
        findings: list[Finding] = []
        now = datetime.now(timezone.utc)
        warning_cutoff = now + timedelta(days=EC2_RI_EXPIRY_WARNING_DAYS)

        for region in self.regions:
            ec2 = self.session.client("ec2", region_name=region)

            try:
                paginator = ec2.get_paginator("describe_reserved_instances")
            except Exception:
                continue

            for page in paginator.paginate(
                Filters=[{"Name": "state", "Values": ["active"]}]
            ):
                for ri in page.get("ReservedInstances", []):
                    end = ri.get("End")
                    if not end:
                        continue
                    end_dt = end if end.tzinfo else end.replace(tzinfo=timezone.utc)
                    if end_dt > warning_cutoff:
                        continue

                    days_left = max(0, (end_dt - now).days)
                    ri_id = ri.get("ReservedInstancesId", "unknown")
                    instance_type = ri.get("InstanceType", "unknown")
                    count = ri.get("InstanceCount", 1)

                    findings.append(Finding(
                        id=f"SP-RI-EXPIRE-{ri_id}",
                        title=f"EC2 Reserved Instance expiring in {days_left} days",
                        description=(
                            f"Reserved Instance {ri_id} ({count}x {instance_type}) expires on "
                            f"{end_dt.strftime('%Y-%m-%d')} ({days_left} days). "
                            f"On expiry, instances revert to on-demand pricing."
                        ),
                        severity=Severity.HIGH if days_left <= 30 else Severity.MEDIUM,
                        category=Category.SAVINGS_PLANS,
                        service="EC2",
                        region=region,
                        resource_id=ri_id,
                        estimated_monthly_savings_usd=0.0,
                        recommendation=(
                            "Renew the RI, purchase a Savings Plan, or confirm intentional "
                            "move to on-demand/Spot before expiry."
                        ),
                        metadata={
                            "reserved_instance_id": ri_id,
                            "instance_type": instance_type,
                            "instance_count": count,
                            "end_date": end_dt.isoformat(),
                            "days_until_expiry": days_left,
                            "offering_type": ri.get("OfferingType", ""),
                        },
                    ))

        return findings


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _ri_recommendation(service: str) -> str:
    tips: dict[str, str] = {
        "Amazon Relational Database Service": (
            "Purchase RDS Reserved Instances for stable database workloads. "
            "Match instance class, engine, and deployment type (Single-AZ vs Multi-AZ). "
            "1-year, no-upfront is the safest starting point."
        ),
        "Amazon ElastiCache": (
            "Purchase ElastiCache Reserved Nodes for stable cache clusters. "
            "Match node type and engine (Redis vs Memcached). "
            "1-year, no-upfront reduces commitment risk."
        ),
        "Amazon Redshift": (
            "Purchase Redshift Reserved Nodes for stable clusters. "
            "Match node type (e.g. dc2.large, ra3.xlplus). "
            "Redshift offers 1-year (~38% off) and 3-year (~55% off) terms."
        ),
        "Amazon OpenSearch Service": (
            "Purchase OpenSearch Reserved Instances for stable domain nodes. "
            "Match instance type and deployment option. "
            "1-year, no-upfront provides ~32% savings."
        ),
        "Amazon Elasticsearch Service": (
            "Purchase Elasticsearch Reserved Instances for stable domain nodes. "
            "Consider migrating the domain to OpenSearch Service at the same time "
            "to access the latest features."
        ),
    }
    return tips.get(
        service,
        f"Purchase Reserved Instances for {service} to reduce on-demand spend. "
        "Use 1-year, no-upfront as the starting point.",
    )
