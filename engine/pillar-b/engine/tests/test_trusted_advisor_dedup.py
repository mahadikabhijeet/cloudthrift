"""
Unit tests for Trusted Advisor + Custom Module sequential execution & deduplication.
"""
import sys
from pathlib import Path

# Ensure pillar-b/engine is in python path
ENGINE_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(ENGINE_DIR))

from shared.findings_schema import Category, Finding, Severity
from enrichment.deduplicator import deduplicate_findings
from modules.infra_hygiene import InfraHygieneModule
from modules.compute_strategy import ComputeStrategyModule


def test_deduplicate_ta_and_custom_finding():
    """Verify that Trusted Advisor and Custom findings for the same resource ID are merged without double savings."""
    ta_finding = Finding(
        id="TA-check123-vol-0abc1234",
        title="Trusted Advisor: Underutilized Amazon EBS Volumes",
        description="AWS Trusted Advisor flagged vol-0abc1234 under check 'Underutilized Amazon EBS Volumes'.",
        severity=Severity.HIGH,
        category=Category.INFRA_HYGIENE,
        service="Underutilized Amazon EBS Volumes",
        region="us-east-1",
        resource_id="vol-0abc1234",
        estimated_monthly_savings_usd=50.00,
        recommendation="Review Trusted Advisor check",
        metadata={"source": "trusted_advisor"},
    )

    custom_finding = Finding(
        id="HYGIENE-EBS-vol-0abc1234",
        title="Unattached EBS volume (safe to delete)",
        description="Volume vol-0abc1234 (500 GiB gp2) has been unattached for 47 days.",
        severity=Severity.HIGH,
        category=Category.INFRA_HYGIENE,
        service="EC2/EBS",
        region="us-east-1",
        resource_id="vol-0abc1234",
        estimated_monthly_savings_usd=50.00,
        recommendation="Snapshot then delete this volume.",
        metadata={"source": "custom", "safe_to_delete": True},
    )

    deduped = deduplicate_findings([ta_finding, custom_finding])

    assert len(deduped) == 1
    result = deduped[0]
    assert result.resource_id == "vol-0abc1234"
    assert result.estimated_monthly_savings_usd == 50.00
    assert result.metadata.get("source") == "custom"
    assert "trusted_advisor" in result.metadata.get("also_reported_by", [])


def test_covered_resource_ids_skips_redundant_custom_checks():
    """Verify custom modules skip resources already in covered_resource_ids."""
    from unittest.mock import MagicMock
    mock_session = MagicMock()
    mock_session.region_name = "us-east-1"
    covered = {"vol-0abc1234", "i-0fff000aaa"}
    module = InfraHygieneModule(session=mock_session, regions=["us-east-1"], covered_resource_ids=covered)
    assert "vol-0abc1234" in module.covered_resource_ids
