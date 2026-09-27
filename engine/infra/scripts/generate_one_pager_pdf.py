#!/usr/bin/env python3
"""
Generate a professional one-page marketing PDF for client outreach.

Usage:
    python infra/scripts/generate_one_pager_pdf.py [--out DIR]

Output: finops_audit_one_pager.pdf  (in current directory or --out)

Requires: pip install reportlab
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm, mm
    from reportlab.platypus import (
        HRFlowable,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
except ImportError:
    print("ERROR: reportlab not installed.")
    print("  pip install reportlab")
    sys.exit(1)

# ── Brand colours ────────────────────────────────────────────────────────────
BRAND_ORANGE  = colors.HexColor("#f97316")
DARK_BG       = colors.HexColor("#111827")
DARK_CARD     = colors.HexColor("#1f2937")
LIGHT_GREY    = colors.HexColor("#f3f4f6")
MEDIUM_GREY   = colors.HexColor("#6b7280")
GREEN         = colors.HexColor("#16a34a")
WHITE         = colors.white

# ── Sample data (replace with real numbers from your best engagement) ────────
SAMPLE_FINDINGS = [
    ("Compute Savings Plans coverage only 31%",    "Savings Plans",     "$4,200"),
    ("3 non-prod RDS instances running 24/7",      "RDS",               "$1,240"),
    ("12 gp2 volumes → gp3 migration",             "EC2/EBS",           "$890"),
    ("NAT Gateway data-processing charges",        "VPC/NAT",           "$780"),
    ("23 orphaned EBS snapshots (avg 180 days)",   "EC2/EBS",           "$340"),
    ("2 unattached EBS volumes",                   "EC2/EBS",           "$220"),
    ("TOTAL",                                      "",                  "$7,670/mo"),
]

CHECKS = [
    ("Infrastructure Hygiene",
     "Unattached EBS · Orphaned snapshots · Unassociated Elastic IPs · "
     "gp2→gp3 · Idle load balancers"),
    ("Compute Strategy",
     "Idle EC2 (CloudWatch-verified) · Stopped instances · "
     "Graviton opportunities · Spot Fleet candidates"),
    ("Database Tuning",
     "Non-prod RDS stop/start automation · Idle RDS · "
     "Single-AZ production gaps"),
    ("Network & Storage",
     "NAT Gateway charges · Inter-AZ traffic · S3 lifecycle gaps"),
    ("Savings Plans & RIs",
     "EC2/Lambda/Fargate SP coverage · RDS/ElastiCache/Redshift/OpenSearch RI gaps · "
     "DynamoDB reserved capacity · EC2 rightsizing"),
]

HOW_IT_WORKS = [
    ("1", "You run ONE command",     "CloudFormation template → read-only IAM role (~5 min)"),
    ("2", "We run the full audit",   "18 AWS regions, CloudWatch metrics, Cost Explorer (~48 hrs)"),
    ("3", "You get the report",      "Interactive dashboard + PDF, priority-ordered recommendations"),
    ("4", "You delete the role",     "One command — all access permanently removed"),
]


def build(output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm,
    )

    styles = getSampleStyleSheet()
    W = A4[0] - 3 * cm   # usable width

    def s(name, **kw) -> ParagraphStyle:
        base = styles[name]
        return ParagraphStyle(name + str(id(kw)), parent=base, **kw)

    story = []

    # ── Header band ──────────────────────────────────────────────────────────
    header_data = [[
        Paragraph('<font color="white"><b>FinOps</b></font>'
                  '<font color="#f97316"><b> Cloud Cost Audit</b></font>',
                  s("Title", fontSize=22, textColor=WHITE, spaceAfter=2)),
        Paragraph(
            '<font color="#9ca3af">Read-only · 48 hours · Fully deletable</font>',
            s("Normal", fontSize=9, textColor=MEDIUM_GREY, alignment=TA_RIGHT),
        ),
    ]]
    header_table = Table(header_data, colWidths=[W * 0.65, W * 0.35])
    header_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), DARK_BG),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING",   (0, 0), (0, -1), 12),
        ("RIGHTPADDING",  (-1, 0), (-1, -1), 12),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 4 * mm))

    # ── Tagline ───────────────────────────────────────────────────────────────
    story.append(Paragraph(
        "Most engineering teams overpay for AWS by <b>20–40%</b>. "
        "We surface the savings in 48 hours — no agents deployed, no write access, nothing installed.",
        s("Normal", fontSize=9.5, textColor=colors.HexColor("#374151"), spaceAfter=4),
    ))
    story.append(HRFlowable(width=W, thickness=0.5, color=LIGHT_GREY))
    story.append(Spacer(1, 3 * mm))

    # ── Two-column section: What We Check + Sample Findings ──────────────────
    left_col = []

    left_col.append(Paragraph(
        "WHAT WE CHECK",
        s("Normal", fontSize=7.5, textColor=BRAND_ORANGE,
          fontName="Helvetica-Bold", spaceAfter=4),
    ))
    left_col.append(Paragraph(
        "20+ automated checks across 18 AWS regions",
        s("Normal", fontSize=8, textColor=MEDIUM_GREY, spaceAfter=6),
    ))

    for cat_name, cat_detail in CHECKS:
        left_col.append(Paragraph(
            f"<b>{cat_name}</b>",
            s("Normal", fontSize=8.5, textColor=DARK_BG, spaceAfter=1),
        ))
        left_col.append(Paragraph(
            cat_detail,
            s("Normal", fontSize=7.5, textColor=MEDIUM_GREY, spaceAfter=5),
        ))

    right_col = []
    right_col.append(Paragraph(
        "SAMPLE FINDINGS",
        s("Normal", fontSize=7.5, textColor=BRAND_ORANGE,
          fontName="Helvetica-Bold", spaceAfter=4),
    ))
    right_col.append(Paragraph(
        "Series B SaaS · $55k/mo AWS spend",
        s("Normal", fontSize=8, textColor=MEDIUM_GREY, spaceAfter=6),
    ))

    findings_data = [["Finding", "Service", "Savings/mo"]]
    for finding, service, savings in SAMPLE_FINDINGS:
        findings_data.append([finding, service, savings])

    findings_table = Table(
        findings_data,
        colWidths=[None, None, 1.8 * cm],
    )
    findings_table.setStyle(TableStyle([
        ("FONTSIZE",   (0, 0), (-1, -1), 7),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), DARK_CARD),
        ("TEXTCOLOR",  (0, 0), (-1, 0), WHITE),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#dcfce7")),
        ("TEXTCOLOR",  (0, -1), (-1, -1), GREEN),
        ("FONTNAME",   (0, -1), (-1, -1), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [WHITE, LIGHT_GREY]),
        ("GRID",       (0, 0), (-1, -1), 0.3, colors.HexColor("#e5e7eb")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING",   (0, 0), (-1, -1), 4),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
        ("ALIGN",      (2, 0), (2, -1), "RIGHT"),
    ]))
    right_col.append(findings_table)

    two_col = Table(
        [[left_col, right_col]],
        colWidths=[W * 0.46, W * 0.54],
    )
    two_col.setStyle(TableStyle([
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
        ("RIGHTPADDING", (0, 0), (0, -1), 8),
    ]))
    story.append(two_col)
    story.append(Spacer(1, 4 * mm))
    story.append(HRFlowable(width=W, thickness=0.5, color=LIGHT_GREY))
    story.append(Spacer(1, 3 * mm))

    # ── What You Get ─────────────────────────────────────────────────────────
    story.append(Paragraph(
        "WHAT YOU GET",
        s("Normal", fontSize=7.5, textColor=BRAND_ORANGE,
          fontName="Helvetica-Bold", spaceAfter=5),
    ))
    deliverables_data = [[
        "✅  Interactive Dashboard",
        "✅  PDF Report (board-ready)",
        "✅  Priority Recommendations",
        "✅  30-min Walkthrough Call",
    ]]
    deliverables_table = Table(deliverables_data, colWidths=[W / 4] * 4)
    deliverables_table.setStyle(TableStyle([
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
        ("BACKGROUND",    (0, 0), (-1, -1), LIGHT_GREY),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("GRID",          (0, 0), (-1, -1), 0.5, WHITE),
    ]))
    story.append(deliverables_table)
    story.append(Spacer(1, 4 * mm))
    story.append(HRFlowable(width=W, thickness=0.5, color=LIGHT_GREY))
    story.append(Spacer(1, 3 * mm))

    # ── How It Works ─────────────────────────────────────────────────────────
    story.append(Paragraph(
        "HOW IT WORKS",
        s("Normal", fontSize=7.5, textColor=BRAND_ORANGE,
          fontName="Helvetica-Bold", spaceAfter=5),
    ))
    hiw_data = []
    for num, title, detail in HOW_IT_WORKS:
        hiw_data.append([
            Paragraph(f'<font color="#f97316"><b>{num}</b></font>',
                      s("Normal", fontSize=14, alignment=TA_CENTER)),
            Paragraph(f"<b>{title}</b><br/>"
                      f'<font color="#6b7280">{detail}</font>',
                      s("Normal", fontSize=8)),
        ])
    hiw_table = Table(hiw_data, colWidths=[1 * cm, W - 1 * cm])
    hiw_table.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [WHITE, LIGHT_GREY]),
    ]))
    story.append(hiw_table)
    story.append(Spacer(1, 4 * mm))
    story.append(HRFlowable(width=W, thickness=0.5, color=LIGHT_GREY))
    story.append(Spacer(1, 3 * mm))

    # ── Security + Pricing footer ─────────────────────────────────────────────
    sec_text = (
        "<b>Security:</b> Read-only role — cannot start, stop, or modify any resource. "
        "ExternalId-protected. Open-source template. Fully deletable after engagement."
    )
    pricing_text = (
        "<b>Pricing:</b>  Fixed fee $500–$2,000 by account size  ·  "
        "or 20% of savings found (min $500)  ·  Monthly retainer from $200/mo"
    )
    footer_data = [[
        Paragraph(sec_text, s("Normal", fontSize=7.5, textColor=colors.HexColor("#374151"))),
        Paragraph(pricing_text, s("Normal", fontSize=7.5, textColor=colors.HexColor("#374151"))),
    ]]
    footer_table = Table(footer_data, colWidths=[W * 0.5, W * 0.5])
    footer_table.setStyle(TableStyle([
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
        ("RIGHTPADDING", (0, 0), (0, -1), 8),
    ]))
    story.append(footer_table)
    story.append(Spacer(1, 3 * mm))

    # ── CTA bar ───────────────────────────────────────────────────────────────
    cta_data = [[
        Paragraph(
            '<font color="white"><b>Ready to see what\'s in your account?</b>  '
            '[your@email.com]  ·  [calendly-link]</font>',
            s("Normal", fontSize=9, textColor=WHITE, alignment=TA_CENTER),
        )
    ]]
    cta_table = Table(cta_data, colWidths=[W])
    cta_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), BRAND_ORANGE),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(cta_table)

    doc.build(story)
    print(f"One-pager written to: {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate FinOps one-pager PDF")
    parser.add_argument("--out", default=".", help="Output directory (default: .)")
    args = parser.parse_args()
    build(Path(args.out) / "finops_audit_one_pager.pdf")


if __name__ == "__main__":
    main()
