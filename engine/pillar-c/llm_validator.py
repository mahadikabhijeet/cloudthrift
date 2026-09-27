"""
Pillar C — LLM Lead Validator  (Claude-powered, prompt-cached)

Scores raw leads from lead_scraper / hn_scraper against four criteria:
  1. AWS usage evidence
  2. Company size fit (50–2000 employees ideal)
  3. Growth stage (Series A+ or profitable SMB)
  4. Industry alignment (SaaS, Fintech, E-commerce preferred)

Cost optimisations:
  - System prompt is cached with cache_control breakpoint (up to 90% cheaper on
    repeated batch runs once the cache warms after the first request)
  - Two model tiers: sonnet (default, quality) and haiku (bulk/cheap mode)
  - Exponential backoff on rate-limit errors (anthropic.RateLimitError)

Required env vars:
    ANTHROPIC_API_KEY
"""
from __future__ import annotations

import json
import os
import time
import random
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import anthropic

# ---------------------------------------------------------------------------
# Prompt — kept stable so the cache never invalidates between runs.
# Do NOT interpolate any dynamic content into SYSTEM_PROMPT.
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a FinOps sales qualification assistant for a cloud cost optimisation
consultancy. Your job is to evaluate whether a company is a strong prospect for
a paid cloud cost audit service targeting AWS users.

Qualification criteria (score 1–10):
  1. AWS usage evidence: job postings, tech stack signals, AWS-specific tooling
     (Terraform, CDK, boto3, CloudFormation, EKS, RDS, CloudFront, etc.)
  2. Company size: ideal range is 50–2000 employees (enough cloud spend to
     justify an audit; small enough to move fast without enterprise procurement)
  3. Growth stage: Series A through Series C, or a profitable bootstrapped SMB
     with real cloud infrastructure. Avoid pre-revenue / hobby projects.
  4. Industry alignment: SaaS, Fintech, E-commerce, HealthTech, EdTech, Gaming,
     and B2B software are preferred. Brick-and-mortar retail or non-tech is low.

Scoring guide:
  9–10  Strong AWS user, right size, right industry, clear cost pain signals
  7–8   Good fit on most criteria, minor gaps
  5–6   Borderline — some signals present but incomplete evidence
  1–4   Poor fit — wrong size, no AWS evidence, wrong industry

You MUST respond with a JSON object and nothing else. No markdown, no
explanation, no code fences. The schema is:
{
  "score": <integer 1–10>,
  "rationale": "<one concise sentence explaining the score>",
  "recommended_angle": "<one specific, personalised talking point for the outreach email>"
}
""".strip()

QUALIFICATION_THRESHOLD = 6   # leads below this score are dropped

MAX_TOKENS = 512

MAX_RETRIES   = 5
BASE_DELAY_S  = 1.0
MAX_DELAY_S   = 60.0

MODEL_QUALITY = "claude-sonnet-4-6"
MODEL_BULK    = "claude-haiku-4-5"


@dataclass
class ValidatedLead:
    company_name: str
    website: str
    linkedin_url: str
    score: int
    rationale: str
    recommended_angle: str
    raw_data: dict


class LLMValidator:
    """
    Score and filter raw leads using Claude.

    Usage:
        validator = LLMValidator()                          # sonnet default
        validator = LLMValidator(model="claude-haiku-4-5") # cheap bulk mode
        qualified = validator.validate(raw_leads)
        validator.save(qualified)
    """

    def __init__(
        self,
        model: str = MODEL_QUALITY,
        threshold: int = QUALIFICATION_THRESHOLD,
    ) -> None:
        self.client    = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self.model     = model
        self.threshold = threshold

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate(self, raw_leads: list[dict]) -> list[ValidatedLead]:
        """Score all leads and return those at or above the threshold."""
        qualified: list[ValidatedLead] = []
        total = len(raw_leads)

        for idx, lead in enumerate(raw_leads, start=1):
            company = lead.get("company_name", "<unknown>")
            print(f"[llm_validator] [{idx}/{total}] Scoring: {company} ...", end=" ", flush=True)

            result = self._score_lead_with_retry(lead)
            score  = result.get("score", 0)

            if score >= self.threshold:
                qualified.append(ValidatedLead(
                    company_name=lead.get("company_name", ""),
                    website=lead.get("website", ""),
                    linkedin_url=lead.get("linkedin_url", ""),
                    score=score,
                    rationale=result.get("rationale", ""),
                    recommended_angle=result.get("recommended_angle", ""),
                    raw_data=lead,
                ))
                print(f"✓ score={score}")
            else:
                print(f"✗ score={score} (below threshold {self.threshold})")

        print(
            f"[llm_validator] {len(qualified)}/{total} leads qualified "
            f"(threshold={self.threshold}, model={self.model})"
        )
        return qualified

    def save(self, leads: list[ValidatedLead], output_dir: str = ".") -> Path:
        date_str = datetime.now().strftime("%Y%m%d_%H%M")
        path = Path(output_dir) / f"leads_validated_{date_str}.json"
        path.write_text(json.dumps([asdict(l) for l in leads], indent=2))
        print(f"[llm_validator] {len(leads)} qualified leads → {path}")
        return path

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _score_lead_with_retry(self, lead: dict) -> dict:
        """Call Claude with exponential backoff on rate-limit errors."""
        for attempt in range(MAX_RETRIES):
            try:
                return self._score_lead(lead)
            except anthropic.RateLimitError as exc:
                retry_after = self._retry_after(exc)
                delay = retry_after or min(
                    BASE_DELAY_S * (2 ** attempt) + random.uniform(0, 1),
                    MAX_DELAY_S,
                )
                print(
                    f"\n[llm_validator] Rate limited (attempt {attempt+1}/{MAX_RETRIES}). "
                    f"Waiting {delay:.1f}s ...",
                    flush=True,
                )
                time.sleep(delay)
            except anthropic.APIStatusError as exc:
                if exc.status_code >= 500 and attempt < MAX_RETRIES - 1:
                    delay = min(BASE_DELAY_S * (2 ** attempt), MAX_DELAY_S)
                    print(f"\n[llm_validator] Server error {exc.status_code}, retrying in {delay:.1f}s")
                    time.sleep(delay)
                else:
                    print(f"\n[llm_validator] API error: {exc.status_code} — {exc.message}")
                    return {"score": 0, "rationale": f"API error: {exc.status_code}", "recommended_angle": ""}
            except Exception as exc:
                print(f"\n[llm_validator] Unexpected error: {exc}")
                return {"score": 0, "rationale": f"Error: {exc}", "recommended_angle": ""}

        return {"score": 0, "rationale": "Max retries exceeded", "recommended_angle": ""}

    def _score_lead(self, lead: dict) -> dict:
        """
        Make a single Claude API call to score a lead.

        The system prompt is cached (cache_control breakpoint on the last system
        text block). After the first request warms the cache, subsequent requests
        in the same batch cost ~10% of the system-prompt tokens.
        """
        response = self.client.messages.create(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    # Marks end of stable prefix — caches the system prompt
                    # across all leads in the same batch run.
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Please evaluate the following company and return a JSON score:\n\n"
                        + json.dumps(lead, indent=2, default=str)
                    ),
                }
            ],
        )

        raw_text = next(
            (b.text for b in response.content if b.type == "text"), ""
        ).strip()

        return self._parse_json_with_retry(raw_text, lead)

    def _parse_json_with_retry(self, raw_text: str, lead: dict) -> dict:
        """Parse Claude's JSON response, asking Claude to repair it once if malformed."""
        try:
            data = json.loads(raw_text)
            if isinstance(data, dict) and "score" in data:
                return data
        except json.JSONDecodeError:
            pass

        # Strip accidental markdown code fences
        cleaned = raw_text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            data = json.loads(cleaned)
            if isinstance(data, dict) and "score" in data:
                return data
        except json.JSONDecodeError:
            pass

        # Ask Claude to repair the JSON
        print("\n[llm_validator] Malformed JSON, requesting repair ...", end=" ", flush=True)
        try:
            repair_response = self.client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "The following text was supposed to be a JSON object with keys "
                            '"score" (integer 1-10), "rationale" (string), and '
                            '"recommended_angle" (string). Please output ONLY valid JSON:\n\n'
                            + raw_text
                        ),
                    }
                ],
            )
            repaired = next(
                (b.text for b in repair_response.content if b.type == "text"), ""
            ).strip()
            data = json.loads(repaired)
            if isinstance(data, dict) and "score" in data:
                print("repaired ✓")
                return data
        except Exception:
            pass

        print("failed, defaulting to score=0")
        return {
            "score": 0,
            "rationale": "Could not parse LLM response",
            "recommended_angle": "",
        }

    @staticmethod
    def _retry_after(exc: anthropic.RateLimitError) -> float | None:
        """Extract Retry-After header value in seconds, or None."""
        try:
            val = exc.response.headers.get("retry-after")
            return float(val) if val else None
        except Exception:
            return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LLM lead validator")
    parser.add_argument("leads_file", help="JSON file of raw leads")
    parser.add_argument("--model", default=MODEL_QUALITY, choices=[MODEL_QUALITY, MODEL_BULK])
    parser.add_argument("--threshold", type=int, default=QUALIFICATION_THRESHOLD)
    parser.add_argument("--output-dir", default=".")
    args = parser.parse_args()

    raw = json.loads(Path(args.leads_file).read_text())
    validator = LLMValidator(model=args.model, threshold=args.threshold)
    qualified = validator.validate(raw)
    validator.save(qualified, output_dir=args.output_dir)
