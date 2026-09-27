"""
Pillar B — Output: Dashboard Data Exporter

Serialises an AuditReport to a JSON payload consumed by the Pillar D web app.
Output file: dashboard_<account_id>_<YYYYMMDD>.json
"""
from __future__ import annotations

import json
from pathlib import Path

from shared.findings_schema import AuditReport, Category, Severity


def _count_by_tier(findings) -> dict[str, int]:
    counts: dict[str, int] = {}
    for f in findings:
        tier = f.metadata.get("priority_tier", "later")
        counts[tier] = counts.get(tier, 0) + 1
    return counts


def export_dashboard_data(report: AuditReport, output_dir: str = ".",
                          silent: bool = False) -> Path:
    """Serialise the audit report to JSON and return the output path.

    silent=True suppresses the confirmation print (used for mid-run checkpoints).
    """
    date_str = report.generated_at.strftime("%Y%m%d")
    filename = f"dashboard_{report.account_id}_{date_str}.json"
    output_path = Path(output_dir) / filename

    payload = {
        "account_id": report.account_id,
        "account_name": report.account_name,
        "generated_at": report.generated_at.isoformat(),
        "summary": {
            "total_findings": len(report.findings),
            "total_monthly_savings_usd": report.total_monthly_savings_usd,
            "by_severity": {
                sev: len(items)
                for sev, items in report.findings_by_severity.items()
            },
            "by_category": {
                cat: {
                    "count": len(items),
                    "savings_usd": round(sum(f.estimated_monthly_savings_usd for f in items), 2),
                }
                for cat, items in report.findings_by_category.items()
            },
            "by_priority_tier": _count_by_tier(report.findings),
        },
        "findings": [
            {
                "id": f.id,
                "title": f.title,
                "description": f.description,
                "severity": f.severity.value,
                "category": f.category.value,
                "service": f.service,
                "region": f.region,
                "resource_id": f.resource_id,
                "estimated_monthly_savings_usd": f.estimated_monthly_savings_usd,
                "recommendation": f.recommendation,
                "metadata": f.metadata,
            }
            for f in report.findings
        ],
    }

    output_path.write_text(json.dumps(payload, indent=2, default=str))
    if not silent:
        print(f"[dashboard_data] Dashboard JSON written to {output_path}")
    return output_path
