"""
Pillar C — Lead Scraper

Discovers companies running AWS workloads that are likely overspending on cloud.

Sources:
  1. Job postings — JSearch API (RapidAPI): searches Indeed, LinkedIn, Glassdoor, ZipRecruiter.
     High volume of AWS/FinOps/cloud-cost postings strongly signals both AWS usage and cost pain.

  2. LinkedIn company search — Apify LinkedIn Company Search actor.
     Finds companies in target industries with employee counts in our sweet spot (50–2000).

Required environment variables:
  RAPIDAPI_KEY      — RapidAPI key (https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch)
  APIFY_API_TOKEN   — Apify API token (https://apify.com — free tier is enough to start)

Output: list of RawLead written to leads_raw_<date>.json for llm_validator.py.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

# JSearch queries — chosen to signal AWS usage AND cost pressure simultaneously
JOB_QUERIES = [
    "FinOps engineer",
    "cloud cost optimisation AWS",
    "AWS infrastructure cost",
    "cloud platform engineer AWS",
    "DevOps AWS Terraform",
]

# Apify LinkedIn Company Search actor
APIFY_LINKEDIN_COMPANY_ACTOR = "curious_coder~linkedin-company-search"
APIFY_POLL_INTERVAL_S = 8
APIFY_MAX_POLLS = 45   # 45 × 8s = 6 min timeout

# Companies with this many employees are most likely to have real cloud spend
# but small enough to move fast and lack an in-house FinOps team
MIN_EMPLOYEES = 50
MAX_EMPLOYEES = 2000


@dataclass
class RawLead:
    company_name: str
    website: str = ""
    linkedin_url: str = ""
    employee_count: str = ""
    industry: str = ""
    tech_signals: list[str] = field(default_factory=list)
    source: str = ""


class LeadScraper:
    """
    Discovers potential FinOps clients from job postings and LinkedIn.

    Usage:
        scraper = LeadScraper()
        leads   = scraper.run()
        path    = scraper.save()
    """

    def __init__(
        self,
        target_industries: list[str] | None = None,
        max_per_source: int = 100,
    ) -> None:
        self.target_industries = target_industries or [
            "SaaS", "Fintech", "E-commerce", "HealthTech", "EdTech",
            "Logistics", "Gaming", "Media",
        ]
        self.max_per_source = max_per_source
        self._leads: list[RawLead] = []
        self._seen_companies: set[str] = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, sources: list[str] | None = None) -> list[RawLead]:
        """
        Run all (or a subset of) scrapers and return deduplicated leads.

        Args:
            sources: ["jobs", "linkedin"] or None for all.
        """
        self._leads = []
        self._seen_companies = set()
        active = set(sources or ["jobs", "linkedin"])

        if "jobs" in active:
            print("[lead_scraper] Fetching from job postings (JSearch)...")
            self._fetch_from_job_postings()
            print(f"[lead_scraper] Job postings done — {len(self._leads)} leads so far")

        if "linkedin" in active:
            print("[lead_scraper] Fetching from LinkedIn (Apify)...")
            self._fetch_from_linkedin()
            print(f"[lead_scraper] LinkedIn done — {len(self._leads)} leads total")

        return self._leads

    def save(self, output_dir: str = ".") -> Path:
        date_str = datetime.now().strftime("%Y%m%d_%H%M")
        path = Path(output_dir) / f"leads_raw_{date_str}.json"
        path.write_text(json.dumps([asdict(l) for l in self._leads], indent=2))
        print(f"[lead_scraper] Saved {len(self._leads)} raw leads → {path}")
        return path

    # ------------------------------------------------------------------
    # Source 1: Job postings via JSearch (RapidAPI)
    # ------------------------------------------------------------------

    def _fetch_from_job_postings(self) -> None:
        """
        Search job boards via JSearch for AWS/FinOps job postings.

        Each unique employer found is treated as a potential lead.
        The query itself becomes a tech signal (e.g. "FinOps engineer" → company is FinOps-aware).

        Required env var: RAPIDAPI_KEY
        """
        api_key = os.environ.get("RAPIDAPI_KEY", "")
        if not api_key:
            raise EnvironmentError(
                "RAPIDAPI_KEY is not set. "
                "Get a free key at https://rapidapi.com and subscribe to JSearch."
            )

        for query in JOB_QUERIES:
            self._jsearch_query(api_key, query)
            time.sleep(0.5)   # stay within free-tier rate limit

    def _jsearch_query(self, api_key: str, query: str) -> None:
        """Fetch one page of JSearch results and extract employer leads."""
        params = urllib.parse.urlencode({
            "query":      query,
            "page":       "1",
            "num_pages":  "3",          # up to 30 results per query
            "date_posted": "month",
            "employment_types": "FULLTIME",
        })
        req = urllib.request.Request(
            f"https://jsearch.p.rapidapi.com/search?{params}",
            headers={
                "X-RapidAPI-Key":  api_key,
                "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            print(f"[lead_scraper] JSearch error for '{query}': {exc.code} {exc.reason}")
            return

        for job in data.get("data", []):
            employer = (job.get("employer_name") or "").strip()
            if not employer:
                continue

            normalised = employer.lower()
            if normalised in self._seen_companies:
                # Existing lead — enrich tech_signals with this new query
                for lead in self._leads:
                    if lead.company_name.lower() == normalised:
                        if query not in lead.tech_signals:
                            lead.tech_signals.append(query)
                continue

            self._seen_companies.add(normalised)
            self._leads.append(RawLead(
                company_name=employer,
                website=_clean_url(job.get("employer_website", "")),
                linkedin_url=_clean_url(job.get("employer_linkedin", "")),
                employee_count="",
                industry="",
                tech_signals=[query],
                source=f"jsearch:{query}",
            ))

            if len(self._leads) >= self.max_per_source:
                return

    # ------------------------------------------------------------------
    # Source 2: LinkedIn company search via Apify
    # ------------------------------------------------------------------

    def _fetch_from_linkedin(self) -> None:
        """
        Discover companies in target industries using the Apify LinkedIn
        Company Search actor (curious_coder~linkedin-company-search).

        The actor searches LinkedIn's company directory and returns structured
        company profiles including employee count, industry, and website.

        Required env var: APIFY_API_TOKEN
        """
        api_token = os.environ.get("APIFY_API_TOKEN", "")
        if not api_token:
            raise EnvironmentError(
                "APIFY_API_TOKEN is not set. "
                "Create a free account at https://apify.com and copy your token "
                "from https://console.apify.com/account/integrations."
            )

        # Build search queries: one per target industry to keep results focused
        search_queries = [
            f"{industry} company AWS cloud" for industry in self.target_industries
        ]

        run_input = {
            "searchQueries": search_queries,
            "maxResults":    self.max_per_source,
            "proxy":         {"useApifyProxy": True},
        }

        # Start the actor run
        run_id, dataset_id = self._apify_start_run(
            api_token, APIFY_LINKEDIN_COMPANY_ACTOR, run_input
        )

        # Wait for the run to finish
        status = self._apify_wait_for_run(api_token, run_id)
        if status != "SUCCEEDED":
            print(f"[lead_scraper] Apify run {run_id} ended with status: {status}")
            return

        # Pull the dataset items
        items = self._apify_fetch_dataset(api_token, dataset_id)
        print(f"[lead_scraper] Apify returned {len(items)} LinkedIn companies")

        for item in items:
            name = (item.get("name") or item.get("companyName") or "").strip()
            if not name:
                continue

            normalised = name.lower()
            if normalised in self._seen_companies:
                continue

            # Filter by employee count if available
            emp = item.get("employeeCount") or item.get("staffCount") or 0
            if isinstance(emp, int) and emp > 0:
                if emp < MIN_EMPLOYEES or emp > MAX_EMPLOYEES:
                    continue

            self._seen_companies.add(normalised)
            self._leads.append(RawLead(
                company_name=name,
                website=_clean_url(item.get("website", "")),
                linkedin_url=_clean_url(item.get("url", item.get("linkedinUrl", ""))),
                employee_count=str(emp) if emp else "",
                industry=item.get("industry", item.get("industries", [""])[0] if isinstance(item.get("industries"), list) else ""),
                tech_signals=["linkedin_company_search"],
                source="apify:linkedin_company",
            ))

    # ------------------------------------------------------------------
    # Apify helpers
    # ------------------------------------------------------------------

    def _apify_start_run(
        self, api_token: str, actor_id: str, run_input: dict
    ) -> tuple[str, str]:
        """Start an Apify actor run. Returns (run_id, dataset_id)."""
        payload = json.dumps(run_input).encode()
        req = urllib.request.Request(
            f"https://api.apify.com/v2/acts/{actor_id}/runs",
            data=payload,
            headers={
                "Authorization": f"Bearer {api_token}",
                "Content-Type":  "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())

        run_id    = data["data"]["id"]
        dataset_id = data["data"]["defaultDatasetId"]
        print(f"[lead_scraper] Apify run started: {run_id}")
        return run_id, dataset_id

    def _apify_wait_for_run(self, api_token: str, run_id: str) -> str:
        """Poll until the Apify run finishes. Returns the final status string."""
        terminal = {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}
        for poll in range(APIFY_MAX_POLLS):
            time.sleep(APIFY_POLL_INTERVAL_S)
            req = urllib.request.Request(
                f"https://api.apify.com/v2/actor-runs/{run_id}",
                headers={"Authorization": f"Bearer {api_token}"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            status = data["data"]["status"]
            if status in terminal:
                return status
            if poll % 5 == 0:
                print(f"[lead_scraper] Apify run {run_id}: {status} (poll {poll})")
        return "TIMED-OUT"

    def _apify_fetch_dataset(self, api_token: str, dataset_id: str) -> list[dict]:
        """Fetch all items from an Apify dataset."""
        req = urllib.request.Request(
            f"https://api.apify.com/v2/datasets/{dataset_id}/items"
            "?format=json&clean=true",
            headers={"Authorization": f"Bearer {api_token}"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _clean_url(url: str) -> str:
    """Normalise a URL — strip trailing slashes and ensure https://."""
    url = (url or "").strip().rstrip("/")
    if url and not url.startswith("http"):
        url = "https://" + url
    return url
