"""
shared/findings_schema.py — Pydantic models for audit findings and reports.

All Pillar B modules produce Finding objects; the output layer consumes AuditReport.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Category(str, Enum):
    INFRA_HYGIENE = "infra_hygiene"
    COMPUTE_STRATEGY = "compute_strategy"
    NETWORK_STORAGE = "network_storage"
    DATABASE_TUNING = "database_tuning"
    SAVINGS_PLANS = "savings_plans"


class Finding(BaseModel):
    id: str = Field(..., description="Unique finding identifier, e.g. HYGIENE-EBS-vol-abc123")
    title: str
    description: str
    severity: Severity
    category: Category
    service: str = Field(..., description="AWS service name, e.g. EC2, RDS, S3")
    region: str
    resource_id: str
    estimated_monthly_savings_usd: float = Field(default=0.0, ge=0)
    recommendation: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class AuditReport(BaseModel):
    account_id: str
    account_name: str = ""
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    findings: list[Finding] = Field(default_factory=list)

    @property
    def total_monthly_savings_usd(self) -> float:
        return round(sum(f.estimated_monthly_savings_usd for f in self.findings), 2)

    @property
    def findings_by_severity(self) -> dict[str, list[Finding]]:
        result: dict[str, list[Finding]] = {s.value: [] for s in Severity}
        for f in self.findings:
            result[f.severity.value].append(f)
        return result

    @property
    def findings_by_category(self) -> dict[str, list[Finding]]:
        result: dict[str, list[Finding]] = {c.value: [] for c in Category}
        for f in self.findings:
            result[f.category.value].append(f)
        return result
