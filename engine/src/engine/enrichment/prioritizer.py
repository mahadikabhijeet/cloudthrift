"""
Score and rank findings by savings × ease × risk for delivery roadmaps.
"""
from __future__ import annotations

from shared.findings_schema import Finding, Severity

_SEVERITY_WEIGHT = {
    Severity.CRITICAL: 100.0,
    Severity.HIGH: 75.0,
    Severity.MEDIUM: 50.0,
    Severity.LOW: 25.0,
}

# (ease 0-1, risk 0-1) — higher ease = simpler; higher risk = more dangerous
_PATTERN_SCORES: list[tuple[str, float, float]] = [
    ("HYGIENE-EIP-", 0.95, 0.05),
    ("HYGIENE-EBS-", 0.90, 0.15),
    ("HYGIENE-GP2-", 0.92, 0.10),
    ("HYGIENE-SNAP-", 0.85, 0.20),
    ("HYGIENE-ELB-", 0.80, 0.25),
    ("HYGIENE-ECR-", 0.88, 0.10),
    ("NETWORK-NAT-IDLE-", 0.75, 0.35),
    ("NETWORK-VPCE-IDLE-", 0.78, 0.30),
    ("STORAGE-S3-MULTIPART-", 0.90, 0.05),
    ("STORAGE-S3-", 0.82, 0.12),
    ("OBS-LOGS-", 0.85, 0.08),
    ("SP-RI-EXPIRE-", 0.60, 0.20),
    ("SP-RIGHTSIZE-", 0.45, 0.55),
    ("CO-EC2-", 0.45, 0.55),
    ("CO-RDS-", 0.35, 0.70),
    ("CO-LAMBDA-", 0.55, 0.40),
    ("CO-ECS-", 0.50, 0.45),
    ("COH-", 0.50, 0.40),
    ("TA-", 0.70, 0.30),
]


def _ease_and_risk(finding: Finding) -> tuple[float, float]:
    for prefix, ease, risk in _PATTERN_SCORES:
        if finding.id.startswith(prefix):
            return ease, risk

    cat = finding.category.value
    if cat == "infra_hygiene":
        return 0.80, 0.20
    if cat == "network_storage":
        return 0.75, 0.25
    if cat == "savings_plans":
        return 0.55, 0.35
    if cat == "database_tuning":
        return 0.40, 0.65
    return 0.50, 0.45


def _tier(score: float, ease: float, risk: float, savings: float) -> str:
    if ease >= 0.75 and risk <= 0.30:
        return "quick_win"
    if score >= 50 or savings >= 100:
        return "this_month"
    if risk >= 0.60:
        return "needs_review"
    return "later"


def prioritize_findings(findings: list[Finding]) -> list[Finding]:
    """
    Enrich each finding with priority metadata and return sorted highest-first.
    """
    enriched: list[Finding] = []

    for finding in findings:
        ease, risk = _ease_and_risk(finding)
        savings = finding.estimated_monthly_savings_usd
        base = savings if savings > 0 else _SEVERITY_WEIGHT.get(finding.severity, 25.0)
        score = round(base * ease * (1.0 - risk), 2)
        tier = _tier(score, ease, risk, savings)

        meta = dict(finding.metadata)
        meta.update({
            "priority_score": score,
            "priority_tier": tier,
            "implementation_ease": round(ease, 2),
            "implementation_risk": round(risk, 2),
        })
        enriched.append(finding.model_copy(update={"metadata": meta}))

    enriched.sort(
        key=lambda f: (
            -f.metadata.get("priority_score", 0),
            -f.estimated_monthly_savings_usd,
            list(Severity).index(f.severity),
        ),
    )
    return enriched
