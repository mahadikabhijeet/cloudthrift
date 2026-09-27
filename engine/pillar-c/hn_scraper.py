"""
Pillar C — HN "Who is Hiring" Scraper  (Task 7 — zero cost)

Hacker News publishes a monthly "Ask HN: Who is hiring?" thread.
Every comment is a company pitch, and companies that mention AWS, Terraform,
Kubernetes, or cloud-cost tooling are strong FinOps prospects.

This scraper:
  1. Finds the latest "Who is Hiring" post via the Algolia HN API (free, no key needed)
  2. Pulls all comments and filters for AWS/cloud signals
  3. Extracts company name, website, stack signals, and remote/location info
  4. Returns RawLead objects compatible with llm_validator.py

Cost: $0.00 — Algolia HN API is completely free and unauthenticated.
Rate limit: generous; 1000+ req/day with no auth.
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

HN_ALGOLIA_BASE   = "https://hn.algolia.com/api/v1"
SEARCH_ENDPOINT   = f"{HN_ALGOLIA_BASE}/search"
ITEMS_ENDPOINT    = f"{HN_ALGOLIA_BASE}/items"

# Keywords that confirm AWS/cloud usage in a job posting
AWS_SIGNALS = [
    "aws", "amazon web services", "ec2", "s3", "eks", "ecs", "lambda",
    "cloudfront", "rds", "dynamodb", "sagemaker", "terraform", "pulumi",
    "cloudformation", "kubernetes", "k8s", "finops", "cloud cost",
    "cost optimisation", "cost optimization", "datadog", "grafana",
    "newrelic", "observability",
]

# Minimum number of AWS signal words needed to qualify a posting
MIN_SIGNAL_COUNT = 2


@dataclass
class RawLead:
    company_name: str
    website: str = ""
    linkedin_url: str = ""
    employee_count: str = ""
    industry: str = ""
    tech_signals: list[str] = field(default_factory=list)
    source: str = ""
    raw_snippet: str = ""


class HNScraper:
    """
    Scrapes the most recent HN 'Who is Hiring' post for AWS-signal companies.

    Usage:
        scraper = HNScraper()
        leads   = scraper.run()
        scraper.save(leads)
    """

    def __init__(self, months_back: int = 1) -> None:
        self.months_back = months_back   # how many recent posts to scan

    def run(self) -> list[RawLead]:
        post_ids = self._find_hiring_posts()
        if not post_ids:
            print("[hn_scraper] No 'Who is Hiring' posts found")
            return []

        leads: list[RawLead] = []
        seen: set[str] = set()

        for post_id in post_ids[:self.months_back]:
            print(f"[hn_scraper] Scanning HN post {post_id}...")
            comments = self._fetch_comments(post_id)
            print(f"[hn_scraper] {len(comments)} top-level comments found")
            for comment in comments:
                lead = self._parse_comment(comment)
                if lead and lead.company_name.lower() not in seen:
                    seen.add(lead.company_name.lower())
                    leads.append(lead)
            time.sleep(0.2)

        print(f"[hn_scraper] {len(leads)} qualified leads extracted")
        return leads

    def save(self, leads: list[RawLead], output_dir: str = ".") -> Path:
        date_str = datetime.now().strftime("%Y%m%d_%H%M")
        path = Path(output_dir) / f"leads_hn_{date_str}.json"
        path.write_text(json.dumps([asdict(l) for l in leads], indent=2))
        print(f"[hn_scraper] Saved {len(leads)} leads → {path}")
        return path

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _find_hiring_posts(self) -> list[str]:
        """Return the object IDs of recent 'Ask HN: Who is hiring?' posts."""
        params = urllib.parse.urlencode({
            "query":  "Ask HN: Who is hiring?",
            "tags":   "story,ask_hn",
            "hitsPerPage": 5,
        })
        data = _get_json(f"{SEARCH_ENDPOINT}?{params}")
        ids  = [hit["objectID"] for hit in data.get("hits", [])
                if "who is hiring" in hit.get("title", "").lower()]
        return ids

    def _fetch_comments(self, post_id: str) -> list[dict]:
        """Fetch the full comment tree for a post. Returns top-level comments only."""
        data = _get_json(f"{ITEMS_ENDPOINT}/{post_id}")
        return [c for c in data.get("children", []) if c.get("text")]

    def _parse_comment(self, comment: dict) -> RawLead | None:
        """
        Extract a RawLead from a single HN comment.

        HN hiring posts follow a loose convention:
          <Company name> | <location> | <remote?> | <stack...>
          <job description with tech mentions>

        We extract:
          - Company name from the first pipe-delimited segment or first line
          - Website from any URL in the comment
          - Tech signals from AWS keyword matches
        """
        raw_text = _strip_html(comment.get("text", ""))
        if not raw_text:
            return None

        # Count AWS/cloud signals
        text_lower = raw_text.lower()
        matched_signals = [s for s in AWS_SIGNALS if s in text_lower]
        if len(matched_signals) < MIN_SIGNAL_COUNT:
            return None

        company_name = _extract_company_name(raw_text)
        if not company_name:
            return None

        website = _extract_url(raw_text)

        return RawLead(
            company_name=company_name,
            website=website,
            linkedin_url="",
            employee_count="",
            industry="",
            tech_signals=matched_signals,
            source=f"hn:who_is_hiring:{comment.get('story_id', 'unknown')}",
            raw_snippet=raw_text[:300],
        )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _get_json(url: str, retries: int = 3) -> dict:
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "FinOpsPlatform/1.0 (github.com/finops-platform)"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except Exception as exc:
            if attempt == retries - 1:
                print(f"[hn_scraper] Request failed after {retries} attempts: {url} — {exc}")
                return {}
            time.sleep(1.5 ** attempt)
    return {}


def _strip_html(text: str) -> str:
    """Remove HTML tags and decode common entities."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace(
        "&gt;", ">").replace("&#x2F;", "/").replace("&quot;", '"')
    return re.sub(r"\s+", " ", text).strip()


def _extract_company_name(text: str) -> str:
    """
    HN posts usually open with:  CompanyName | Remote | Stack
    Fallback: first non-empty line that isn't a URL.
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return ""

    first_line = lines[0]

    # Pipe-delimited format
    if "|" in first_line:
        candidate = first_line.split("|")[0].strip()
        if 2 < len(candidate) < 80 and not candidate.startswith("http"):
            return candidate

    # Fall back to the first line if it's short enough to be a company name
    if 2 < len(first_line) < 60 and not first_line.startswith("http"):
        return first_line

    return ""


def _extract_url(text: str) -> str:
    """Return the first https URL found in the text, favouring non-HN URLs."""
    urls = re.findall(r"https?://[^\s\"'<>]+", text)
    for url in urls:
        if "ycombinator.com" not in url and "hacker" not in url:
            return url.rstrip(".,)")
    return ""
