#!/usr/bin/env python3
"""
Research a single company and generate personalized outreach emails.

Usage:
    python pillar-a/outreach/scripts/research_lead.py "Acme Corp" --url https://acme.com
    python pillar-a/outreach/scripts/research_lead.py "Acme Corp" --url https://acme.com --output ./output

Output (in --output directory):
    acme-corp_research.json   — full research + ICP score (review for accuracy)
    acme-corp_emails.md       — 3 personalised email variants, ready to edit + send

Requirements:
    pip install anthropic ddgs requests beautifulsoup4 lxml
    export ANTHROPIC_API_KEY=sk-ant-...

Estimated cost: $0.08–$0.20 per company (Claude Opus 4.7 with adaptive thinking)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── Dependency check ─────────────────────────────────────────────────────────
try:
    import anthropic
except ImportError:
    sys.exit("ERROR: pip install anthropic")

try:
    # Library was renamed from duckduckgo_search to ddgs in 2025
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS
except ImportError:
    sys.exit("ERROR: pip install ddgs")

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("ERROR: pip install requests beautifulsoup4 lxml")

# ── Paths ─────────────────────────────────────────────────────────────────────
_HERE        = Path(__file__).resolve().parent
_PROMPTS_DIR = _HERE.parent / "prompts"
_DOCS_DIR    = _HERE.parent.parent / "docs"


# ── Web utilities ─────────────────────────────────────────────────────────────

def ddg_search(query: str, max_results: int = 4) -> list[dict]:
    """DuckDuckGo search — free, no API key."""
    try:
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results))
    except Exception as exc:
        print(f"  [search] '{query[:50]}...' failed: {exc}")
        return []


def scrape(url: str, max_chars: int = 6000) -> str:
    """Scrape and return visible text from a URL."""
    try:
        resp = requests.get(
            url, timeout=12,
            headers={"User-Agent": "Mozilla/5.0 (research bot; not archiving)"},
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        return text[:max_chars]
    except Exception as exc:
        return f"[scrape failed: {exc}]"


def collect_raw_data(company: str, url: str = "") -> dict:
    """Run web searches and optionally scrape the website."""
    queries = [
        f"{company} AWS infrastructure engineering blog tech stack",
        f"{company} funding Series round employees Crunchbase",
        f"{company} CTO VP Engineering infrastructure LinkedIn",
        f"{company} Spot.io OR Cloudability OR CloudHealth OR Harness FinOps",
        f"site:linkedin.com/jobs {company} AWS DevOps Platform Engineer SRE",
    ]

    results: list[str] = []
    for i, q in enumerate(queries):
        hits = ddg_search(q, max_results=3)
        for h in hits:
            results.append(
                f"[{h.get('title', '')}]\n{h.get('body', '')}\nURL: {h.get('href', '')}"
            )
        if i < len(queries) - 1:
            time.sleep(0.8)   # rate-limit DuckDuckGo

    website_text = scrape(url) if url else ""

    return {
        "search_results": "\n\n".join(results),
        "website_text":   website_text,
    }


# ── Claude calls ──────────────────────────────────────────────────────────────

def research_with_claude(
    client: anthropic.Anthropic,
    company: str,
    url: str,
    raw: dict,
) -> dict:
    """Send raw data to Claude for analysis. Returns parsed JSON research dict."""
    system_prompt = (_PROMPTS_DIR / "01_research_company.md").read_text()
    icp_md        = (_DOCS_DIR / "ICP.md").read_text()

    user_msg = f"""Company: {company}
Website: {url or "not provided"}

=== WEB SEARCH RESULTS ===
{raw["search_results"][:6000]}

=== WEBSITE TEXT ===
{raw["website_text"][:3000]}

=== ICP CRITERIA (reference) ===
{icp_md[:1500]}

Analyse the company and respond with a single valid JSON object as specified in your instructions.
Do not include any text before or after the JSON."""

    print("  [claude] Researching + qualifying...")
    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=3000,
        thinking={"type": "adaptive"},
        system=system_prompt,
        messages=[{"role": "user", "content": user_msg}],
    )

    # Last content block is the text answer (after thinking blocks)
    text = next(
        (b.text for b in reversed(response.content) if b.type == "text"),
        "",
    )

    # Extract JSON from the response
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError as exc:
            print(f"  [claude] JSON parse failed: {exc}")
    return {"raw_analysis": text, "company": company, "qualify": "maybe", "icp_score": 0}


def generate_emails_with_claude(
    client: anthropic.Anthropic,
    research: dict,
) -> str:
    """Generate personalised email variants from the research JSON."""
    system_prompt = (_PROMPTS_DIR / "04_generate_email.md").read_text()
    templates_md  = (_DOCS_DIR / "OUTREACH_TEMPLATES.md").read_text()

    user_msg = f"""Research findings for {research.get("company", "this company")}:

{json.dumps(research, indent=2)[:4000]}

Reference templates (for tone and structure):
{templates_md[:2000]}

Generate 3 personalised email variants following the output format in your instructions.
Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d")}"""

    print("  [claude] Generating personalised emails...")
    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=2500,
        system=system_prompt,
        messages=[{"role": "user", "content": user_msg}],
    )

    return next(
        (b.text for b in reversed(response.content) if b.type == "text"),
        "[email generation failed]",
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Research a company and generate personalized outreach",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("company", help="Company name (e.g. 'Acme Corp')")
    parser.add_argument("--url",    default="", help="Company website URL")
    parser.add_argument("--output", default=".", help="Output directory (default: .)")
    parser.add_argument("--skip-email", action="store_true",
                        help="Only do research, skip email generation")
    parser.add_argument("--min-score", type=int, default=0,
                        help="Skip email generation if ICP score below this")
    args = parser.parse_args()

    client     = anthropic.Anthropic()
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    slug       = slugify(args.company)

    print(f"\n{'='*55}")
    print(f"  FinOps Lead Research — {args.company}")
    print(f"{'='*55}\n")

    # Step 1: Web research
    print("[1/3] Collecting web data (DuckDuckGo + scrape)...")
    raw = collect_raw_data(args.company, args.url)
    print(f"      {len(raw['search_results'])} chars of search results"
          f" + {len(raw['website_text'])} chars website text")

    # Step 2: Claude analysis
    print("[2/3] Analysing with Claude Opus 4.7...")
    research = research_with_claude(client, args.company, args.url, raw)

    icp_score = research.get("icp_score", 0)
    qualify   = research.get("qualify", "unknown")
    print(f"      ICP Score: {icp_score}/12  |  Qualify: {qualify.upper()}")

    research_path = output_dir / f"{slug}_research.json"
    research_path.write_text(json.dumps(research, indent=2, default=str))
    print(f"      Saved → {research_path}")

    # Step 3: Email generation
    if args.skip_email:
        print("[3/3] Email generation skipped (--skip-email)")
    elif icp_score < args.min_score:
        print(f"[3/3] Email skipped — score {icp_score} below threshold {args.min_score}")
    elif qualify == "no":
        print(f"[3/3] Email skipped — qualify = no")
    else:
        print("[3/3] Generating personalised emails...")
        emails = generate_emails_with_claude(client, research)
        email_path = output_dir / f"{slug}_emails.md"
        email_path.write_text(emails)
        print(f"      Saved → {email_path}")

    print(f"\n{'='*55}")
    print(f"  Done. Review output before sending:")
    print(f"  1. Open {slug}_research.json — verify facts")
    print(f"  2. Open {slug}_emails.md — edit first sentence")
    print(f"  3. Verify contact email (hunter.io / LinkedIn)")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    main()
