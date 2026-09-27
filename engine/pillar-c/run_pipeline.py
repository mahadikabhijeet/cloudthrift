"""
Pillar C — Pipeline Runner

End-to-end lead generation pipeline. Chains all Pillar C components:

  Stage 1  HN Scraper        — discovers companies from HN "Who is Hiring" (free)
  Stage 2  Tech Validator     — confirms AWS usage via headers/DNS/GitHub (free)
  Stage 3  LLM Validator      — scores fit using Claude; filters below threshold
  Stage 4  Decision Maker     — finds VP/CTO contacts via Apify + Hunter.io
  Stage 5  Email Validator    — generates and MX-validates email patterns (free)
  Stage 6  Gmail Outreach     — sends personalised cold emails via Gmail API

Usage:
    # Full pipeline (all stages)
    python pillar-c/run_pipeline.py

    # Dry run — compose emails but don't send
    python pillar-c/run_pipeline.py --dry-run

    # Run specific stages only
    python pillar-c/run_pipeline.py --stages hn,tech,llm

    # Skip to stage 4 using previously saved leads
    python pillar-c/run_pipeline.py --stages dm,email,outreach \
        --leads-file leads_validated_20241201.json

    # Use both HN (free) and paid job boards + LinkedIn
    python pillar-c/run_pipeline.py --sources hn,jobs,linkedin

Required env vars (set in .env):
    ANTHROPIC_API_KEY      — for LLM scoring and email composition
    GITHUB_TOKEN           — optional, raises GitHub API limit to 15k/hr
    APIFY_API_TOKEN        — for LinkedIn people search (stages 1/4)
    HUNTER_API_KEY         — for email verification (stage 4)
    GMAIL_CREDENTIALS_JSON — OAuth credentials for Gmail send (stage 6)
    GMAIL_TOKEN_JSON       — OAuth token for Gmail send (stage 6)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap: make shared/ importable when running from repo root or pillar-c/
# ---------------------------------------------------------------------------
_here = Path(__file__).resolve().parent
_repo = _here.parent
if str(_repo) not in sys.path:
    sys.path.insert(0, str(_repo))

ALL_STAGES = ["hn", "tech", "llm", "dm", "email", "outreach"]


def _load_env() -> None:
    """Load .env from repo root if python-dotenv is available."""
    env_path = _repo / ".env"
    if env_path.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(env_path)
            print(f"[pipeline] Loaded env from {env_path}")
        except ImportError:
            pass


def run_pipeline(
    stages: list[str],
    sources: list[str],
    leads_file: str,
    output_dir: str,
    dry_run: bool,
    months_back: int,
) -> None:
    active = set(stages)
    os.makedirs(output_dir, exist_ok=True)

    raw_leads: list[dict] = []
    validated_leads: list[dict] = []
    contacts: list[dict] = []

    # ------------------------------------------------------------------ #
    # Stage 1 — HN Scraper                                                #
    # ------------------------------------------------------------------ #
    if "hn" in active:
        print(f"\n{'='*60}")
        print("  Stage 1 — HN Who is Hiring scraper")
        print(f"{'='*60}")
        from hn_scraper import HNScraper
        scraper = HNScraper(months_back=months_back)
        hn_leads = scraper.run()
        hn_leads_dicts = [asdict(l) for l in hn_leads]

        if "jobs" in sources or "linkedin" in sources:
            from lead_scraper import LeadScraper
            print("\n  Stage 1b — Job boards / LinkedIn scraper")
            paid_scraper = LeadScraper()
            paid_leads = paid_scraper.run(sources=[s for s in sources if s != "hn"])
            paid_dicts = [asdict(l) for l in paid_leads]
            raw_leads = _dedup(hn_leads_dicts + paid_dicts)
        else:
            raw_leads = hn_leads_dicts

        print(f"\n[pipeline] Stage 1 complete — {len(raw_leads)} raw leads")
        _save_json(raw_leads, output_dir, "leads_raw")

    # ------------------------------------------------------------------ #
    # Stage 2 — Tech Stack Validator                                      #
    # ------------------------------------------------------------------ #
    if "tech" in active:
        if not raw_leads:
            raw_leads = _load_latest(output_dir, "leads_raw") or _load_file(leads_file)
        if not raw_leads:
            _die("Stage 2 needs raw leads. Run stage 'hn' first or pass --leads-file.")

        print(f"\n{'='*60}")
        print("  Stage 2 — AWS tech stack validator")
        print(f"{'='*60}")
        from tech_stack_validator import TechStackValidator
        validator = TechStackValidator()
        aws_confirmed = validator.validate_batch(raw_leads)
        raw_leads = aws_confirmed   # carry forward only confirmed leads
        print(f"\n[pipeline] Stage 2 complete — {len(aws_confirmed)} AWS-confirmed leads")
        _save_json(aws_confirmed, output_dir, "leads_aws_confirmed")

    # ------------------------------------------------------------------ #
    # Stage 3 — LLM Validator                                             #
    # ------------------------------------------------------------------ #
    if "llm" in active:
        if not raw_leads:
            raw_leads = _load_latest(output_dir, "leads_aws_confirmed") \
                     or _load_latest(output_dir, "leads_raw") \
                     or _load_file(leads_file)
        if not raw_leads:
            _die("Stage 3 needs leads. Run earlier stages first or pass --leads-file.")

        print(f"\n{'='*60}")
        print("  Stage 3 — LLM lead scoring (Claude)")
        print(f"{'='*60}")
        from llm_validator import LLMValidator
        llm = LLMValidator()
        scored = llm.validate(raw_leads)
        validated_leads = [asdict(l) for l in scored]
        print(f"\n[pipeline] Stage 3 complete — {len(validated_leads)} qualified leads (score ≥ {llm.threshold})")
        _save_json(validated_leads, output_dir, "leads_validated")

    # ------------------------------------------------------------------ #
    # Stage 4 — Decision Maker Finder                                     #
    # ------------------------------------------------------------------ #
    if "dm" in active:
        if not validated_leads:
            validated_leads = _load_latest(output_dir, "leads_validated") or _load_file(leads_file)
        if not validated_leads:
            _die("Stage 4 needs validated leads. Run stage 'llm' first or pass --leads-file.")

        print(f"\n{'='*60}")
        print("  Stage 4 — Decision maker finder (Apify + Hunter.io)")
        print(f"{'='*60}")
        from decision_maker_finder import DecisionMakerFinder
        import urllib.parse

        finder = DecisionMakerFinder()
        for lead in validated_leads:
            company_name = lead.get("company_name", "")
            domain = _lead_domain(lead)
            if not company_name or not domain:
                continue
            print(f"\n[pipeline]   → {company_name} ({domain})")
            try:
                dms = finder.find(company_name=company_name, company_domain=domain)
                for dm in dms:
                    contacts.append({**asdict(dm), "lead": lead})
            except Exception as exc:
                print(f"[pipeline]   ! {company_name}: {exc}")

        print(f"\n[pipeline] Stage 4 complete — {len(contacts)} contacts found")
        _save_json(contacts, output_dir, "contacts")

    # ------------------------------------------------------------------ #
    # Stage 5 — Email Validator                                           #
    # ------------------------------------------------------------------ #
    if "email" in active:
        if not contacts:
            contacts = _load_latest(output_dir, "contacts") or []
        if not contacts:
            _die("Stage 5 needs contacts. Run stage 'dm' first.")

        print(f"\n{'='*60}")
        print("  Stage 5 — Email validator (pattern gen + MX check)")
        print(f"{'='*60}")
        from email_validator import EmailValidator
        ev = EmailValidator()

        enriched: list[dict] = []
        for contact in contacts:
            if contact.get("email"):
                contact["email_best_guess"] = contact["email"]
                enriched.append(contact)
                continue
            first, last = _split_name(contact.get("name", ""))
            domain = _lead_domain(contact.get("lead", {}))
            if not (first and last and domain):
                continue
            result = ev.validate(first, last, domain)
            if result.best_guess:
                contact["email_best_guess"] = result.best_guess
                contact["email_candidates"] = [c.email for c in result.candidates]
                enriched.append(contact)

        contacts = enriched
        print(f"\n[pipeline] Stage 5 complete — {len(contacts)} contacts with email addresses")
        _save_json(contacts, output_dir, "contacts_enriched")

    # ------------------------------------------------------------------ #
    # Stage 6 — Gmail Outreach                                            #
    # ------------------------------------------------------------------ #
    if "outreach" in active:
        if not contacts:
            contacts = _load_latest(output_dir, "contacts_enriched") \
                    or _load_latest(output_dir, "contacts") or []
        if not contacts:
            _die("Stage 6 needs contacts with emails. Run stages 'dm' and 'email' first.")

        print(f"\n{'='*60}")
        mode = "DRY RUN" if dry_run else "LIVE"
        print(f"  Stage 6 — Gmail outreach ({mode})")
        print(f"{'='*60}")
        from gmail_outreach import GmailOutreach
        outreach = GmailOutreach()

        sent = skipped = 0
        for contact in contacts:
            email = contact.get("email_best_guess") or contact.get("email", "")
            if not email:
                continue
            contact_for_send = {
                "name":  contact.get("name", ""),
                "title": contact.get("title", ""),
                "email": email,
            }
            company = contact.get("lead", {})
            if not company.get("company_name"):
                company = {"company_name": contact.get("company", ""), "recommended_angle": ""}

            ok = outreach.send(contact_for_send, company, dry_run=dry_run)
            if ok:
                sent += 1
            else:
                skipped += 1

        print(f"\n[pipeline] Stage 6 complete — {sent} emails {'queued' if dry_run else 'sent'}, {skipped} skipped (duplicate/missing email)")

    # ------------------------------------------------------------------ #
    # Summary                                                             #
    # ------------------------------------------------------------------ #
    print(f"\n{'='*60}")
    print("  Pipeline complete")
    print(f"{'='*60}")
    print(f"  Output directory : {output_dir}")
    for f in sorted(Path(output_dir).glob("*.json")):
        size = f.stat().st_size
        print(f"  {f.name:<45} {size:>8,} bytes")
    print()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _save_json(data: list, output_dir: str, prefix: str) -> Path:
    date_str = datetime.now().strftime("%Y%m%d_%H%M")
    path = Path(output_dir) / f"{prefix}_{date_str}.json"
    path.write_text(json.dumps(data, indent=2, default=str))
    print(f"[pipeline] Saved {len(data)} items → {path}")
    return path


def _load_latest(output_dir: str, prefix: str) -> list[dict]:
    files = sorted(Path(output_dir).glob(f"{prefix}_*.json"), reverse=True)
    if not files:
        return []
    data = json.loads(files[0].read_text())
    print(f"[pipeline] Loaded {len(data)} items from {files[0].name}")
    return data


def _load_file(path: str) -> list[dict]:
    if not path or not Path(path).exists():
        return []
    data = json.loads(Path(path).read_text())
    print(f"[pipeline] Loaded {len(data)} items from {path}")
    return data


def _dedup(leads: list[dict]) -> list[dict]:
    seen: set[str] = set()
    result: list[dict] = []
    for lead in leads:
        key = lead.get("company_name", "").lower().strip()
        if key and key not in seen:
            seen.add(key)
            result.append(lead)
    return result


def _lead_domain(lead: dict) -> str:
    website = lead.get("website", "")
    if not website:
        return ""
    if not website.startswith("http"):
        website = "https://" + website
    try:
        import urllib.parse
        return urllib.parse.urlparse(website).netloc.lstrip("www.") or ""
    except Exception:
        return ""


def _split_name(full_name: str) -> tuple[str, str]:
    parts = full_name.strip().split()
    if len(parts) >= 2:
        return parts[0], parts[-1]
    return full_name, ""


def _die(msg: str) -> None:
    print(f"[pipeline] ERROR: {msg}")
    sys.exit(1)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    _load_env()

    parser = argparse.ArgumentParser(
        description="FinOps Platform — Pillar C Lead Generation Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_pipeline.py                           # full pipeline, all stages
  python run_pipeline.py --dry-run                 # compose emails, don't send
  python run_pipeline.py --stages hn,tech,llm      # discovery only
  python run_pipeline.py --stages outreach --dry-run  # resend from saved contacts
  python run_pipeline.py --sources hn,jobs,linkedin   # all lead sources
        """,
    )
    parser.add_argument(
        "--stages",
        default=",".join(ALL_STAGES),
        help=f"Comma-separated stages to run. All stages: {','.join(ALL_STAGES)}",
    )
    parser.add_argument(
        "--sources",
        default="hn",
        help="Lead sources for stage 1: hn, jobs, linkedin (comma-separated). Default: hn",
    )
    parser.add_argument(
        "--leads-file",
        default="",
        help="Path to a JSON leads file to resume from a specific stage",
    )
    parser.add_argument(
        "--output-dir",
        default="pipeline_output",
        help="Directory for intermediate and final output files (default: pipeline_output)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compose and print emails but do not send them",
    )
    parser.add_argument(
        "--months-back",
        type=int,
        default=1,
        help="How many recent HN hiring posts to scan (default: 1)",
    )

    args = parser.parse_args()
    stages  = [s.strip() for s in args.stages.split(",") if s.strip()]
    sources = [s.strip() for s in args.sources.split(",") if s.strip()]

    invalid = [s for s in stages if s not in ALL_STAGES]
    if invalid:
        parser.error(f"Unknown stages: {invalid}. Valid: {ALL_STAGES}")

    print(f"\n{'='*60}")
    print("  FinOps Platform — Lead Generation Pipeline")
    print(f"{'='*60}")
    print(f"  Stages   : {' → '.join(stages)}")
    print(f"  Sources  : {sources}")
    print(f"  Output   : {args.output_dir}")
    print(f"  Dry run  : {args.dry_run}")
    print(f"{'='*60}\n")

    run_pipeline(
        stages=stages,
        sources=sources,
        leads_file=args.leads_file,
        output_dir=args.output_dir,
        dry_run=args.dry_run,
        months_back=args.months_back,
    )


if __name__ == "__main__":
    main()
