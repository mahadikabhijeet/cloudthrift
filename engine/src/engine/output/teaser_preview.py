"""
Pillar B — Output: Teaser Preview Generator

Generates a prospect-facing markdown summary from a teaser scan result.
Used as an outreach hook: "I ran a 3-minute scan and found these things in
your account — want the full picture?"

Output: teaser_<account_id>_<YYYYMMDD>.md

Automatically generated when running with --mode teaser.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

MAX_PREVIEW_FINDINGS        = 5
FULL_AUDIT_MULTIPLIER_LOW   = 3
FULL_AUDIT_MULTIPLIER_HIGH  = 10


def export_teaser_preview(report, output_dir: str = ".") -> Path:
    """Generate a prospect-facing markdown preview from a teaser scan."""
    payload      = _to_dict(report)
    account_id   = payload["account_id"]
    account_name = payload.get("account_name") or account_id
    date_str     = payload.get("generated_at", "")[:10]
    findings     = payload.get("findings", [])

    total_savings = sum(f.get("estimated_monthly_savings_usd", 0) for f in findings)

    # Prefer quick wins, then by priority_score
    sorted_findings = sorted(
        findings,
        key=lambda f: (
            0 if f.get("metadata", {}).get("priority_tier") == "quick_win" else 1,
            -f.get("metadata", {}).get("priority_score", 0),
            -f.get("estimated_monthly_savings_usd", 0),
        ),
    )
    top = sorted_findings[:MAX_PREVIEW_FINDINGS]
    remaining = len(findings) - len(top)
    quick_win_count = sum(
        1 for f in findings
        if f.get("metadata", {}).get("priority_tier") == "quick_win"
    )

    low_est  = _round_to_hundreds(total_savings * FULL_AUDIT_MULTIPLIER_LOW)
    high_est = _round_to_hundreds(total_savings * FULL_AUDIT_MULTIPLIER_HIGH)

    lines = [
        "# AWS Cost Audit — Quick-Scan Preview",
        "",
        f"**Account:** {account_name}",
        f"**Scanned:** {date_str}  ·  **Type:** Fast infrastructure scan",
        "",
        "> Covers orphaned EBS volumes, unassociated Elastic IPs, idle load balancers,",
        "> gp2→gp3 migrations, S3 lifecycle gaps, and Trusted Advisor cost flags.",
        ">",
        f"> A full 48-hour audit (18 AWS regions, CloudWatch metrics, Cost Explorer, Savings Plans)",
        f"> typically uncovers **{FULL_AUDIT_MULTIPLIER_LOW}–{FULL_AUDIT_MULTIPLIER_HIGH}× more savings** than a quick scan.",
        "",
        "---",
        "",
        "## What We Found",
        "",
    ]

    if quick_win_count:
        lines.append(f"**{quick_win_count} quick win{'s' if quick_win_count != 1 else ''}** — safe to action this week.")
        lines.append("")

    if top:
        lines += [
            "| Finding | Service | Region | Est. Savings/mo |",
            "|---------|---------|--------|-----------------|",
        ]
        for f in top:
            savings = f.get("estimated_monthly_savings_usd", 0)
            savings_str = f"${savings:,.0f}" if savings else "—"
            title = f.get("title", "")[:72]
            tier = f.get("metadata", {}).get("priority_tier", "")
            if tier == "quick_win":
                title = f"⚡ {title}"
            lines.append(
                f"| {title} | {f.get('service', '')} | {f.get('region', '')} | {savings_str} |"
            )
        if remaining > 0:
            lines.append(f"| *…and {remaining} more findings* | | | |")
    else:
        lines.append("*No findings in this quick scan — this account has good infrastructure hygiene.*")

    lines += [""]

    if total_savings > 0:
        lines += [
            f"**Quick-scan total: ${total_savings:,.0f}/month**  ",
            f"**Full-audit estimate: ${low_est:,.0f}–${high_est:,.0f}/month** "
            f"({FULL_AUDIT_MULTIPLIER_LOW}–{FULL_AUDIT_MULTIPLIER_HIGH}× extrapolation from quick scan)",
        ]
    else:
        lines.append(
            "No dollar-quantified findings in the quick scan — the full audit would check "
            "CloudWatch metrics and Cost Explorer for the complete picture."
        )

    lines += [
        "",
        "---",
        "",
        "## How the Full Audit Works",
        "",
        "| Step | Owner | Time |",
        "|------|-------|------|",
        "| Run one CloudFormation command (read-only IAM role) | You | ~5 min |",
        "| Full audit runs — 18 regions, CloudWatch, Cost Explorer | Us | ~48 hrs |",
        "| Interactive dashboard + PDF report delivered | Us | Day 2 |",
        "| 30-min walkthrough call — top findings, priority order | Both | Day 3–5 |",
        "| Delete the role (one command, access removed permanently) | You | After call |",
        "",
        "**No application data leaves your account. No write permissions. Open-source setup script.**",
        "",
        "---",
        "",
        "*Want to see the full picture?*",
        "*Reply to this message or book a 30-minute call — we'll walk through the findings together.*",
        "",
        f"*Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} by FinOps Platform — teaser scan*",
    ]

    content = "\n".join(lines)
    date_compact = date_str.replace("-", "")
    filename    = f"teaser_{account_id}_{date_compact}.md"
    output_path = Path(output_dir) / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    print(f"[teaser_preview] Prospect preview written to {output_path}")
    return output_path


def _to_dict(report) -> dict:
    if isinstance(report, dict):
        return report
    return {
        "account_id":   report.account_id,
        "account_name": report.account_name,
        "generated_at": report.generated_at.isoformat(),
        "findings": [
            {
                "id":                            f.id,
                "title":                         f.title,
                "severity":                      f.severity.value,
                "service":                       f.service,
                "region":                        f.region,
                "resource_id":                   f.resource_id,
                "estimated_monthly_savings_usd": f.estimated_monthly_savings_usd,
                "metadata":                      f.metadata,
            }
            for f in report.findings
        ],
    }


def _round_to_hundreds(n: float) -> float:
    return round(n / 100) * 100
