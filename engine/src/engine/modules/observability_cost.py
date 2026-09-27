"""
Pillar B — Observability Cost Module

Flags CloudWatch Logs groups with infinite retention (common hidden cost).
"""
from __future__ import annotations

import boto3

from shared.findings_schema import Category, Finding, Severity

# ~$0.03/GB-month storage (varies by region)
LOGS_STORAGE_GB_MONTH_USD = 0.03
# Groups storing more than this are worth flagging at higher severity
LOGS_HIGH_STORAGE_BYTES = 10 * 1024 ** 3   # 10 GB


class ObservabilityCostModule:
    def __init__(
        self,
        session: boto3.Session,
        regions: list[str] | None = None,
        teaser: bool = False,
        covered_resource_ids: set[str] | None = None,
    ) -> None:
        self.session = session
        self.region = session.region_name
        self.regions = regions or [self.region]
        self.teaser = teaser
        self.covered_resource_ids = {r.lower().strip() for r in (covered_resource_ids or set())}

    def run(self) -> list[Finding]:
        findings: list[Finding] = []
        findings.extend(self._check_log_groups_without_retention())
        return findings

    def _check_log_groups_without_retention(self) -> list[Finding]:
        findings: list[Finding] = []

        for region in self.regions:
            logs = self.session.client("logs", region_name=region)

            try:
                paginator = logs.get_paginator("describe_log_groups")
            except Exception:
                continue

            for page in paginator.paginate():
                for group in page.get("logGroups", []):
                    if group.get("retentionInDays") is not None:
                        continue

                    name = group["logGroupName"]
                    stored_bytes = group.get("storedBytes", 0) or 0
                    stored_gib = stored_bytes / (1024 ** 3)
                    monthly_storage = round(stored_gib * LOGS_STORAGE_GB_MONTH_USD, 2)

                    severity = (
                        Severity.HIGH if stored_bytes >= LOGS_HIGH_STORAGE_BYTES
                        else Severity.MEDIUM if stored_bytes > 0
                        else Severity.LOW
                    )

                    findings.append(Finding(
                        id=f"OBS-LOGS-{name[:40].replace('/', '-')}",
                        title=f"CloudWatch log group '{name}' has infinite retention",
                        description=(
                            f"Log group '{name}' has no retention policy "
                            f"({stored_gib:.2f} GiB stored). Logs are kept forever, "
                            f"increasing storage cost over time."
                        ),
                        severity=severity,
                        category=Category.NETWORK_STORAGE,
                        service="CloudWatch Logs",
                        region=region,
                        resource_id=name,
                        estimated_monthly_savings_usd=monthly_storage,
                        recommendation=(
                            "Set retention to 30–90 days for application logs, "
                            "or export to S3/Glacier for long-term archival: "
                            f"aws logs put-retention-policy --log-group-name '{name}' "
                            "--retention-in-days 30"
                        ),
                        metadata={
                            "log_group_name": name,
                            "stored_bytes": stored_bytes,
                            "stored_gib": round(stored_gib, 2),
                            "recommended_retention_days": 30,
                        },
                    ))

        return findings
