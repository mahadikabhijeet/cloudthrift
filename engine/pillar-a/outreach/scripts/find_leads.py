#!/usr/bin/env python3
"""
Automated lead discovery via DuckDuckGo + Claude qualification.

Searches for companies matching your ICP and outputs a leads CSV
ready to feed into batch_pipeline.py.

Usage:
    # Find 20 leads in fintech (Series A-B, AWS, SaaS)
    python pillar-a/outreach/scripts/find_leads.py \
        --vertical fintech \
        --stage "Series A,Series B" \
        --count 20 \
        --output pillar-a/outreach/leads.csv

    # Find dev tools companies
    python pillar-a/outreach/scripts/find_leads.py \
        --vertical "developer tools" \
        --count 15

Requirements:
    pip install anthropic duckduckgo-search
    export ANTHROPIC_API_KEY=sk-ant-...

Note:
    This finds company NAMES from search results — it does not verify
    every data point. Run batch_pipeline.py afterwards for full research.
    Expected quality: ~50-70% of found companies will be truly relevant.
    Always review the CSV before running the full pipeline on all rows.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import anthropic
except ImportError:
    sys.exit("ERROR: pip install anthropic")

try:
    from duckduckgo_search import DDGS
except ImportError:
    sys.exit("ERROR: pip install duckduckgo-search")

_HERE     = Path(__file__).resolve().parent
_DOCS_DIR = _HERE.parent.parent / "docs"

# Search templates targeting companies likely to match ICP
SEARCH_TEMPLATES = [
    '"{stage}" "{vertical}" SaaS AWS infrastructure engineering',
    '"{stage}" "{vertical}" startup AWS cloud infrastructure 2024',
    'site:techcrunch.com "{stage}" "{vertical}" AWS',
    'site:venturebeat.com "{stage}" "{vertical}" cloud infrastructure',
    '"{vertical}" startup "{stage}" AWS engineering blog',
    'site:linkedin.com/jobs "{vertical}" "AWS" "Platform Engineer" "{stage}"',
]


def search_for_companies(vertical: str, stage: str, max_results_per_query: int = 5) -> list[dict]:
    """Run multiple search queries and collect raw results."""
    all_results: list[dict] = []
    stages = [s.strip() for s in stage.split(",")]

    for stage_term in stages:
        for template in SEARCH_TEMPLATES:
            query = template.format(stage=stage_term, vertical=vertical)
            try:
                with DDGS() as ddgs:
                    hits = list(ddgs.text(query, max_results=max_results_per_query))
                all_results.extend(hits)
                print(f"  [search] '{query[:60]}' → {len(hits)} results")
            except Exception as exc:
                print(f"  [search] Failed: {exc}")
            time.sleep(0.8)

    return all_results


def extract_companies_with_claude(
    client: anthropic.Anthropic,
    search_results: list[dict],
    vertical: str,
    stage: str,
    target_count: int,
) -> list[dict]:
    """Use Claude to extract company names + basic info from raw search results."""
    icp_md = (_DOCS_DIR / "ICP.md").read_text()

    results_text = "\n\n".join(
        f"[{r.get('title', '')}]\n{r.get('body', '')}\nURL: {r.get('href', '')}"
        for r in search_results[:50]   # cap context
    )

    system = """You are a lead extraction specialist. Given raw web search results,
extract company names that match the given ICP criteria.

Output ONLY a JSON array of objects. No other text.
Each object: {"company": "Name", "website": "https://...", "funding_stage": "Series B",
              "employee_count": "~80", "aws_signal": "brief evidence of AWS use",
              "source_url": "URL where you found this", "confidence": "high/medium/low"}

Rules:
- Only include companies with actual evidence of AWS usage
- Only include companies with evidence of the target funding stage
- Do not invent company names — only extract from the actual search results
- If you see the same company mentioned twice, include it once
- Mark confidence=low if you're unsure about any key fact
"""

    user = f"""Extract up to {target_count} companies from these search results.

Target: {stage} funded {vertical} companies that use AWS and likely have no dedicated FinOps team.

ICP (summary):
- 20-200 employees, 30%+ engineers
- AWS-native (EC2, RDS, ECS/EKS, Lambda)
- No Cloudability, Spot.io, CloudHealth, Harness
- Series A/B/C funded

Search results:
{results_text[:7000]}

Respond with a JSON array only."""

    print(f"  [claude] Extracting companies from {len(search_results)} search results...")
    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=3000,
        system=system,
        messages=[{"role": "user", "content": user}],
    )

    text = next(
        (b.text for b in reversed(response.content) if b.type == "text"),
        "[]",
    )
    match = re.search(r"\[[\s\S]*\]", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    print("  [claude] Could not parse JSON — returning empty list")
    return []


def write_csv(companies: list[dict], output_path: Path) -> None:
    """Write leads CSV in the format expected by batch_pipeline.py."""
    fieldnames = ["company", "website", "funding_stage", "employee_count",
                  "aws_signal", "confidence", "notes"]

    existing: list[dict] = []
    if output_path.exists():
        with open(output_path) as f:
            existing = list(csv.DictReader(f))
        existing_names = {r["company"].lower() for r in existing}
        companies = [c for c in companies if c.get("company", "").lower() not in existing_names]
        print(f"  [csv] Appending {len(companies)} new companies to existing {len(existing)}")
    else:
        print(f"  [csv] Writing {len(companies)} companies")

    with open(output_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        if not existing:
            writer.writeheader()
        for c in companies:
            writer.writerow({
                "company":       c.get("company", ""),
                "website":       c.get("website", ""),
                "funding_stage": c.get("funding_stage", ""),
                "employee_count":c.get("employee_count", ""),
                "aws_signal":    c.get("aws_signal", ""),
                "confidence":    c.get("confidence", ""),
                "notes":         c.get("source_url", ""),
            })


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Discover leads matching your ICP via DuckDuckGo + Claude",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--vertical", default="SaaS",
                        help="Target vertical (fintech, healthtech, 'developer tools', etc.)")
    parser.add_argument("--stage", default="Series A,Series B",
                        help="Funding stages, comma-separated (default: 'Series A,Series B')")
    parser.add_argument("--count", type=int, default=20,
                        help="Target number of companies to find (default: 20)")
    parser.add_argument("--output", default="pillar-a/outreach/leads.csv",
                        help="Output CSV path (appends to existing file)")
    args = parser.parse_args()

    client = anthropic.Anthropic()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*55}")
    print(f"  FinOps Lead Discovery")
    print(f"  Vertical : {args.vertical}")
    print(f"  Stage    : {args.stage}")
    print(f"  Target   : {args.count} companies")
    print(f"  Output   : {output_path}")
    print(f"{'='*55}\n")

    print("[1/3] Searching the web...")
    raw = search_for_companies(args.vertical, args.stage)
    print(f"      Found {len(raw)} raw search results")

    print("[2/3] Extracting companies with Claude...")
    companies = extract_companies_with_claude(
        client, raw, args.vertical, args.stage, args.count
    )
    print(f"      Extracted {len(companies)} companies")

    print("[3/3] Writing CSV...")
    write_csv(companies, output_path)

    print(f"\n{'='*55}")
    print(f"  Done. {len(companies)} companies added to {output_path}")
    print(f"")
    print(f"  Next steps:")
    print(f"  1. Review the CSV — remove any that don't fit")
    print(f"  2. Run the full research pipeline:")
    print(f"     python pillar-a/outreach/scripts/batch_pipeline.py \\")
    print(f"       --input {output_path} \\")
    print(f"       --output pillar-a/outreach/output/")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    main()
