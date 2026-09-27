#!/usr/bin/env python3
"""
Batch process a CSV of companies through the research + email pipeline.

Usage:
    python pillar-a/outreach/scripts/batch_pipeline.py \
        --input pillar-a/outreach/leads.csv \
        --output pillar-a/outreach/output/ \
        --min-score 7

CSV format (see leads_template.csv):
    company,website,funding_stage,employee_count,notes

Output per company:
    output/<slug>_research.json
    output/<slug>_emails.md

Summary:
    output/batch_summary.md    — table of all companies with scores + status

Requirements:
    Same as research_lead.py (anthropic, duckduckgo-search, requests, beautifulsoup4)
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Make research_lead importable
sys.path.insert(0, str(Path(__file__).resolve().parent))
import research_lead as rl


def run_batch(
    input_csv: Path,
    output_dir: Path,
    min_score:  int,
    delay_s:    float,
    skip_existing: bool,
) -> None:
    import anthropic
    client = anthropic.Anthropic()
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = list(csv.DictReader(input_csv.read_text().splitlines()))
    total = len(rows)
    print(f"\n{'='*60}")
    print(f"  FinOps Lead Batch Pipeline")
    print(f"  Companies : {total}")
    print(f"  Min score : {min_score}/12")
    print(f"  Output    : {output_dir}")
    print(f"{'='*60}\n")

    summary: list[dict] = []

    for i, row in enumerate(rows, 1):
        company = row.get("company", "").strip()
        url     = row.get("website", "").strip()
        if not company:
            continue

        slug = rl.slugify(company)
        research_path = output_dir / f"{slug}_research.json"

        print(f"[{i:>3}/{total}] {company}")

        if skip_existing and research_path.exists():
            print(f"        Skipping — already processed (use --no-skip to rerun)")
            import json
            existing = json.loads(research_path.read_text())
            summary.append({
                "company":   company,
                "icp_score": existing.get("icp_score", "?"),
                "qualify":   existing.get("qualify", "?"),
                "contact":   _contact_name(existing),
                "status":    "skipped (existing)",
            })
            continue

        try:
            # Step 1: collect web data
            raw = rl.collect_raw_data(company, url)

            # Step 2: research + qualify
            research = rl.research_with_claude(client, company, url, raw)
            research_path.write_text(
                __import__("json").dumps(research, indent=2, default=str)
            )

            icp_score = research.get("icp_score", 0)
            qualify   = research.get("qualify", "unknown")
            print(f"        Score: {icp_score}/12 | Qualify: {qualify.upper()}")

            # Step 3: generate emails if qualified
            email_status = "skipped (score)"
            if qualify != "no" and icp_score >= min_score:
                emails = rl.generate_emails_with_claude(client, research)
                email_path = output_dir / f"{slug}_emails.md"
                email_path.write_text(emails)
                email_status = "emails generated"

            summary.append({
                "company":   company,
                "icp_score": icp_score,
                "qualify":   qualify,
                "contact":   _contact_name(research),
                "status":    email_status,
            })

        except Exception as exc:
            print(f"        ERROR: {exc}")
            summary.append({
                "company":   company,
                "icp_score": "ERR",
                "qualify":   "error",
                "contact":   "",
                "status":    f"error: {exc}",
            })

        if i < total:
            print(f"        Waiting {delay_s:.0f}s before next company...")
            time.sleep(delay_s)

    # Write summary
    _write_summary(output_dir, summary)
    print(f"\nBatch complete. Summary → {output_dir}/batch_summary.md\n")


def _contact_name(research: dict) -> str:
    contacts = research.get("contacts", [])
    if contacts and contacts[0].get("name"):
        return f"{contacts[0]['name']} ({contacts[0].get('title', '')})"
    return "not found"


def _write_summary(output_dir: Path, summary: list[dict]) -> None:
    lines = [
        "# Batch Research Summary",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "| # | Company | Score | Qualify | Contact | Status |",
        "|---|---------|-------|---------|---------|--------|",
    ]
    for i, row in enumerate(summary, 1):
        lines.append(
            f"| {i} "
            f"| {row['company']} "
            f"| {row['icp_score']}/12 "
            f"| {row['qualify'].upper()} "
            f"| {row['contact']} "
            f"| {row['status']} |"
        )

    qualified = [r for r in summary if isinstance(r["icp_score"], int) and r["icp_score"] >= 7]
    lines += [
        "",
        f"**Total processed:** {len(summary)}  ",
        f"**Qualified (score ≥ 7):** {len(qualified)}  ",
        f"**Emails generated:** {sum(1 for r in summary if r['status'] == 'emails generated')}",
    ]

    (output_dir / "batch_summary.md").write_text("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Batch research + email generation for a CSV of leads",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--input",  required=True,  help="Input CSV file")
    parser.add_argument("--output", default="output", help="Output directory")
    parser.add_argument("--min-score", type=int, default=7,
                        help="Min ICP score to generate emails (default: 7)")
    parser.add_argument("--delay",  type=float, default=15,
                        help="Seconds between companies (default: 15, avoids rate limits)")
    parser.add_argument("--no-skip", action="store_true",
                        help="Re-process companies even if output file already exists")
    args = parser.parse_args()

    run_batch(
        input_csv     = Path(args.input),
        output_dir    = Path(args.output),
        min_score     = args.min_score,
        delay_s       = args.delay,
        skip_existing = not args.no_skip,
    )


if __name__ == "__main__":
    main()
