"""
Pillar B — Output: Static HTML Exporter

Renders the audit report as a self-contained HTML file using the Pillar D
Jinja2 templates. The result can be opened in any browser without running a
server and emailed to clients as a file attachment.

The Tailwind CDN script is preserved — opening the file requires internet
access for full styling, but all interactivity (filtering, expand/collapse)
is pure DOM JavaScript with no server calls.
"""
from __future__ import annotations

import json
from pathlib import Path

_TEMPLATES_DIR = Path(__file__).resolve().parents[3] / "dashboard" / "app" / "templates"


def export_static_html(report, output_dir: str = ".") -> Path:
    """Render report.html as a self-contained static HTML file.

    report: AuditReport object or dashboard JSON dict (same format as
            export_dashboard_data produces).
    """
    try:
        from jinja2 import Environment, FileSystemLoader
    except ImportError:
        print("[html_exporter] jinja2 not installed — skipping HTML export.")
        print("  Install with: pip install jinja2")
        return Path(output_dir) / "report_missing_jinja2.html"

    payload      = _report_to_dict(report)
    account_id   = payload["account_id"]
    account_name = payload.get("account_name") or account_id
    date_str     = payload.get("generated_at", "")[:10].replace("-", "")

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=False,
    )
    env.filters["tojson"] = _tojson_filter

    html = env.get_template("report.html").render(
        report=payload,
        findings=payload.get("findings", []),
        page_title=account_name,
    )

    html = _strip_server_features(html)

    filename    = f"report_{account_id}_{date_str}.html"
    output_path = Path(output_dir) / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    print(f"[html_exporter] Static HTML written to {output_path}")
    return output_path


def _report_to_dict(report) -> dict:
    """Convert AuditReport object (or passthrough an existing dict)."""
    if isinstance(report, dict):
        return report

    return {
        "account_id":   report.account_id,
        "account_name": report.account_name,
        "generated_at": report.generated_at.isoformat(),
        "summary": {
            "total_monthly_savings_usd": report.total_monthly_savings_usd,
            "by_severity": {
                sev: len(items)
                for sev, items in report.findings_by_severity.items()
            },
            "by_category": {
                cat: {
                    "count":       len(items),
                    "savings_usd": round(
                        sum(f.estimated_monthly_savings_usd for f in items), 2
                    ),
                }
                for cat, items in report.findings_by_category.items()
            },
        },
        "findings": [
            {
                "id":                            f.id,
                "title":                         f.title,
                "description":                   f.description,
                "severity":                      f.severity.value,
                "category":                      f.category.value,
                "service":                       f.service,
                "region":                        f.region,
                "resource_id":                   f.resource_id,
                "estimated_monthly_savings_usd": f.estimated_monthly_savings_usd,
                "recommendation":                f.recommendation,
                "metadata":                      f.metadata,
            }
            for f in report.findings
        ],
    }


def _tojson_filter(obj, indent=None) -> str:
    return json.dumps(obj, indent=indent, default=str)


def _strip_server_features(html: str) -> str:
    """Remove the 'Re-run Audit' button (server-only feature)."""
    marker = 'onclick="triggerAudit('
    pos = html.find(marker)
    if pos == -1:
        return html
    button_start = html.rfind("<button", 0, pos)
    button_end   = html.find("</button>", pos)
    if button_start == -1 or button_end == -1:
        return html
    return html[:button_start] + html[button_end + len("</button>"):]
