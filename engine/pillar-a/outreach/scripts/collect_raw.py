#!/usr/bin/env python3
"""
Collect raw web data for a company — no Claude API, no API credits needed.
Outputs a paste-ready text block for your Claude Project research workflow.

Usage:
    python3 collect_raw.py "RemotePass" --url https://remotepass.com
    python3 collect_raw.py "Medallion"  --url https://medallion.co
    python3 collect_raw.py "Hightouch"  --url https://hightouch.com

Output:
    Saves output/remotepass_raw.txt  (paste this into your Claude Project)
    Also prints the file path so you know where to find it.

Requirements (no Anthropic SDK needed):
    pip install ddgs requests beautifulsoup4 lxml
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# ── Dependency check ──────────────────────────────────────────────────────────
try:
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


# ── Web utilities ─────────────────────────────────────────────────────────────

def ddg_search(query: str, max_results: int = 4) -> list[dict]:
    try:
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results))
    except Exception as exc:
        print(f"  [search] warning: '{query[:50]}' — {exc}")
        return []


def scrape(url: str, max_chars: int = 6000) -> str:
    try:
        resp = requests.get(
            url, timeout=12,
            headers={"User-Agent": "Mozilla/5.0 (compatible; research-bot)"},
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        return text[:max_chars]
    except Exception as exc:
        return f"[scrape failed: {exc}]"


# ── Main collector ─────────────────────────────────────────────────────────────

def collect(company: str, url: str = "", notes: str = "") -> str:
    """Run searches + scrape and return a paste-ready text block."""
    print(f"\n{'='*55}")
    print(f"  Collecting data for: {company}")
    print(f"{'='*55}\n")

    queries = [
        f"{company} AWS infrastructure engineering blog tech stack",
        f"{company} funding round raised employees Crunchbase 2024 2025",
        f"{company} CTO VP Engineering Head of Infrastructure LinkedIn",
        f"{company} Spot.io OR Cloudability OR CloudHealth OR Harness FinOps cloud cost",
        f"site:linkedin.com/jobs {company} AWS DevOps Platform SRE engineer",
    ]

    search_blocks: list[str] = []
    for i, q in enumerate(queries):
        print(f"  [{i+1}/5] Searching: {q[:60]}...")
        hits = ddg_search(q, max_results=3)
        for h in hits:
            search_blocks.append(
                f"[{h.get('title', '')}]\n"
                f"{h.get('body', '')}\n"
                f"URL: {h.get('href', '')}"
            )
        if i < len(queries) - 1:
            time.sleep(0.8)

    website_text = ""
    if url:
        print(f"  [6/6] Scraping: {url} ...")
        website_text = scrape(url)

    search_combined = "\n\n".join(search_blocks)
    total_chars = len(search_combined) + len(website_text)
    print(f"\n  Done — {len(search_blocks)} search snippets + {len(website_text):,} website chars ({total_chars:,} total)\n")

    # ── Build paste-ready block ────────────────────────────────────────────────
    lines = [
        f"Company: {company}",
        f"Website: {url or 'not provided'}",
    ]
    if notes:
        lines.append(f"Additional context: {notes}")

    lines += [
        "",
        "=== WEB SEARCH RESULTS ===",
        search_combined[:6000],
        "",
        "=== WEBSITE TEXT ===",
        website_text[:3000],
        "",
        "=== TASK ===",
        "Analyse the company and respond with a single valid JSON object as specified "
        "in your instructions. Do not include any text before or after the JSON.",
    ]

    return "\n".join(lines)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect raw research data — paste output into Claude Project",
    )
    parser.add_argument("company", help="Company name, e.g. 'RemotePass'")
    parser.add_argument("--url", default="", help="Company website URL")
    parser.add_argument("--notes", default="",
                        help="Extra context (funding date, specific hook, etc.)")
    parser.add_argument("--output", default="pillar-a/outreach/output",
                        help="Directory to save the raw text file (default: pillar-a/outreach/output)")
    args = parser.parse_args()

    raw_text = collect(args.company, args.url, args.notes)

    # Save to file
    slug = args.company.lower().replace(" ", "-").replace("/", "-")
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{slug}_raw.txt"
    out_path.write_text(raw_text, encoding="utf-8")

    print(f"{'='*55}")
    print(f"  Raw data saved to: {out_path}")
    print(f"{'='*55}")
    print()
    print("  NEXT STEP — paste the file content into your Claude Project:")
    print()
    print(f"    cat '{out_path}'")
    print()
    print("  Then copy-paste the output into your Claude Project chat.")
    print("  Claude will respond with the research JSON.")
    print()


if __name__ == "__main__":
    main()
