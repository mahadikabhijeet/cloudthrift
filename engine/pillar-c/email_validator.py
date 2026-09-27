"""
Pillar C — Email Validator  (Task 9 — zero cost)

Generates likely email addresses for a contact and validates them WITHOUT
any paid email-verification API (Hunter.io verification, NeverBounce, etc.).

Two-stage approach:
  Stage 1 — Pattern generation ($0)
      Generates the 8 most common corporate email formats from a first name,
      last name, and domain.  E.g. john.smith@acme.com, jsmith@acme.com …

  Stage 2 — MX record check ($0)
      Confirms the domain actually receives email.  If the domain has no MX
      record we skip it entirely rather than generating dead addresses.

  Stage 3 — SMTP RCPT TO probe ($0, optional)
      Opens an SMTP connection and issues RCPT TO without sending mail.
      Many mail servers accept all addresses (catch-all) so a 250 does NOT
      guarantee deliverability; a 550 is a reliable negative signal.
      Disabled by default (many corp firewalls block outbound 25/465/587
      from non-server IPs, and aggressive probing risks IP reputation).
      Enable with verify_smtp=True only in server environments.

Cost: $0.00 — DNS + socket calls only, no external APIs.

Optional integration with Hunter.io:
  If HUNTER_API_KEY is set, `find_verified_email()` calls Hunter's
  email-finder endpoint (25 free req/month) for a confidence-scored result.
  This module works fine without it.
"""
from __future__ import annotations

import json
import os
import smtplib
import socket
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

HUNTER_API = "https://api.hunter.io/v2"
HUNTER_MIN_CONFIDENCE = 50   # minimum Hunter confidence score to accept

# Ordered by real-world frequency (source: various email-format studies)
EMAIL_PATTERNS = [
    "{first}.{last}",        # john.smith
    "{first}{last}",         # johnsmith
    "{f}{last}",             # jsmith
    "{first}",               # john
    "{first}_{last}",        # john_smith
    "{f}.{last}",            # j.smith
    "{last}.{first}",        # smith.john
    "{last}{f}",             # smithj
]


@dataclass
class EmailCandidate:
    email: str
    pattern: str
    mx_valid: bool = False
    smtp_status: str = ""     # "accepted", "rejected", "unknown", "skipped"
    hunter_confidence: int = 0
    source: str = "generated"


@dataclass
class EmailValidationResult:
    first_name: str
    last_name: str
    domain: str
    candidates: list[EmailCandidate] = field(default_factory=list)
    best_guess: str = ""
    mx_records: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class EmailValidator:
    """
    Generates and validates email addresses for a contact at a given domain.

    Usage:
        ev = EmailValidator()
        result = ev.validate("John", "Smith", "acme.com")
        print(result.best_guess)
    """

    def __init__(self, verify_smtp: bool = False) -> None:
        self._verify_smtp = verify_smtp
        self._hunter_key = os.environ.get("HUNTER_API_KEY", "")
        self._mx_cache: dict[str, list[str]] = {}

    def validate(
        self,
        first_name: str,
        last_name: str,
        domain: str,
        title: str = "",
    ) -> EmailValidationResult:
        first  = _normalize(first_name)
        last   = _normalize(last_name)
        domain = domain.strip().lower().lstrip("www.")

        result = EmailValidationResult(
            first_name=first_name,
            last_name=last_name,
            domain=domain,
        )

        # Stage 1: MX check
        mx = self._get_mx_records(domain)
        result.mx_records = mx
        if not mx:
            result.notes.append(f"No MX records found for {domain} — email delivery unlikely")
            return result

        # Stage 2: Hunter.io (if key present and credits available)
        if self._hunter_key:
            hunter_email = self._try_hunter(first_name, last_name, domain)
            if hunter_email:
                result.best_guess = hunter_email
                result.candidates.append(EmailCandidate(
                    email=hunter_email,
                    pattern="hunter_io",
                    mx_valid=True,
                    smtp_status="skipped",
                    hunter_confidence=hunter_email,  # overwritten below
                    source="hunter",
                ))
                # Rebuild properly
                result.candidates.clear()
                cand = EmailCandidate(
                    email=hunter_email,
                    pattern="hunter_io",
                    mx_valid=True,
                    smtp_status="skipped",
                    source="hunter",
                )
                result.candidates.append(cand)
                return result

        # Stage 3: Generate pattern candidates
        candidates = _generate_candidates(first, last, domain)
        for cand in candidates:
            cand.mx_valid = True   # MX already confirmed above
            if self._verify_smtp:
                cand.smtp_status = _smtp_probe(cand.email, mx[0])
            else:
                cand.smtp_status = "skipped"
            result.candidates.append(cand)

        # Best guess: first pattern (most common format)
        if result.candidates:
            result.best_guess = result.candidates[0].email

        return result

    def validate_batch(self, contacts: list[dict]) -> list[dict]:
        """
        Validate emails for a list of contact dicts.
        Each dict must have: first_name, last_name, domain (or website).
        Adds email_best_guess and email_candidates keys.
        Returns only contacts where a best_guess was found.
        """
        enriched = []
        for contact in contacts:
            first  = contact.get("first_name", "")
            last   = contact.get("last_name", "")
            domain = contact.get("domain", "") or _url_to_domain(contact.get("website", ""))
            if not (first and last and domain):
                continue
            result = self.validate(first, last, domain)
            if result.best_guess:
                contact["email_best_guess"] = result.best_guess
                contact["email_candidates"] = [c.email for c in result.candidates]
                contact["email_mx_valid"]   = bool(result.mx_records)
                enriched.append(contact)
        return enriched

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_mx_records(self, domain: str) -> list[str]:
        if domain in self._mx_cache:
            return self._mx_cache[domain]
        try:
            import subprocess
            dig = subprocess.run(
                ["dig", "+short", "MX", domain],
                capture_output=True, text=True, timeout=5,
            )
            lines = [l.strip() for l in dig.stdout.strip().splitlines() if l.strip()]
            # MX records: "10 mail.acme.com." — sort by priority, extract hostname
            records: list[tuple[int, str]] = []
            for line in lines:
                parts = line.split()
                if len(parts) == 2:
                    try:
                        records.append((int(parts[0]), parts[1].rstrip(".")))
                    except ValueError:
                        pass
            records.sort(key=lambda x: x[0])
            mx_hosts = [r[1] for r in records]
            self._mx_cache[domain] = mx_hosts
            return mx_hosts
        except Exception:
            pass

        # Fallback: Python socket DNS (can't do MX directly — just confirm domain resolves)
        try:
            socket.getaddrinfo(domain, None)
            result = [domain]  # treat domain itself as fallback MX
            self._mx_cache[domain] = result
            return result
        except socket.gaierror:
            self._mx_cache[domain] = []
            return []

    def _try_hunter(self, first: str, last: str, domain: str) -> str:
        """Call Hunter.io email finder. Returns email string or ''."""
        try:
            params = urllib.parse.urlencode({
                "first_name":  first,
                "last_name":   last,
                "domain":      domain,
                "api_key":     self._hunter_key,
            })
            req = urllib.request.Request(
                f"{HUNTER_API}/email-finder?{params}",
                headers={"User-Agent": "FinOpsPlatform/1.0"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            email      = data.get("data", {}).get("email", "")
            confidence = data.get("data", {}).get("score", 0)
            if email and confidence >= HUNTER_MIN_CONFIDENCE:
                return email
        except Exception:
            pass
        return ""


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _normalize(name: str) -> str:
    """Lowercase, strip, remove non-alpha characters for pattern generation."""
    import re
    return re.sub(r"[^a-z]", "", name.strip().lower())


def _generate_candidates(first: str, last: str, domain: str) -> list[EmailCandidate]:
    if not first or not last:
        return []
    f = first[0]
    candidates = []
    seen: set[str] = set()
    for pattern in EMAIL_PATTERNS:
        local = pattern.format(first=first, last=last, f=f)
        email = f"{local}@{domain}"
        if email not in seen:
            seen.add(email)
            candidates.append(EmailCandidate(email=email, pattern=pattern))
    return candidates


def _smtp_probe(email: str, mx_host: str) -> str:
    """
    SMTP RCPT TO probe — optional, disabled by default.
    Returns "accepted", "rejected", or "unknown".

    NOTE: Many servers are catch-all and accept everything.
    A 550 rejection is reliable; a 250 acceptance is not.
    """
    try:
        with smtplib.SMTP(mx_host, port=25, timeout=10) as smtp:
            smtp.ehlo("finops-platform.io")
            code, _ = smtp.rcpt(email)
            if code == 250:
                return "accepted"
            elif code in (550, 551, 553):
                return "rejected"
            return "unknown"
    except Exception:
        return "unknown"


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
