"""
Pillar D — FinOps Dashboard (FastAPI)

Serves audit findings produced by Pillar B as a REST API + HTML dashboard.

Reads dashboard JSON files written by pillar-b/engine/output/dashboard_data.py.
File naming convention: dashboard_<account_id>_<YYYYMMDD>.json

Environment variables:
    DATA_DIR    Directory containing dashboard_*.json files (default: ./data)
    PORT        HTTP port (default: 8000)

Endpoints:
    GET  /                              Dashboard index (HTML)
    GET  /account/{account_id}          Account report (HTML)
    GET  /health                        Health check (JSON)
    GET  /api/accounts                  List accounts with latest report summary
    GET  /api/accounts/{id}/report      Full report JSON
    GET  /api/accounts/{id}/findings    Paginated findings (supports ?severity=&category=)
    POST /api/accounts/{id}/run-audit   Trigger audit subprocess (returns job_id)
    GET  /api/jobs/{job_id}             Poll audit job status
"""
from __future__ import annotations

import asyncio
import glob
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

_here = Path(__file__).resolve().parent
_repo = _here.parents[2]

DATA_DIR = Path(os.environ.get("DATA_DIR", str(_here.parent / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="FinOps Platform",
    description="Cloud cost visibility and optimisation dashboard",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

templates = Jinja2Templates(directory=str(_here / "templates"))

_static_dir = _here / "static"
_static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

# In-memory job registry — keyed by job_id
_jobs: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _list_report_files() -> list[Path]:
    return sorted(DATA_DIR.glob("dashboard_*.json"), reverse=True)


def _latest_report_for(account_id: str) -> dict | None:
    files = sorted(DATA_DIR.glob(f"dashboard_{account_id}_*.json"), reverse=True)
    if not files:
        return None
    return json.loads(files[0].read_text())


def _all_accounts() -> list[dict]:
    """Return one summary entry per account (latest report only)."""
    seen: set[str] = set()
    accounts: list[dict] = []
    for f in _list_report_files():
        # filename: dashboard_<account_id>_<YYYYMMDD>.json
        parts = f.stem.split("_")
        if len(parts) < 3:
            continue
        account_id = parts[1]
        if account_id in seen:
            continue
        seen.add(account_id)
        try:
            report = json.loads(f.read_text())
            accounts.append({
                "account_id":   account_id,
                "account_name": report.get("account_name", account_id),
                "generated_at": report.get("generated_at", ""),
                "total_findings": report.get("summary", {}).get("total_findings", 0),
                "total_monthly_savings_usd": report.get("summary", {}).get("total_monthly_savings_usd", 0),
                "severity_counts": report.get("summary", {}).get("by_severity", {}),
            })
        except Exception:
            continue
    return accounts


def _severity_order(sev: str) -> int:
    return {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(sev, 4)


# ---------------------------------------------------------------------------
# HTML routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    accounts = _all_accounts()
    total_savings = sum(a["total_monthly_savings_usd"] for a in accounts)
    total_findings = sum(a["total_findings"] for a in accounts)
    return templates.TemplateResponse(request, "dashboard.html", {
        "accounts":       accounts,
        "total_savings":  total_savings,
        "total_findings": total_findings,
        "page_title":     "FinOps Dashboard",
    })


@app.get("/account/{account_id}", response_class=HTMLResponse)
async def account_report(request: Request, account_id: str):
    report = _latest_report_for(account_id)
    if not report:
        raise HTTPException(status_code=404, detail=f"No report found for {account_id}")

    findings = report.get("findings", [])
    findings.sort(key=lambda f: (
        -f.get("metadata", {}).get("priority_score", 0),
        _severity_order(f.get("severity", "low")),
    ))

    return templates.TemplateResponse(request, "report.html", {
        "report":     report,
        "findings":   findings,
        "page_title": f"Report — {report.get('account_name', account_id)}",
    })


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "data_dir": str(DATA_DIR), "reports": len(_list_report_files())}


@app.get("/api/accounts")
async def list_accounts():
    return {"accounts": _all_accounts()}


@app.get("/api/accounts/{account_id}/report")
async def get_report(account_id: str):
    report = _latest_report_for(account_id)
    if not report:
        raise HTTPException(status_code=404, detail=f"No report found for {account_id}")
    return report


@app.get("/api/accounts/{account_id}/findings")
async def get_findings(
    account_id: str,
    severity: str   = Query(default="", description="Filter: critical,high,medium,low"),
    category: str   = Query(default="", description="Filter: infra_hygiene,compute_strategy,network_storage,database_tuning,savings_plans"),
    page: int       = Query(default=1, ge=1),
    page_size: int  = Query(default=50, ge=1, le=200),
):
    report = _latest_report_for(account_id)
    if not report:
        raise HTTPException(status_code=404, detail=f"No report found for {account_id}")

    findings = report.get("findings", [])

    if severity:
        sev_set = {s.strip().lower() for s in severity.split(",")}
        findings = [f for f in findings if f.get("severity", "").lower() in sev_set]

    if category:
        cat_set = {c.strip().lower() for c in category.split(",")}
        findings = [f for f in findings if f.get("category", "").lower() in cat_set]

    findings.sort(key=lambda f: _severity_order(f.get("severity", "low")))

    total = len(findings)
    start = (page - 1) * page_size
    page_findings = findings[start: start + page_size]

    return {
        "total":     total,
        "page":      page,
        "page_size": page_size,
        "findings":  page_findings,
    }


@app.post("/api/accounts/{account_id}/run-audit")
async def trigger_audit(
    account_id: str,
    role_arn:    str = Query(default="", description="IAM role ARN to assume"),
    external_id: str = Query(default="", description="STS ExternalId"),
    region:      str = Query(default="us-east-1"),
    mock:        bool = Query(default=False, description="Use mock data (no AWS credentials needed)"),
):
    job_id = str(uuid.uuid4())[:8]

    _jobs[job_id] = {
        "job_id":     job_id,
        "account_id": account_id,
        "status":     "queued",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "logs":       [],
        "output_file": None,
    }

    asyncio.create_task(_run_audit_task(
        job_id=job_id,
        account_id=account_id,
        role_arn=role_arn,
        external_id=external_id,
        region=region,
        mock=mock,
    ))

    return {"job_id": job_id, "status": "queued", "account_id": account_id}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return job


@app.get("/api/jobs")
async def list_jobs():
    return {"jobs": list(_jobs.values())}


# ---------------------------------------------------------------------------
# Audit background task
# ---------------------------------------------------------------------------

async def _run_audit_task(
    job_id: str,
    account_id: str,
    role_arn: str,
    external_id: str,
    region: str,
    mock: bool,
) -> None:
    job = _jobs[job_id]
    job["status"] = "running"

    engine_path = str(_repo / "pillar-b" / "engine" / "main.py")
    cmd = [
        sys.executable, engine_path,
        "--account-id", account_id,
        "--region", region,
        "--output", "json",
        "--output-dir", str(DATA_DIR),
    ]

    if mock:
        cmd.append("--mock")
    else:
        if not role_arn or not external_id:
            job["status"] = "failed"
            job["logs"].append("ERROR: role_arn and external_id required for live audits")
            job["finished_at"] = datetime.now(timezone.utc).isoformat()
            return
        cmd += ["--role-arn", role_arn, "--external-id", external_id]

    job["logs"].append(f"Running: {' '.join(cmd)}")

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode(errors="replace")
        job["logs"].extend(output.splitlines())

        if proc.returncode == 0:
            job["status"] = "succeeded"
            # Find the output file that was just written
            files = sorted(DATA_DIR.glob(f"dashboard_{account_id}_*.json"), reverse=True)
            if files:
                job["output_file"] = str(files[0])
        else:
            job["status"] = "failed"
    except Exception as exc:
        job["status"] = "failed"
        job["logs"].append(f"Exception: {exc}")

    job["finished_at"] = datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=True)
