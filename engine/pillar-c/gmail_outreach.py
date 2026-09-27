"""
Pillar C — Gmail Outreach  (prompt-cached, rate-limited, CAN-SPAM compliant)

Sends personalised cold outreach emails to decision makers.

Features:
  - Claude (Sonnet) composes each email from a cached system prompt
  - Gmail API rate limiting: max 500 sends/day, 1 req/sec between sends
  - CAN-SPAM compliant: every email includes an unsubscribe footer with
    physical address
  - Follow-up scheduling: sent log records send date; marks follow_up_due
    after 5 days
  - Per-recipient error tracking: Gmail API failures are logged to the
    sent log without crashing the batch
  - Deduplication: will not re-send to an address already in the sent log
    (unless force_resend=True)

Required env vars:
    ANTHROPIC_API_KEY        — for email composition via Claude
    GMAIL_CREDENTIALS_JSON   — path to OAuth2 credentials.json
    GMAIL_TOKEN_JSON         — path to token.json (created on first run)

Optional env vars:
    FINOPS_SENDER_NAME       — display name in From header (default: "Alex")
    FINOPS_COMPANY_ADDRESS   — physical address for CAN-SPAM footer
                               (MUST be set for production use)
"""
from __future__ import annotations

import base64
import json
import os
import time
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import anthropic

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    GMAIL_AVAILABLE = True
except ImportError:
    GMAIL_AVAILABLE = False

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GMAIL_SCOPES      = ["https://www.googleapis.com/auth/gmail.send"]
SENDER_NAME       = os.environ.get("FINOPS_SENDER_NAME", "Alex")
COMPANY_ADDRESS   = os.environ.get(
    "FINOPS_COMPANY_ADDRESS",
    "FinOps Platform, 123 Cloud Street, San Francisco, CA 94105",
)

MAX_EMAILS_PER_DAY = 500   # Gmail API hard limit
MIN_SEND_INTERVAL  = 1.0   # seconds between sends

FOLLOW_UP_DAYS = 5

SENT_LOG_PATH = Path(".sent_log.json")

# ---------------------------------------------------------------------------
# Email composition system prompt — stable so it caches across the batch.
# The f-string uses module-level constants, not per-request data, so the
# rendered string is identical for every request in a session.
# ---------------------------------------------------------------------------

_COMPOSE_SYSTEM_PROMPT = f"""\
You are a B2B sales copywriter helping {SENDER_NAME}, a FinOps consultant, write
short cold outreach emails to engineering and infrastructure leaders at companies
that are likely overspending on AWS.

Style guidelines:
- 3–4 sentences maximum in the body (before sign-off)
- Reference a specific, plausible cost pain relevant to the company's size and
  industry (NAT Gateway egress, idle EC2, over-provisioned RDS, etc.)
- Offer a free 30-minute cloud cost audit as the call to action
- Sound like a real human wrote it — no buzzwords, no corporate-speak
- End with a simple yes/no question to reduce friction
- Sign off as: {SENDER_NAME}
- Do NOT include a subject line — output only the email body text
- Do NOT include an unsubscribe line — it will be appended automatically
""".strip()


class GmailOutreach:
    """
    Compose and send personalised cold emails via Gmail.

    Usage:
        outreach = GmailOutreach()
        outreach.send(contact, company, dry_run=True)   # preview
        outreach.send(contact, company, dry_run=False)  # live send
    """

    def __init__(self) -> None:
        self.anthropic        = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self._sent_log        = self._load_sent_log()
        self._daily_count     = 0
        self._last_send_time  = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send(
        self,
        contact: dict,
        company: dict,
        dry_run: bool = False,
        force_resend: bool = False,
    ) -> bool:
        """
        Compose and send a personalised email to a decision maker.

        Args:
            contact:      dict with keys: name, title, email (or email_best_guess)
            company:      dict with keys: company_name, recommended_angle
            dry_run:      If True, print the email instead of sending it
            force_resend: If True, send even if this address is in the sent log

        Returns:
            True if the email was sent (or printed in dry_run mode).
            False if skipped (duplicate, missing email, or daily limit hit).
        """
        email = (contact.get("email_best_guess") or contact.get("email", "")).strip()
        if not email:
            return False

        if not force_resend and email in self._sent_log:
            prior = self._sent_log[email]
            if not prior.get("error"):
                print(f"[gmail_outreach] Skipping {email} (already sent {prior.get('sent_at','?')})")
                return False

        if not dry_run and self._daily_count >= MAX_EMAILS_PER_DAY:
            print(f"[gmail_outreach] Daily limit ({MAX_EMAILS_PER_DAY}) reached. Stopping.")
            return False

        body     = self._compose(contact, company)
        subject  = f"Quick question about {company.get('company_name', 'your')} cloud spend"
        full_body = body + self._unsubscribe_footer()

        if dry_run:
            print(
                f"\n{'─'*60}\n"
                f"[DRY RUN]\n"
                f"To:      {email}\n"
                f"Subject: {subject}\n\n"
                f"{full_body}\n"
                f"{'─'*60}"
            )
            self._record_sent(email, sent=False, dry_run=True)
            return True

        # Rate limiting: enforce minimum interval between sends
        elapsed = time.monotonic() - self._last_send_time
        if elapsed < MIN_SEND_INTERVAL:
            time.sleep(MIN_SEND_INTERVAL - elapsed)

        error_msg: str | None = None
        try:
            self._send_via_gmail(to=email, subject=subject, body=full_body)
            self._daily_count += 1
            self._last_send_time = time.monotonic()
            print(f"[gmail_outreach] ✓ Sent to {email} ({self._daily_count}/{MAX_EMAILS_PER_DAY} today)")
        except Exception as exc:
            error_msg = str(exc)
            print(f"[gmail_outreach] ✗ Failed to send to {email}: {error_msg}")

        self._record_sent(email, sent=error_msg is None, error=error_msg)
        return error_msg is None

    def send_batch(
        self,
        contacts: list[dict],
        companies: dict[str, dict],
        dry_run: bool = False,
    ) -> dict[str, int]:
        """
        Send emails to a list of contacts.

        Args:
            contacts:  list of contact dicts (each must have 'email' and
                       'company_name' to look up in `companies`)
            companies: mapping from company_name → ValidatedLead-style dict
            dry_run:   preview mode

        Returns:
            {"sent": int, "skipped": int, "failed": int}
        """
        stats: dict[str, int] = {"sent": 0, "skipped": 0, "failed": 0}
        for contact in contacts:
            company_name = contact.get("company_name") or ""
            company = companies.get(company_name, {"company_name": company_name, "recommended_angle": ""})
            ok = self.send(contact, company, dry_run=dry_run)
            if ok:
                stats["sent"] += 1
            elif contact.get("email") or contact.get("email_best_guess"):
                stats["skipped"] += 1
        return stats

    def pending_followups(self) -> list[dict]:
        """Return entries whose follow-up is due and hasn't been sent yet."""
        now = datetime.now(timezone.utc)
        due = []
        for email, entry in self._sent_log.items():
            if entry.get("follow_up_sent") or entry.get("error") or entry.get("dry_run"):
                continue
            due_str = entry.get("follow_up_due", "")
            if not due_str:
                continue
            try:
                if now >= datetime.fromisoformat(due_str):
                    due.append({"email": email, **entry})
            except ValueError:
                pass
        return due

    def mark_followup_sent(self, email: str) -> None:
        """Call this after successfully sending a follow-up to a contact."""
        if email in self._sent_log:
            self._sent_log[email]["follow_up_sent"] = True
            SENT_LOG_PATH.write_text(json.dumps(self._sent_log, indent=2))

    # ------------------------------------------------------------------
    # Email composition
    # ------------------------------------------------------------------

    def _compose(self, contact: dict, company: dict) -> str:
        """
        Ask Claude to write a personalised email body.

        The system prompt is cached — first request in a batch warms the
        cache; all subsequent requests pay ~10% of system-prompt tokens.
        """
        name         = contact.get("name", "there")
        title        = contact.get("title", "")
        angle        = company.get("recommended_angle", "")
        company_name = company.get("company_name", "your company")

        user_prompt = (
            f"Write a cold outreach email to {name}"
            + (f" ({title})" if title else "")
            + f" at {company_name}.\n"
        )
        if angle:
            user_prompt += f"\nContext about their likely cloud situation: {angle}\n"

        response = self.anthropic.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=400,
            system=[
                {
                    "type": "text",
                    "text": _COMPOSE_SYSTEM_PROMPT,
                    # Stable system prompt — cache it across the whole batch.
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_prompt}],
        )
        return next(
            (b.text for b in response.content if b.type == "text"), ""
        ).strip()

    # ------------------------------------------------------------------
    # CAN-SPAM footer (required by law for commercial email)
    # ------------------------------------------------------------------

    @staticmethod
    def _unsubscribe_footer() -> str:
        return (
            f"\n\n---\n"
            f"You are receiving this email because your company was identified as a potential "
            f"AWS cost-optimisation candidate. To unsubscribe, reply with 'unsubscribe' in the "
            f"subject line.\n"
            f"{COMPANY_ADDRESS}"
        )

    # ------------------------------------------------------------------
    # Gmail API
    # ------------------------------------------------------------------

    def _send_via_gmail(self, to: str, subject: str, body: str) -> None:
        if not GMAIL_AVAILABLE:
            raise RuntimeError(
                "google-auth-oauthlib and google-api-python-client must be installed. "
                "Run: pip install google-auth-oauthlib google-api-python-client"
            )
        service = self._get_gmail_service()
        msg = MIMEMultipart("alternative")
        msg["To"]      = to
        msg["Subject"] = subject
        msg["From"]    = f"{SENDER_NAME} <me>"
        msg.attach(MIMEText(body, "plain"))
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        service.users().messages().send(userId="me", body={"raw": raw}).execute()

    def _get_gmail_service(self):
        creds = None
        token_path = Path(os.environ.get("GMAIL_TOKEN_JSON", "token.json"))
        creds_path = Path(os.environ.get("GMAIL_CREDENTIALS_JSON", "credentials.json"))

        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), GMAIL_SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), GMAIL_SCOPES)
                creds = flow.run_local_server(port=0)
            token_path.write_text(creds.to_json())
        return build("gmail", "v1", credentials=creds)

    # ------------------------------------------------------------------
    # Sent log persistence
    # ------------------------------------------------------------------

    def _load_sent_log(self) -> dict[str, dict]:
        if SENT_LOG_PATH.exists():
            try:
                return json.loads(SENT_LOG_PATH.read_text())
            except Exception:
                return {}
        return {}

    def _record_sent(
        self,
        email: str,
        sent: bool = True,
        error: str | None = None,
        dry_run: bool = False,
    ) -> None:
        now = datetime.now(timezone.utc)
        self._sent_log[email] = {
            "sent_at":        now.isoformat(),
            "follow_up_due":  (now + timedelta(days=FOLLOW_UP_DAYS)).isoformat() if sent else None,
            "follow_up_sent": False,
            "error":          error,
            "dry_run":        dry_run,
        }
        try:
            SENT_LOG_PATH.write_text(json.dumps(self._sent_log, indent=2))
        except Exception as exc:
            print(f"[gmail_outreach] Warning: could not write sent log: {exc}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Gmail outreach sender")
    parser.add_argument("contacts_file", help="JSON file of contacts from decision_maker_finder")
    parser.add_argument("--companies-file", help="JSON file of validated leads (for recommended_angle)")
    parser.add_argument("--dry-run", action="store_true", help="Print emails without sending")
    parser.add_argument("--pending-followups", action="store_true", help="List contacts due for follow-up")
    args = parser.parse_args()

    outreach = GmailOutreach()

    if args.pending_followups:
        due = outreach.pending_followups()
        print(json.dumps(due, indent=2))
    else:
        contacts = json.loads(Path(args.contacts_file).read_text())
        companies: dict[str, dict] = {}
        if args.companies_file:
            for lead in json.loads(Path(args.companies_file).read_text()):
                companies[lead["company_name"]] = lead
        stats = outreach.send_batch(contacts, companies, dry_run=args.dry_run)
        print(f"\n[gmail_outreach] Done: {stats}")
