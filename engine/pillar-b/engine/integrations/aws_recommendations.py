"""
Pillar B — AWS Native Recommendations Module

Ingests cost recommendations from:
  1. AWS Trusted Advisor (cost_optimizing checks)
  2. AWS Compute Optimizer (EC2, EBS, Lambda)
  3. AWS Cost Optimization Hub (when enabled on payer account)

Runs first in the audit pipeline; custom modules add depth on top.
Deduplication happens after all modules complete.
"""
from __future__ import annotations

import boto3
from botocore.exceptions import ClientError

from integrations.recommendation_mapper import (
    TEASER_TA_NAME_KEYWORDS,
    finding_from_compute_optimizer_ebs,
    finding_from_compute_optimizer_ec2,
    finding_from_compute_optimizer_ecs,
    finding_from_compute_optimizer_lambda,
    finding_from_compute_optimizer_rds,
    finding_from_cost_optimization_hub,
    finding_from_trusted_advisor,
)
from shared.findings_schema import Finding

_SUPPORT_REGION = "us-east-1"
_MAX_CO_PAGES = 10
_MAX_COH_RESULTS = 200


class AwsRecommendationsModule:
    def __init__(
        self,
        session: boto3.Session,
        regions: list[str] | None = None,
        teaser: bool = False,
        billing_session: boto3.Session | None = None,
        billing_account_id: str = "",
    ) -> None:
        self.session = session
        self.region = session.region_name
        self.regions = regions or [self.region]
        self.teaser = teaser
        # Compute Optimizer + Cost Optimization Hub are org-level services best
        # queried from the payer account. billing_session defaults to the target
        # session; billing_account_id (set only in payer mode) scopes results.
        self.billing_session = billing_session or session
        self.billing_account_id = billing_account_id

    def run(self) -> list[Finding]:
        findings: list[Finding] = []
        findings.extend(self._fetch_trusted_advisor())
        if not self.teaser:
            findings.extend(self._fetch_compute_optimizer())
            findings.extend(self._fetch_cost_optimization_hub())
        return findings

    def _fetch_trusted_advisor(self) -> list[Finding]:
        support = self.session.client("support", region_name=_SUPPORT_REGION)
        findings: list[Finding] = []

        try:
            checks_resp = support.describe_trusted_advisor_checks(language="en")
        except ClientError as exc:
            print(f"  [AwsRecommendations] Trusted Advisor unavailable: {_short_error(exc)}")
            return findings

        cost_checks = [
            c for c in checks_resp.get("checks", [])
            if c.get("category") == "cost_optimizing"
        ]

        if self.teaser:
            cost_checks = [
                c for c in cost_checks
                if any(kw in c.get("name", "").lower() for kw in TEASER_TA_NAME_KEYWORDS)
            ]

        for check in cost_checks:
            check_id = check["id"]
            check_name = check.get("name", check_id)
            # describe_trusted_advisor_checks returns `metadata` as a list of plain
            # column-name strings; tolerate dicts too in case the shape ever changes.
            columns = [
                (m.get("name", f"col_{i}") if isinstance(m, dict) else str(m))
                for i, m in enumerate(check.get("metadata", []))
            ]

            try:
                result_resp = support.describe_trusted_advisor_check_result(checkId=check_id)
            except ClientError as exc:
                print(f"  [AwsRecommendations] TA check '{check_name}' skipped: {_short_error(exc)}")
                continue

            result = result_resp.get("result", {})
            if result.get("status") == "not_available":
                continue

            for resource in result.get("flaggedResources", []):
                if resource.get("isSuppressed"):
                    continue
                finding = finding_from_trusted_advisor(
                    check_id=check_id,
                    check_name=check_name,
                    resource=resource,
                    column_names=columns,
                )
                if finding:
                    findings.append(finding)

        if findings:
            print(f"  [AwsRecommendations] Trusted Advisor: {len(findings)} flagged resources")
        return findings

    def _fetch_compute_optimizer(self) -> list[Finding]:
        co = self.billing_session.client("compute-optimizer", region_name=_SUPPORT_REGION)
        findings: list[Finding] = []

        try:
            enroll = co.get_enrollment_status()
            if enroll.get("status") != "Active":
                print("  [AwsRecommendations] Compute Optimizer not enrolled — skipping")
                return findings
        except ClientError as exc:
            print(f"  [AwsRecommendations] Compute Optimizer unavailable: {_short_error(exc)}")
            return findings

        findings.extend(self._paginate_co(
            co.get_ec2_instance_recommendations,
            "instanceRecommendations",
            finding_from_compute_optimizer_ec2,
        ))
        findings.extend(self._paginate_co(
            co.get_ebs_volume_recommendations,
            "volumeRecommendations",
            finding_from_compute_optimizer_ebs,
        ))
        findings.extend(self._paginate_co(
            co.get_lambda_function_recommendations,
            "lambdaFunctionRecommendations",
            finding_from_compute_optimizer_lambda,
        ))
        findings.extend(self._paginate_co(
            co.get_rds_database_recommendations,
            "rdsDBRecommendations",
            finding_from_compute_optimizer_rds,
        ))
        findings.extend(self._paginate_co(
            co.get_ecs_service_recommendations,
            "ecsServiceRecommendations",
            finding_from_compute_optimizer_ecs,
        ))

        if findings:
            print(f"  [AwsRecommendations] Compute Optimizer: {len(findings)} recommendations")
        return findings

    def _paginate_co(self, api_call, result_key: str, mapper) -> list[Finding]:
        findings: list[Finding] = []
        token: str | None = None

        for _ in range(_MAX_CO_PAGES):
            kwargs: dict = {}
            # In payer mode, scope Compute Optimizer to the target member account.
            if self.billing_account_id:
                kwargs["accountIds"] = [self.billing_account_id]
            if token:
                kwargs["nextToken"] = token
            try:
                resp = api_call(**kwargs)
            except ClientError as exc:
                print(f"  [AwsRecommendations] CO {result_key} skipped: {_short_error(exc)}")
                break

            for item in resp.get(result_key, []):
                finding = mapper(item)
                if finding:
                    findings.append(finding)

            token = resp.get("nextToken")
            if not token:
                break

        return findings

    def _fetch_cost_optimization_hub(self) -> list[Finding]:
        coh = self.billing_session.client("cost-optimization-hub", region_name=_SUPPORT_REGION)
        findings: list[Finding] = []
        token: str | None = None
        fetched = 0

        while fetched < _MAX_COH_RESULTS:
            kwargs: dict = {"maxResults": min(100, _MAX_COH_RESULTS - fetched)}
            # In payer mode, scope Cost Optimization Hub to the target member account.
            if self.billing_account_id:
                kwargs["filter"] = {"accountIds": [self.billing_account_id]}
            if token:
                kwargs["nextToken"] = token

            try:
                resp = coh.list_recommendations(**kwargs)
            except ClientError as exc:
                err = _short_error(exc)
                if "not enabled" in err.lower() or "AccessDenied" in err:
                    print("  [AwsRecommendations] Cost Optimization Hub not enabled — skipping")
                else:
                    print(f"  [AwsRecommendations] COH skipped: {err}")
                break

            items = resp.get("items", [])
            for summary in items:
                finding = finding_from_cost_optimization_hub(summary)
                if finding:
                    findings.append(finding)

            fetched += len(items)
            token = resp.get("nextToken")
            if not token or not items:
                break

        if findings:
            print(f"  [AwsRecommendations] Cost Optimization Hub: {len(findings)} recommendations")
        return findings


def _short_error(exc: ClientError) -> str:
    err = exc.response.get("Error", {})
    return f"{err.get('Code', 'ClientError')}: {err.get('Message', str(exc))}"
