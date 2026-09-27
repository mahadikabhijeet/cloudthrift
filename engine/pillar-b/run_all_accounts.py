"""
Pillar B — Multi-Account Audit Runner

Reads pillar-a/accounts.json and runs the cost audit against every enabled
account in parallel. Writes one dashboard_<account_id>_<date>.json per account
into the output directory (default: pillar-d/data/).

Usage:
    python pillar-b/run_all_accounts.py [OPTIONS]

Options:
    --config     Path to accounts.json (default: pillar-a/accounts.json)
    --output-dir Directory for JSON reports (default: pillar-d/data)
    --workers    Parallel audit threads (default: 6)
    --env        Only audit accounts with this env value (prod, staging, dev...)
    --filter     Only audit accounts whose name contains this string
    --accounts   Comma-separated list of specific account IDs to audit
    --dry-run    List accounts that would be audited without running anything
    --output     pdf, json, or both (default: json)

Examples:
    # Audit all prod accounts, 8 in parallel
    python pillar-b/run_all_accounts.py --env prod --workers 8

    # Audit specific accounts
    python pillar-b/run_all_accounts.py --accounts 111111111111,222222222222

    # Dry run to see what would be audited
    python pillar-b/run_all_accounts.py --env staging --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

# Allow running from repo root or from pillar-b/
_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))  # repo root → finds shared/
sys.path.insert(0, str(_here / "engine"))  # finds modules/, output/, mock_data

from shared.findings_schema import AuditReport
from output.dashboard_data import export_dashboard_data
from output.pdf_generator import generate_pdf


# ---------------------------------------------------------------------------
# Single-account audit (runs in a thread)
# ---------------------------------------------------------------------------

def audit_one(account: dict, config: dict, output_dir: Path, output_fmt: str,
              region_list: list[str] | None = None,
              teaser: bool = False,
              teaser_sources: str = "light") -> dict:
    """
    Audit a single account. Returns a result dict.
    Called from the thread pool — must be thread-safe.
    """
    acct_id   = account["id"]
    acct_name = account.get("name", acct_id)
    region    = account.get("region") or config.get("default_region", "us-east-1")

    role_arn = account.get("role_arn", "").strip()
    profile  = account.get("profile", "").strip() or config.get("default_profile", "")
    ext_id   = (account.get("external_id") or config.get("external_id", "")).strip()

    if not role_arn and not profile:
        return {
            "account_id": acct_id, "account_name": acct_name,
            "env": account.get("env", "unknown"), "region": region,
            "status": "failed", "findings": 0, "savings_usd": 0.0,
            "output_file": None, "duration_s": 0.0,
            "error": (
                "accounts.json entry needs either 'profile' (SSO/direct access) "
                "or 'role_arn' (cross-account assumption)"
            ),
        }

    started = datetime.now(timezone.utc)
    result: dict = {
        "account_id":   acct_id,
        "account_name": acct_name,
        "env":          account.get("env", "unknown"),
        "region":       region,
        "role_arn":     role_arn,
        "profile":      profile,
        "status":       "pending",
        "findings":     0,
        "savings_usd":  0.0,
        "output_file":  None,
        "error":        None,
        "duration_s":   0.0,
    }

    try:
        from shared.aws_client import get_session, get_all_regions, validate_session
        from audit_modules import get_audit_module_classes
        from enrichment.pipeline import post_process_findings

        session = get_session(
            role_arn=role_arn,
            external_id=ext_id,
            region=region,
            profile=profile,
            session_name=f"finops-multi-audit-{acct_id}",
        )

        # Pre-flight: fail fast on clock skew or expired token before scanning regions
        validate_session(session, profile=profile)

        scan_regions = region_list if region_list else get_all_regions(session)

        if teaser:
            print(f"  [{acct_name}] teaser mode ({teaser_sources}) — skipping heavy checks")

        report = AuditReport(
            account_id=acct_id,
            account_name=acct_name,
            generated_at=started,
        )

        for ModuleClass in get_audit_module_classes(teaser=teaser, teaser_sources=teaser_sources):
            module_start = datetime.now(timezone.utc)
            module = ModuleClass(session, regions=scan_regions, teaser=teaser)
            module_findings = module.run()
            report.findings.extend(module_findings)

            elapsed = (datetime.now(timezone.utc) - module_start).total_seconds()
            print(
                f"  [{acct_name}] {module.__class__.__name__}: "
                f"{len(module_findings)} findings  "
                f"(total: {len(report.findings)}, {elapsed:.0f}s)"
            )

            if output_fmt in ("json", "both"):
                export_dashboard_data(report, output_dir=str(output_dir), silent=True)

        report.findings, stats = post_process_findings(report.findings)
        if stats["before_dedup"] != stats["after_dedup"]:
            print(
                f"  [{acct_name}] Deduplicator: {stats['before_dedup']} → "
                f"{stats['after_dedup']} findings after merge"
            )

        output_path: Path | None = None
        if output_fmt in ("json", "both"):
            output_path = export_dashboard_data(report, output_dir=str(output_dir))
        if output_fmt in ("pdf", "both"):
            generate_pdf(report, output_dir=str(output_dir))
        if output_fmt == "html":
            from output.html_exporter import export_static_html
            output_path = export_static_html(report, output_dir=str(output_dir))
        if teaser:
            from output.teaser_preview import export_teaser_preview
            export_teaser_preview(report, output_dir=str(output_dir))

        result.update({
            "status":      "succeeded",
            "findings":    len(report.findings),
            "savings_usd": report.total_monthly_savings_usd,
            "output_file": str(output_path) if output_path else None,
        })

    except Exception as exc:
        result.update({"status": "failed", "error": str(exc)})

    result["duration_s"] = (datetime.now(timezone.utc) - started).total_seconds()
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="FinOps — audit all accounts in parallel",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--config",
        default="pillar-a/accounts.json",
        help="Path to accounts.json")
    parser.add_argument("--output-dir",
        default="pillar-d/data",
        help="Directory for report files")
    parser.add_argument("--workers", type=int, default=6,
        help="Parallel threads (default: 6)")
    parser.add_argument("--env",
        default="",
        help="Filter: only accounts with this env value")
    parser.add_argument("--filter",
        default="",
        help="Filter: only accounts whose name contains this string")
    parser.add_argument("--accounts",
        default="",
        help="Comma-separated account IDs to audit (overrides other filters)")
    parser.add_argument("--dry-run", action="store_true",
        help="List accounts without running audits")
    parser.add_argument("--output",
        choices=["pdf", "json", "html", "both"], default="json")
    parser.add_argument("--mode",
        choices=["full", "teaser"], default="full",
        help="full: all checks (default). teaser: fast API-only checks")
    parser.add_argument("--teaser-sources",
        choices=["ta-only", "light", "standard"], default="light",
        help="teaser module set: ta-only, light (default), or standard")
    parser.add_argument("--region-list",
        default="",
        help="Comma-separated regions to scan for every account, e.g. us-east-1,eu-west-1 "
             "(default: all enabled regions per account)")
    args = parser.parse_args()

    # --- Load config ----------------------------------------------------------
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"ERROR: Config not found: {config_path}")
        print("Run: bash pillar-a/scripts/generate-accounts-config.sh")
        print("Or:  cp pillar-a/accounts.example.json pillar-a/accounts.json  (then edit)")
        sys.exit(1)

    config = json.loads(config_path.read_text())

    # --- Filter accounts ------------------------------------------------------
    accounts = [a for a in config.get("accounts", []) if a.get("enabled", True)]

    if args.accounts:
        wanted = {a.strip() for a in args.accounts.split(",")}
        accounts = [a for a in accounts if a["id"] in wanted]
    else:
        if args.env:
            accounts = [a for a in accounts if a.get("env", "") == args.env]
        if args.filter:
            accounts = [a for a in accounts if args.filter.lower() in a.get("name", "").lower()]

    if not accounts:
        print("No accounts matched the given filters.")
        sys.exit(0)

    region_list = [r.strip() for r in args.region_list.split(",") if r.strip()] if args.region_list else []
    teaser = (args.mode == "teaser")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- Header ---------------------------------------------------------------
    print(f"\n{'='*65}")
    print(f"  FinOps Multi-Account Audit" + (" [TEASER MODE]" if teaser else ""))
    print(f"{'='*65}")
    print(f"  Accounts : {len(accounts)}")
    print(f"  Workers  : {args.workers}")
    print(f"  Output   : {output_dir}")
    if teaser:      print(f"  Mode     : teaser ({args.teaser_sources})")
    if region_list: print(f"  Regions  : {', '.join(region_list)}")
    else:           print(f"  Regions  : all enabled (per account)")
    if args.env:    print(f"  Env      : {args.env}")
    if args.filter: print(f"  Filter   : {args.filter}")
    print(f"{'='*65}\n")

    if args.dry_run:
        print("DRY RUN — accounts that would be audited:\n")
        for a in accounts:
            role_arn = a.get("role_arn", "")
            profile  = a.get("profile", "") or config.get("default_profile", "")
            if profile and not role_arn:
                auth = f"profile:{profile}"
            elif role_arn:
                ext = a.get("external_id") or config.get("external_id", "")
                auth = role_arn + (" (ExternalId set)" if ext else "")
            else:
                auth = "⚠ no profile or role_arn"
            print(f"  [{a.get('env','?'):<10}] {a.get('name',''):<20} {a['id']}  →  {auth}")
        print(f"\n{len(accounts)} accounts would be audited.")
        return

    # --- Run audits in parallel -----------------------------------------------
    results: list[dict] = []
    completed = 0
    total = len(accounts)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(audit_one, acct, config, output_dir, args.output,
                        region_list or None, teaser, args.teaser_sources): acct
            for acct in accounts
        }

        for future in as_completed(futures):
            completed += 1
            result = future.result()
            results.append(result)

            status_icon = "✓" if result["status"] == "succeeded" else "✗"
            savings = f"${result['savings_usd']:>10,.2f}/mo" if result["status"] == "succeeded" else " " * 15
            findings = f"{result['findings']:>4} findings" if result["status"] == "succeeded" else result.get("error", "")[:40]
            duration = f"{result['duration_s']:.0f}s"

            print(
                f"  [{completed:>3}/{total}] {status_icon}  "
                f"{result['account_name']:<20} {result['account_id']}  "
                f"{savings}  {findings}  ({duration})"
            )

    # --- Summary --------------------------------------------------------------
    succeeded = [r for r in results if r["status"] == "succeeded"]
    failed    = [r for r in results if r["status"] == "failed"]
    total_savings = sum(r["savings_usd"] for r in succeeded)
    total_findings = sum(r["findings"]    for r in succeeded)

    print(f"\n{'='*65}")
    print(f"  SUMMARY")
    print(f"{'='*65}")
    print(f"  Succeeded : {len(succeeded)}/{total}")
    print(f"  Findings  : {total_findings}")
    print(f"  Total est. savings : ${total_savings:,.2f}/month  (${total_savings*12:,.0f}/year)")

    if failed:
        print(f"\n  Failed accounts ({len(failed)}):")
        for r in failed:
            print(f"    - {r['account_name']} ({r['account_id']}): {r['error']}")

    if succeeded:
        print(f"\n  Reports written to: {output_dir}")
        print(f"\n  Open the dashboard:")
        print(f"    cd pillar-d")
        print(f"    DATA_DIR=data python -m uvicorn app.main:app --port 8000")

    print(f"{'='*65}\n")

    # Write machine-readable run summary
    summary_path = output_dir / f"run_summary_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    summary_path.write_text(json.dumps({
        "run_at": datetime.now(timezone.utc).isoformat(),
        "total": total,
        "succeeded": len(succeeded),
        "failed": len(failed),
        "total_findings": total_findings,
        "total_monthly_savings_usd": total_savings,
        "accounts": results,
    }, indent=2))
    print(f"  Run summary → {summary_path}")

    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
