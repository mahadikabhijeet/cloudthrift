"""
Pillar C — Decision Maker Finder

Given a validated lead (company), finds the right person to contact:
  - VP / Director of Engineering or Infrastructure
  - Head of FinOps / Cloud Operations
  - CTO at companies < 200 employees

Pipeline:
  1. LinkedIn people search (Apify) — finds profiles at the company matching target titles
  2. Hunter.io email finder        — resolves a verified work email for each contact

Required environment variables:
  APIFY_API_TOKEN   — Apify API token (https://console.apify.com/account/integrations)
  HUNTER_API_KEY    — Hunter.io API key (https://hunter.io/api-keys)
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass

# Ordered from most to least senior — we stop at the first title found per company
TARGET_TITLES = [
    "CTO",
    "VP Engineering",
    "VP of Engineering",
    "VP Infrastructure",
    "VP of Infrastructure",
    "Head of FinOps",
    "Head of Cloud",
    "Director of Engineering",
    "Director of Cloud",
    "Director of Infrastructure",
    "Head of Cloud Operations",
    "Principal Cloud Engineer",
]

# Apify LinkedIn People Search actor
APIFY_LINKEDIN_PEOPLE_ACTOR = "curious_coder~linkedin-profile-scraper"
APIFY_POLL_INTERVAL_S = 8
APIFY_MAX_POLLS = 45

# Hunter.io: only return emails above this confidence threshold
HUNTER_MIN_CONFIDENCE = 50   # percentage


@dataclass
class DecisionMaker:
    name: str
    title: str
    company: str
    linkedin_url: str = ""
    email: str = ""
    email_confidence: float = 0.0


class DecisionMakerFinder:
    """
    Finds decision makers at target companies using Apify (LinkedIn) and Hunter.io.

    Usage:
        finder = DecisionMakerFinder()
        contacts = finder.find(company_name="Acme Corp", company_domain="acme.com")
    """

    def __init__(self) -> None:
        self._hunter_key  = os.environ.get("HUNTER_API_KEY", "")
        self._apify_token = os.environ.get("APIFY_API_TOKEN", "")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def find(self, company_name: str, company_domain: str) -> list[DecisionMaker]:
        """
        Return verified decision makers for a company.

        Steps:
          1. Search LinkedIn for people at `company_name` matching TARGET_TITLES.
          2. For each candidate, call Hunter.io to find a verified email.
          3. Return only contacts for whom we have a confirmed email.

        Args:
            company_name:   Company name as it appears on LinkedIn.
            company_domain: Root domain for email lookup, e.g. "acme.com".
        """
        if not self._apify_token:
            raise EnvironmentError(
                "APIFY_API_TOKEN is not set. "
                "Get yours at https://console.apify.com/account/integrations."
            )
        if not self._hunter_key:
            raise EnvironmentError(
                "HUNTER_API_KEY is not set. "
                "Get yours at https://hunter.io/api-keys (free tier: 25 searches/month)."
            )

        candidates = self._search_linkedin(company_name)
        results: list[DecisionMaker] = []
        for contact in candidates:
            enriched = self._enrich_email(contact, company_domain)
            if enriched.email:
                results.append(enriched)
            time.sleep(0.3)   # Hunter.io free tier: 1 req/sec

        return results

    # ------------------------------------------------------------------
    # Step 1: LinkedIn people search via Apify
    # ------------------------------------------------------------------

    def _search_linkedin(self, company_name: str) -> list[DecisionMaker]:
        """
        Use the Apify LinkedIn Profile Scraper to find people at `company_name`
        whose titles match TARGET_TITLES.

        The actor accepts a list of LinkedIn search URLs. We construct one search
        URL per title group to avoid burning too many Apify compute units.
        """
        # Build LinkedIn people-search URLs for the target titles
        # LinkedIn search URL pattern: /search/results/people/?keywords=<title>&company=<name>
        search_urls = [
            "https://www.linkedin.com/search/results/people/?"
            + urllib.parse.urlencode({
                "keywords": title,
                "company":  company_name,
                "origin":   "GLOBAL_SEARCH_HEADER",
            })
            for title in ["CTO", "VP Engineering", "Head of FinOps", "Director of Engineering"]
        ]

        run_input = {
            "startUrls":   [{"url": url} for url in search_urls],
            "maxResults":  10,
            "proxy":       {"useApifyProxy": True},
        }

        run_id, dataset_id = self._apify_start_run(
            APIFY_LINKEDIN_PEOPLE_ACTOR, run_input
        )
        status = self._apify_wait_for_run(run_id)
        if status != "SUCCEEDED":
            print(f"[decision_maker_finder] Apify run {run_id} ended with: {status}")
            return []

        items = self._apify_fetch_dataset(dataset_id)

        candidates: list[DecisionMaker] = []
        seen_names: set[str] = set()

        for item in items:
            name  = _full_name(item)
            title = (item.get("headline") or item.get("title") or "").strip()

            if not name or name in seen_names:
                continue
            if not _title_matches(title):
                continue

            seen_names.add(name)
            candidates.append(DecisionMaker(
                name=name,
                title=title,
                company=company_name,
                linkedin_url=_clean_url(
                    item.get("linkedinUrl") or item.get("url", "")
                ),
            ))

        print(
            f"[decision_maker_finder] Found {len(candidates)} LinkedIn candidates "
            f"at {company_name}"
        )
        return candidates

    # ------------------------------------------------------------------
    # Step 2: Email enrichment via Hunter.io
    # ------------------------------------------------------------------

    def _enrich_email(self, contact: DecisionMaker, domain: str) -> DecisionMaker:
        """
        Look up the contact's work email using Hunter.io's email-finder endpoint.

        Hunter.io uses the full name + company domain to predict the email address
        and returns a confidence score (0–100). We only accept scores ≥ HUNTER_MIN_CONFIDENCE.

        Docs: https://hunter.io/api-docs#email-finder
        """
        first, last = _split_name(contact.name)
        if not first or not last or not domain:
            return contact

        params = urllib.parse.urlencode({
            "domain":     domain,
            "first_name": first,
            "last_name":  last,
            "api_key":    self._hunter_key,
        })
        req = urllib.request.Request(
            f"https://api.hunter.io/v2/email-finder?{params}"
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return contact   # no email found — not an error
            print(
                f"[decision_maker_finder] Hunter.io error for {contact.name} "
                f"@{domain}: {exc.code}"
            )
            return contact

        payload = data.get("data", {})
        email      = payload.get("email", "")
        confidence = float(payload.get("score", 0))

        if email and confidence >= HUNTER_MIN_CONFIDENCE:
            contact.email            = email
            contact.email_confidence = confidence
            print(
                f"[decision_maker_finder] ✓ {contact.name} <{email}> "
                f"({confidence:.0f}% confidence)"
            )
        else:
            print(
                f"[decision_maker_finder] ✗ {contact.name} @{domain}: "
                f"{'no email' if not email else f'{confidence:.0f}% — below threshold'}"
            )

        return contact

    # ------------------------------------------------------------------
    # Apify helpers (shared with lead_scraper pattern)
    # ------------------------------------------------------------------

    def _apify_start_run(self, actor_id: str, run_input: dict) -> tuple[str, str]:
        payload = json.dumps(run_input).encode()
        req = urllib.request.Request(
            f"https://api.apify.com/v2/acts/{actor_id}/runs",
            data=payload,
            headers={
                "Authorization": f"Bearer {self._apify_token}",
                "Content-Type":  "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        run_id     = data["data"]["id"]
        dataset_id = data["data"]["defaultDatasetId"]
        print(f"[decision_maker_finder] Apify run started: {run_id}")
        return run_id, dataset_id

    def _apify_wait_for_run(self, run_id: str) -> str:
        terminal = {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}
        for _ in range(APIFY_MAX_POLLS):
            time.sleep(APIFY_POLL_INTERVAL_S)
            req = urllib.request.Request(
                f"https://api.apify.com/v2/actor-runs/{run_id}",
                headers={"Authorization": f"Bearer {self._apify_token}"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            status = data["data"]["status"]
            if status in terminal:
                return status
        return "TIMED-OUT"

    def _apify_fetch_dataset(self, dataset_id: str) -> list[dict]:
        req = urllib.request.Request(
            f"https://api.apify.com/v2/datasets/{dataset_id}/items"
            "?format=json&clean=true",
            headers={"Authorization": f"Bearer {self._apify_token}"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _full_name(item: dict) -> str:
    first = (item.get("firstName") or "").strip()
    last  = (item.get("lastName")  or "").strip()
    full  = (item.get("fullName")  or item.get("name") or "").strip()
    if full:
        return full
    if first or last:
        return f"{first} {last}".strip()
    return ""


def _split_name(full_name: str) -> tuple[str, str]:
    parts = full_name.strip().split()
    if len(parts) >= 2:
        return parts[0], parts[-1]
    return full_name, ""


def _title_matches(title: str) -> bool:
    title_lower = title.lower()
    return any(t.lower() in title_lower for t in TARGET_TITLES)


def _clean_url(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    if url and not url.startswith("http"):
        url = "https://" + url
    return url
