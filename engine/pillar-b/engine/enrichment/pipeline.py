"""
Post-processing pipeline: deduplicate → runbooks → prioritize.
"""
from __future__ import annotations

from enrichment.deduplicator import deduplicate_findings
from enrichment.prioritizer import prioritize_findings
from enrichment.runbook_generator import attach_runbooks
from shared.findings_schema import Finding


def post_process_findings(findings: list[Finding]) -> tuple[list[Finding], dict]:
    """
    Run the full enrichment pipeline.

    Returns (processed_findings, stats_dict).
    """
    before = len(findings)
    findings = deduplicate_findings(findings)
    after_dedup = len(findings)
    findings = attach_runbooks(findings)
    findings = prioritize_findings(findings)

    tiers: dict[str, int] = {}
    for f in findings:
        tier = f.metadata.get("priority_tier", "later")
        tiers[tier] = tiers.get(tier, 0) + 1

    stats = {
        "before_dedup": before,
        "after_dedup": after_dedup,
        "quick_wins": tiers.get("quick_win", 0),
        "this_month": tiers.get("this_month", 0),
        "later": tiers.get("later", 0),
        "needs_review": tiers.get("needs_review", 0),
    }
    return findings, stats
