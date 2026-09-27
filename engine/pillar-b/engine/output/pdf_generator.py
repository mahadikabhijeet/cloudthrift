"""
Pillar B — Output: PDF Report Generator

Renders an AuditReport as a formatted PDF using ReportLab.
Output file: audit_<account_id>_<YYYYMMDD>.pdf

Page 1: Executive summary (savings headline, top 3, severity + category tables)
Page 2: 30-day roadmap (quick wins + this month)
Page 3+: Full findings table + runbook appendix for top findings
"""
from __future__ import annotations

from pathlib import Path

from shared.findings_schema import AuditReport, Severity

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

SEVERITY_COLOURS = {
    Severity.CRITICAL: "#c0392b",
    Severity.HIGH:     "#e67e22",
    Severity.MEDIUM:   "#f1c40f",
    Severity.LOW:      "#27ae60",
}

_CAT_LABELS = {
    "infra_hygiene":    "Infra Hygiene",
    "compute_strategy": "Compute Strategy",
    "network_storage":  "Network & Storage",
    "database_tuning":  "Database Tuning",
    "savings_plans":    "Savings Plans",
}

_TIER_LABELS = {
    "quick_win":    "Quick Win (do this week)",
    "this_month":   "This Month",
    "needs_review": "Needs Review (higher risk)",
    "later":        "Later",
}

_RUNBOOK_APPENDIX_LIMIT = 8


def generate_pdf(report: AuditReport, output_dir: str = ".") -> Path:
    """Write the audit report to a PDF file and return the output path."""
    date_str = report.generated_at.strftime("%Y%m%d")
    filename = f"audit_{report.account_id}_{date_str}.pdf"
    output_path = Path(output_dir) / filename

    if not REPORTLAB_AVAILABLE:
        print("[pdf_generator] reportlab not installed — skipping PDF generation.")
        print("  Install with: pip install reportlab")
        return output_path

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(output_path), pagesize=A4)
    styles = getSampleStyleSheet()
    mono = ParagraphStyle(
        "Mono",
        parent=styles["Code"],
        fontName="Courier",
        fontSize=7,
        leading=9,
    )
    story: list = []

    # Page 1: executive summary
    story.extend(_build_summary_page(report, styles))

    # Page 2: roadmap
    story.extend(_build_roadmap_page(report, styles))

    # Page 3+: full findings (already priority-sorted if pipeline ran)
    story.extend(_build_findings_table(report, styles))

    # Runbook appendix
    story.extend(_build_runbook_appendix(report, styles, mono))

    doc.build(story)
    print(f"[pdf_generator] Report written to {output_path}")
    return output_path


def _sorted_findings(report: AuditReport) -> list:
    """Findings are pre-sorted by prioritizer; fall back to severity."""
    if not report.findings:
        return []
    if report.findings[0].metadata.get("priority_score") is not None:
        return list(report.findings)
    return sorted(report.findings, key=lambda x: list(Severity).index(x.severity))


def _build_summary_page(report: AuditReport, styles) -> list:
    """Return a list of ReportLab flowables for the executive summary page."""
    story: list = []
    findings = _sorted_findings(report)

    story.append(Paragraph("FinOps Cloud Cost Audit Report", styles["Title"]))
    story.append(Spacer(1, 0.4 * cm))
    acct_label = report.account_name or report.account_id
    story.append(Paragraph(f"Account: {acct_label} ({report.account_id})", styles["Normal"]))
    story.append(Paragraph(
        f"Generated: {report.generated_at.strftime('%Y-%m-%d %H:%M UTC')}",
        styles["Normal"],
    ))
    story.append(Spacer(1, 0.8 * cm))

    monthly = report.total_monthly_savings_usd
    story.append(Paragraph(
        f"Estimated Monthly Savings: ${monthly:,.0f}",
        styles["Heading2"],
    ))
    story.append(Paragraph(
        f"Annual opportunity: ${monthly * 12:,.0f}  |  "
        f"Total findings: {len(report.findings)}",
        styles["Normal"],
    ))
    story.append(Spacer(1, 0.8 * cm))

    if findings:
        story.append(Paragraph("Top 3 Priority Opportunities", styles["Heading2"]))
        story.append(Spacer(1, 0.3 * cm))
        top3 = findings[:3]
        top3_data = [["#", "Finding", "Tier", "Est. Savings/mo"]]
        for i, f in enumerate(top3, 1):
            savings_str = f"${f.estimated_monthly_savings_usd:,.0f}" if f.estimated_monthly_savings_usd else "—"
            tier = _TIER_LABELS.get(f.metadata.get("priority_tier", ""), "—")
            top3_data.append([
                str(i),
                f.title[:60],
                tier[:22],
                savings_str,
            ])
        top3_table = Table(top3_data, colWidths=[0.7 * cm, 9 * cm, 3.5 * cm, 3.3 * cm])
        top3_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
            ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
            ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",   (0, 0), (-1, -1), 9),
            ("GRID",       (0, 0), (-1, -1), 0.5, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#ecf0f1")]),
        ]))
        story.append(top3_table)
        story.append(Spacer(1, 0.8 * cm))

    by_sev = report.findings_by_severity
    sev_rows = [
        (sev.value.upper(), len(by_sev.get(sev.value, [])))
        for sev in (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW)
        if by_sev.get(sev.value)
    ]
    if sev_rows:
        story.append(Paragraph("Findings by Severity", styles["Heading2"]))
        story.append(Spacer(1, 0.3 * cm))
        sev_data = [["Severity", "Count"]] + [[sev, str(cnt)] for sev, cnt in sev_rows]
        sev_table = Table(sev_data, colWidths=[5 * cm, 2 * cm])
        sev_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
            ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
            ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",   (0, 0), (-1, -1), 9),
            ("GRID",       (0, 0), (-1, -1), 0.5, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#ecf0f1")]),
        ]))
        story.append(sev_table)
        story.append(Spacer(1, 0.8 * cm))

    by_cat = report.findings_by_category
    cat_rows = sorted(
        [
            (
                _CAT_LABELS.get(cat, cat),
                len(items),
                sum(f.estimated_monthly_savings_usd for f in items),
            )
            for cat, items in by_cat.items()
            if items
        ],
        key=lambda r: -r[2],
    )
    if cat_rows:
        story.append(Paragraph("Findings by Category", styles["Heading2"]))
        story.append(Spacer(1, 0.3 * cm))
        cat_data = [["Category", "Findings", "Est. Savings/mo"]] + [
            [label, str(count), f"${savings:,.0f}"]
            for label, count, savings in cat_rows
        ]
        cat_table = Table(cat_data, colWidths=[7 * cm, 2.5 * cm, 4 * cm])
        cat_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
            ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
            ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",   (0, 0), (-1, -1), 9),
            ("GRID",       (0, 0), (-1, -1), 0.5, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#ecf0f1")]),
        ]))
        story.append(cat_table)

    story.append(PageBreak())
    return story


def _build_roadmap_page(report: AuditReport, styles) -> list:
    story: list = []
    findings = _sorted_findings(report)

    story.append(Paragraph("30-Day Remediation Roadmap", styles["Title"]))
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph(
        "Findings ranked by savings × ease × risk. Start with Quick Wins.",
        styles["Normal"],
    ))
    story.append(Spacer(1, 0.5 * cm))

    for tier_key in ("quick_win", "this_month", "needs_review"):
        tier_findings = [
            f for f in findings
            if f.metadata.get("priority_tier") == tier_key
        ][:5]
        if not tier_findings:
            continue

        label = _TIER_LABELS.get(tier_key, tier_key)
        story.append(Paragraph(label, styles["Heading2"]))
        story.append(Spacer(1, 0.2 * cm))

        rows = [["Finding", "Resource", "Savings/mo", "Score"]]
        for f in tier_findings:
            rows.append([
                f.title[:50],
                f.resource_id[:24],
                f"${f.estimated_monthly_savings_usd:,.0f}" if f.estimated_monthly_savings_usd else "—",
                str(f.metadata.get("priority_score", "—")),
            ])
        table = Table(rows, colWidths=[7 * cm, 4 * cm, 2.5 * cm, 1.8 * cm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#34495e")),
            ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
            ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",   (0, 0), (-1, -1), 8),
            ("GRID",       (0, 0), (-1, -1), 0.5, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f9fa")]),
        ]))
        story.append(table)
        story.append(Spacer(1, 0.5 * cm))

    story.append(PageBreak())
    return story


def _build_findings_table(report: AuditReport, styles) -> list:
    story: list = []
    findings = _sorted_findings(report)

    story.append(Paragraph("All Findings (priority order)", styles["Heading1"]))
    story.append(Spacer(1, 0.3 * cm))

    if not findings:
        story.append(Paragraph("No findings — account looks healthy!", styles["Normal"]))
        return story

    table_data = [["Tier", "Severity", "Title", "Service", "Resource", "Savings/mo"]]
    for f in findings:
        tier = f.metadata.get("priority_tier", "")[:12]
        table_data.append([
            tier,
            f.severity.value.upper(),
            f.title[:45],
            f.service[:12],
            f.resource_id[:22],
            f"${f.estimated_monthly_savings_usd:,.2f}",
        ])

    table = Table(table_data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, -1), 7),
        ("GRID",       (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#ecf0f1")]),
    ]))
    story.append(table)
    story.append(PageBreak())
    return story


def _build_runbook_appendix(report: AuditReport, styles, mono_style) -> list:
    story: list = []
    findings = _sorted_findings(report)[:_RUNBOOK_APPENDIX_LIMIT]

    if not findings:
        return story

    story.append(Paragraph("Runbook Appendix — Top Priority Findings", styles["Heading1"]))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(
        "Copy-paste CLI steps. Validate in non-production before applying.",
        styles["Normal"],
    ))
    story.append(Spacer(1, 0.4 * cm))

    for i, f in enumerate(findings, 1):
        story.append(Paragraph(
            f"{i}. {f.title} <font size='8' color='#666666'>({f.resource_id})</font>",
            styles["Heading3"],
        ))
        runbook = f.metadata.get("runbook") or [f.recommendation]
        for step in runbook:
            safe = step.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            story.append(Paragraph(safe, mono_style))
        story.append(Spacer(1, 0.3 * cm))

    return story
