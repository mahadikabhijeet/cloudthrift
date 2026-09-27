"""
Pillar B: Cloud cost audit engine — entry point.

Assumes the client's cross-account role, runs all analysis modules in sequence,
and writes results as a PDF report and JSON dashboard payload.

Usage (real account):
    python pillar-b/engine/main.py \
        --role-arn  arn:aws:iam::ACCOUNT:role/FinOps-Audit-ReadOnly-Role \
        --external-id  <secret> \
        --account-id   123456789012 \
        --region       us-east-1 \
        --output       both

Usage (smoke test — no AWS credentials required):
    python pillar-b/engine/main.py --mock --account-id 123456789012
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.findings_schema import AuditReport
from output.dashboard_data import export_dashboard_data
from output.pdf_generator import generate_pdf


def run_audit(
    account_id: str,
    region: str,
    role_arn: str = "",
    external_id: str = "",
    profile: str = "",
    payer_profile: str = "",
    all_regions: bool = False,
    region_list: list[str] | None = None,
    teaser: bool = False,
    teaser_sources: str = "light",
) -> AuditReport:
    import inspect

    from shared.aws_client import get_session, get_all_regions, validate_session
    from audit_modules import get_audit_module_classes
    from enrichment.pipeline import post_process_findings

    session = get_session(role_arn=role_arn, external_id=external_id,
                          region=region, profile=profile)

    # Pre-flight: verify credentials and clock sync before running 18-region scans
    caller_arn = validate_session(session, profile=profile)
    print(f"  [auth] Validated — {caller_arn}")

    # Optional payer/billing session: Cost Explorer, Compute Optimizer, and Cost
    # Optimization Hub are only meaningful from the org's payer account. When a
    # payer profile is supplied, billing APIs run through it (scoped to this
    # account via LINKED_ACCOUNT); resource-describe stays on the target session.
    billing_session = session
    billing_account_id = ""
    if payer_profile:
        billing_session = get_session(profile=payer_profile, region=region)
        payer_arn = validate_session(billing_session, profile=payer_profile)
        print(f"  [auth] Payer validated — {payer_arn}")
        billing_account_id = account_id

    if region_list:
        regions: list[str] | None = region_list
    elif all_regions:
        regions = get_all_regions(session)
    else:
        regions = None

    if teaser:
        print(f"  [teaser mode] sources={teaser_sources} — skipping CloudWatch/Cost Explorer heavy checks")

    report = AuditReport(account_id=account_id, generated_at=datetime.now(timezone.utc))

    covered_resource_ids: set[str] = set()

    for ModuleClass in get_audit_module_classes(teaser=teaser, teaser_sources=teaser_sources):
        # Thread the billing session and covered_resource_ids into modules that opt in
        kwargs: dict = {"regions": regions, "teaser": teaser}
        params = inspect.signature(ModuleClass.__init__).parameters
        if "billing_session" in params:
            kwargs["billing_session"] = billing_session
        if "billing_account_id" in params:
            kwargs["billing_account_id"] = billing_account_id
        if "covered_resource_ids" in params:
            kwargs["covered_resource_ids"] = covered_resource_ids

        module = ModuleClass(session, **kwargs)
        findings = module.run()
        report.findings.extend(findings)
        print(f"  [{module.__class__.__name__}] {len(findings)} findings")

        # Accumulate resource IDs covered so custom modules skip redundant API calls
        for f in findings:
            if f.resource_id and f.resource_id.lower().strip() not in ("unknown", ""):
                covered_resource_ids.add(f.resource_id.lower().strip())

    report.findings, stats = post_process_findings(report.findings)
    if stats["before_dedup"] != stats["after_dedup"]:
        print(f"  [Deduplicator] {stats['before_dedup']} → {stats['after_dedup']} findings after merge")
    print(
        f"  [Prioritizer] {stats['quick_wins']} quick wins, "
        f"{stats['this_month']} this month, {stats['needs_review']} need review"
    )

    return report


def run_mock(account_id: str, region: str) -> AuditReport:
    from mock_data import generate_mock_report
    from enrichment.pipeline import post_process_findings

    print("  [MOCK] Generating synthetic findings — no AWS credentials needed")
    report = generate_mock_report(account_id, region)
    report.findings, _ = post_process_findings(report.findings)
    print(f"  [MOCK] {len(report.findings)} findings generated")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="FinOps Platform — Cloud Cost Audit Engine")
    parser.add_argument("--mock",        action="store_true",
                        help="Use synthetic data for smoke testing (no AWS credentials required)")
    parser.add_argument("--profile",     default="",
                        help="AWS CLI profile for direct SSO/credential access (company workflow)")
    parser.add_argument("--payer-profile", default="",
                        help="AWS CLI profile for the org's PAYER/management account. When set, "
                             "Cost Explorer / Savings Plans / Compute Optimizer / Cost Optimization "
                             "Hub queries run through it (scoped to --account-id via LINKED_ACCOUNT). "
                             "Read-only; no role assumption.")
    parser.add_argument("--role-arn",    default="",
                        help="ARN of the cross-account IAM role (client/role-assumption workflow)")
    parser.add_argument("--external-id", default="",
                        help="External ID for role assumption (omit if role has no ExternalId condition)")
    parser.add_argument("--account-id",  required=True,
                        help="Target AWS account ID (or any label in mock mode)")
    parser.add_argument("--region",       default="us-east-1")
    parser.add_argument("--all-regions",  action="store_true",
                        help="Scan all enabled AWS regions (default: session region only)")
    parser.add_argument("--region-list",  default="",
                        help="Comma-separated list of regions to scan, e.g. us-east-1,eu-west-1,ap-southeast-1 (overrides --all-regions)")
    parser.add_argument("--output",      choices=["pdf", "json", "html", "both"], default="both")
    parser.add_argument("--output-dir",  default=".", help="Directory for output files")
    parser.add_argument("--mode",        choices=["full", "teaser"], default="full",
                        help="full: all checks (default). teaser: fast API-only checks")
    parser.add_argument("--teaser-sources", choices=["ta-only", "light", "standard"],
                        default="light",
                        help="teaser module set: ta-only (~30s), light (default, ~2-3 min/region), "
                             "standard (all modules with teaser flags)")
    args = parser.parse_args()

    if not args.mock and not args.profile and not args.role_arn:
        parser.error("live mode requires --profile (SSO) or --role-arn (role assumption)")

    if args.payer_profile and args.mock:
        parser.error("--payer-profile has no effect in --mock mode")

    region_list = [r.strip() for r in args.region_list.split(",") if r.strip()] if args.region_list else []
    teaser = (args.mode == "teaser")

    mode_label = "MOCK" if args.mock else f"LIVE ({args.account_id})"
    if teaser:
        mode_label += f" [TEASER/{args.teaser_sources}]"
    region_display = ", ".join(region_list) if region_list else ("ALL" if args.all_regions else args.region)
    print(f"\n{'='*60}")
    print(f"  FinOps Audit Engine  |  {mode_label}  |  {region_display}")
    print(f"{'='*60}\n")

    if args.mock:
        report = run_mock(args.account_id, args.region)
    else:
        report = run_audit(
            account_id=args.account_id,
            region=args.region,
            role_arn=args.role_arn,
            external_id=args.external_id,
            profile=args.profile,
            payer_profile=args.payer_profile,
            all_regions=args.all_regions,
            region_list=region_list or None,
            teaser=teaser,
            teaser_sources=args.teaser_sources if teaser else "light",
        )

    print(f"\n{'─'*60}")
    print(f"  Findings : {len(report.findings)}")
    print(f"  Est. savings : ${report.total_monthly_savings_usd:,.2f}/month")

    by_sev = report.findings_by_severity
    for sev in ("critical", "high", "medium", "low"):
        count = len(by_sev.get(sev, []))
        if count:
            print(f"  {sev.upper():<10} {count} finding{'s' if count != 1 else ''}")
    print(f"{'─'*60}\n")

    if args.output in ("pdf", "both"):
        path = generate_pdf(report, output_dir=args.output_dir)
        print(f"  PDF  → {path}")
    if args.output in ("json", "both"):
        path = export_dashboard_data(report, output_dir=args.output_dir)
        print(f"  JSON → {path}")
    if args.output == "html":
        from output.html_exporter import export_static_html
        path = export_static_html(report, output_dir=args.output_dir)
        print(f"  HTML → {path}")

    if teaser:
        from output.teaser_preview import export_teaser_preview
        path = export_teaser_preview(report, output_dir=args.output_dir)
        print(f"  TEASER PREVIEW → {path}")

    print("\nDone.\n")


if __name__ == "__main__":
    main()
