"""
Pillar C — Tech Stack Validator  (Task 8 — zero cost)

Confirms AWS usage for a candidate company WITHOUT any paid tools.

Three free signal sources, layered cheapest-first:

  Layer 1 — HTTP header scan ($0, instant)
      Detects CloudFront, ALB/ELB, AWS Certificate Manager, S3 redirect,
      and API Gateway via response headers and TLS certificate issuer.

  Layer 2 — DNS lookup ($0, instant)
      Checks CNAME/A records for .cloudfront.net, .amazonaws.com,
      .awsglobalaccelerator.com, .elb.amazonaws.com signatures.

  Layer 3 — GitHub API ($0, 5000 req/hr unauthenticated, 15k with token)
      Searches the company's GitHub org (if discoverable) for repos
      containing Terraform, CloudFormation, CDK, or AWS SDK references.
      Set GITHUB_TOKEN env var to raise rate limits.

A lead is considered AWS-confirmed if it scores >= AWS_CONFIRM_THRESHOLD.
Each layer contributes to a score so partial evidence still counts.

Required env vars (all optional — degrades gracefully without them):
  GITHUB_TOKEN   — GitHub personal access token (raises rate limit to 15k/hr)
"""
from __future__ import annotations

import json
import os
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

GITHUB_API = "https://api.github.com"

# Score thresholds
AWS_CONFIRM_THRESHOLD = 3   # points needed to mark lead as AWS-confirmed

# Points per signal
POINTS = {
    "cloudfront_header":   3,
    "alb_header":          3,
    "acm_cert":            3,
    "s3_redirect":         2,
    "aws_dns_cname":       3,
    "aws_dns_mx":          1,
    "github_terraform":    2,
    "github_cfn":          2,
    "github_aws_sdk":      1,
    "job_posting_signal":  1,   # carried over from lead_scraper tech_signals
}


@dataclass
class ValidationResult:
    domain: str
    aws_confirmed: bool
    score: int
    signals: list[str] = field(default_factory=list)
    github_org: str = ""
    notes: list[str] = field(default_factory=list)


class TechStackValidator:
    """
    Validates whether a company uses AWS, using only free API/network calls.

    Usage:
        validator = TechStackValidator()
        result = validator.validate("acme.com", github_org="acme-corp")
        if result.aws_confirmed:
            ...
    """

    def __init__(self) -> None:
        self._github_token = os.environ.get("GITHUB_TOKEN", "")

    def validate(self, domain: str, github_org: str = "") -> ValidationResult:
        domain  = _clean_domain(domain)
        result  = ValidationResult(domain=domain, aws_confirmed=False, score=0)

        self._check_http_headers(result)
        self._check_dns(result)
        if github_org:
            result.github_org = github_org
            self._check_github(result, github_org)
        elif domain:
            # Try to guess the GitHub org from the domain
            guessed_org = domain.split(".")[0]
            if self._github_org_exists(guessed_org):
                result.github_org = guessed_org
                self._check_github(result, guessed_org)

        result.aws_confirmed = result.score >= AWS_CONFIRM_THRESHOLD
        return result

    def validate_batch(self, leads: list[dict]) -> list[dict]:
        """
        Validate a list of lead dicts (from lead_scraper/hn_scraper).
        Adds aws_confirmed, aws_score, and aws_signals keys to each lead dict.
        Returns only leads where aws_confirmed=True.
        """
        confirmed: list[dict] = []
        for lead in leads:
            domain = _url_to_domain(lead.get("website", ""))
            if not domain:
                continue
            result = self.validate(domain)
            if result.aws_confirmed:
                lead["aws_confirmed"]  = True
                lead["aws_score"]      = result.score
                lead["aws_signals"]    = result.signals
                lead["github_org"]     = result.github_org
                confirmed.append(lead)
                print(f"[validator] ✓ {domain} — AWS confirmed (score {result.score}): {result.signals}")
            else:
                print(f"[validator] ✗ {domain} — score {result.score}/{AWS_CONFIRM_THRESHOLD} (not confirmed)")
        return confirmed

    # ------------------------------------------------------------------
    # Layer 1: HTTP header scan
    # ------------------------------------------------------------------

    def _check_http_headers(self, result: ValidationResult) -> None:
        url = f"https://{result.domain}"
        try:
            ctx = ssl.create_default_context()
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "FinOpsPlatform/1.0"},
            )
            with urllib.request.urlopen(req, timeout=8, context=ctx) as resp:
                headers = {k.lower(): v.lower() for k, v in resp.headers.items()}
                cert    = resp.fp.raw._sock.getpeercert() if hasattr(resp.fp, "raw") else {}
        except urllib.error.HTTPError as exc:
            headers = {k.lower(): v.lower() for k, v in exc.headers.items()}
            cert    = {}
        except Exception as exc:
            result.notes.append(f"HTTP scan failed: {exc}")
            return

        # CloudFront
        if "cloudfront" in headers.get("via", "") or "cloudfront" in headers.get("x-amz-cf-id", ""):
            _add_signal(result, "cloudfront_header", f"CloudFront via header: {headers.get('via','')[:60]}")

        # ALB / API Gateway
        server = headers.get("server", "")
        if "awselb" in server or "awsalb" in server or "amazon" in headers.get("x-amzn-requestid", ""):
            _add_signal(result, "alb_header", f"ALB/APIGW server header: {server}")

        # S3 redirect
        if "x-amz-request-id" in headers or "x-amz-id-2" in headers:
            _add_signal(result, "s3_redirect", "S3 x-amz-request-id header present")

        # ACM certificate (TLS issuer)
        try:
            ctx2  = ssl.create_default_context()
            conn  = ctx2.wrap_socket(socket.create_connection((result.domain, 443), timeout=5),
                                     server_hostname=result.domain)
            der   = conn.getpeercert()
            conn.close()
            issuer = dict(x[0] for x in der.get("issuer", []))
            org    = issuer.get("organizationName", "")
            if "amazon" in org.lower():
                _add_signal(result, "acm_cert", f"TLS cert issued by Amazon: {org}")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Layer 2: DNS
    # ------------------------------------------------------------------

    def _check_dns(self, result: ValidationResult) -> None:
        aws_cname_patterns = [
            ".cloudfront.net", ".amazonaws.com",
            ".awsglobalaccelerator.com", ".elb.amazonaws.com",
            ".execute-api.", ".s3-website",
        ]
        try:
            # socket.getaddrinfo follows CNAMEs transparently; use a raw DNS check instead
            import subprocess
            dig = subprocess.run(
                ["dig", "+short", "CNAME", result.domain],
                capture_output=True, text=True, timeout=5,
            )
            cname_out = dig.stdout.strip().lower()
            for pattern in aws_cname_patterns:
                if pattern in cname_out:
                    _add_signal(result, "aws_dns_cname", f"CNAME resolves to {cname_out[:80]}")
                    break
        except Exception:
            # dig not available — skip silently
            pass

    # ------------------------------------------------------------------
    # Layer 3: GitHub
    # ------------------------------------------------------------------

    def _github_org_exists(self, org: str) -> bool:
        try:
            _gh_get(f"/orgs/{org}", self._github_token)
            return True
        except Exception:
            return False

    def _check_github(self, result: ValidationResult, org: str) -> None:
        checks = [
            ("terraform",       "github_terraform"),
            ("cloudformation",  "github_cfn"),
            ("aws-cdk",         "github_cfn"),
            ("boto3",           "github_aws_sdk"),
            ("aws-sdk",         "github_aws_sdk"),
        ]
        for keyword, signal_key in checks:
            if result.signals.count(signal_key) > 0:
                continue   # already scored this signal
            try:
                resp = _gh_get(
                    f"/search/code?q={urllib.parse.quote(keyword)}+org:{org}&per_page=1",
                    self._github_token,
                )
                if resp.get("total_count", 0) > 0:
                    _add_signal(result, signal_key, f"GitHub: found '{keyword}' in {org} repos")
            except Exception:
                pass


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _add_signal(result: ValidationResult, key: str, note: str) -> None:
    if key not in result.signals:
        result.signals.append(key)
        result.score += POINTS.get(key, 1)
        result.notes.append(note)


def _gh_get(path: str, token: str) -> dict:
    headers = {"Accept": "application/vnd.github.v3+json",
               "User-Agent": "FinOpsPlatform/1.0"}
    if token:
        headers["Authorization"] = f"token {token}"
    req = urllib.request.Request(f"{GITHUB_API}{path}", headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _clean_domain(domain: str) -> str:
    domain = domain.strip().lower()
    domain = re.sub(r"^https?://", "", domain) if (
        domain.startswith("http://") or domain.startswith("https://")
    ) else domain
    return domain.split("/")[0]


def _url_to_domain(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if not url.startswith("http"):
        url = "https://" + url
    try:
        return urllib.parse.urlparse(url).netloc.lstrip("www.") or ""
    except Exception:
        return ""


import re  # noqa: E402 — keep at bottom to avoid shadowing builtins above
