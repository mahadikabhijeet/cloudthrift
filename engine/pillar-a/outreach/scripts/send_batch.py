#!/usr/bin/env python3
"""
Careful outreach sender — reads finalized drafts from crm/pipeline-state.json and
sends the named leads via Zoho SMTP, BCC'ing the owner for a record. DRY-RUN by
default (prints the exact message); only transmits with --send.

    python3 pillar-a/outreach/scripts/send_batch.py protex-ai metronome            # dry-run
    python3 pillar-a/outreach/scripts/send_batch.py protex-ai metronome --send     # transmit

Secrets come from ~/.config/finops-gmail/finops.env (never in git).
On send it marks the lead stage=contacted / first_sent=today in pipeline-state.json.
"""
import json, os, sys, ssl, smtplib, pathlib, datetime, argparse, subprocess, hashlib
from email.message import EmailMessage
import sys, pathlib as _pl
sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))
from voice_lint import lint_lead   # preflight guard, see voice_lint.py header

# Password lives in the macOS Keychain (not the env file). Fetched live at send-time
# so the secret never sits in env/git/logs. Override the item name via KEYCHAIN_SERVICE
# / KEYCHAIN_ACCOUNT env vars if these defaults don't match your Keychain entry.
KC_SERVICE = os.environ.get("KEYCHAIN_SERVICE", "finops-outreach")
KC_ACCOUNT = os.environ.get("KEYCHAIN_ACCOUNT", "")

def keychain_password():
    cmd = ["security", "find-generic-password", "-s", KC_SERVICE]
    if KC_ACCOUNT:
        cmd += ["-a", KC_ACCOUNT]
    cmd += ["-w"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return r.stdout.strip() or None
    except Exception:
        return None

ROOT  = pathlib.Path(__file__).resolve().parents[3]
STATE = ROOT / "crm" / "pipeline-state.json"
ENV   = pathlib.Path.home() / ".config" / "finops-gmail" / "finops.env"

def body_sha(subject, body):
    """Identity of a message as the recipient would see it."""
    return hashlib.sha256(((subject or "") + "\n" + (body or "")).encode()).hexdigest()[:16]

def load_env():
    d = {}
    for line in ENV.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            k = k.strip()
            if k.startswith("export "): k = k[len("export "):].strip()
            d[k] = v.strip().strip('"').strip("'")
    return d

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="+")
    ap.add_argument("--send", action="store_true")
    a = ap.parse_args()
    env = load_env()
    host = env["FINOPS_SMTP_HOST"]; port = int(env.get("FINOPS_SMTP_PORT", "465"))
    user = env["FINOPS_SMTP_USER"]
    pw = keychain_password() or env.get("FINOPS_SMTP_PASSWORD")   # Keychain first, env fallback
    if not pw:
        sys.exit(f"No password from Keychain (service '{KC_SERVICE}') or env. "
                 f"Set the right item name via KEYCHAIN_SERVICE / KEYCHAIN_ACCOUNT.")
    src = "Keychain" if keychain_password() else "env"
    print(f"[auth] using password from {src}; SMTP {user}@{host}:{port}")
    sender_name = env.get("FINOPS_SENDER_NAME", "Abhijeet Mahadik")
    s = json.loads(STATE.read_text())
    by_id = {l["id"]: l for l in s["leads"]}
    today = datetime.date.today().isoformat()
    sent = 0

    for lid in a.ids:
        l = by_id.get(lid)
        if not l: print(f"! no lead {lid}"); continue
        to = l.get("email", "").strip()
        if not to:
            print(f"! {lid}: no email, skipping"); continue

        # PREFLIGHT (added 2026-07-27) — refuse to transmit copy that fails the voice lint.
        # On 2026-07-27 three leads queued for send (Langfuse, Browserbase, Redpanda) had
        # draft_subject = null and would have gone out with a blank subject line; separately,
        # clickbait subjects and invented claims from the old draft_local.py prompt had
        # already reached Metronome and Treasury Prime on 07-25. A prompt is a request, this
        # is the guarantee. Same shape as the `<>` guard in the DevOps yt-upload.py: check
        # before the irreversible call. Skips the lead, never silently "fixes" it.
        problems = lint_lead(l)
        if problems:
            print(f"! {lid}: BLOCKED by voice lint, not sending ({len(problems)} problem(s)):")
            for p in problems:
                print(f"    - {p}")
            print(f"    fix the draft, then re-run. Lint alone: "
                  f"python3 pillar-a/outreach/scripts/voice_lint.py {lid}")
            continue

        # DUPLICATE-SEND GUARD (added 2026-08-01) — refuse to transmit copy this address
        # has already received. The lint checks whether a draft is GOOD; this checks whether
        # it is NEW, which is a different failure. It matters because draft_* is a staging
        # slot that still holds the LAST thing sent: after the 07-28 batch, all 12 contacted
        # leads had already-transmitted copy sitting in draft_*, and on 4 of them (Metronome,
        # Treasury Prime, Qdrant, Griffin) it was the day-3 bump promoted at send time. A
        # plain `draft_* == sent_*` equality test catches NONE of those, because sent_* holds
        # the first touch while draft_* holds the bump. So identity is a hash of the actual
        # subject+body, checked against sent_log — the per-lead record of what really went
        # out. Nothing here is auto-"fixed": a blocked lead needs its next draft promoted.
        h = body_sha(l.get("draft_subject"), l.get("draft_body"))
        prior = next((x for x in l.get("sent_log", []) if x.get("sha") == h), None)
        if prior:
            print(f"! {lid}: BLOCKED as duplicate — this exact message already went to {to} "
                  f"on {prior.get('date')} ({prior.get('note','')}).")
            print(f"    draft_* still holds already-sent copy. Promote the next touch "
                  f"(e.g. bump_subject/bump_body -> draft_subject/draft_body) then re-run.")
            continue

        msg = EmailMessage()
        msg["From"] = f"{sender_name} <{user}>"
        msg["To"] = to
        msg["Bcc"] = user                       # keep a copy in the sending inbox
        msg["Subject"] = l["draft_subject"]
        msg.set_content(l["draft_body"])
        print("="*66)
        print(f"To: {to}   (email confidence {l.get('email_confidence','?')}%)")
        print(f"Subject: {l['draft_subject']}")
        print(l["draft_body"])
        if a.send:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=ctx) as smtp:
                smtp.login(user, pw)
                smtp.send_message(msg)
            l["stage"] = "contacted"
            l.setdefault("first_sent", today)     # don't let a bump overwrite the first touch date
            l["last_sent"] = today
            l["next_action"] = "Day-3 bump if no reply"
            l["next_date"] = (datetime.date.today() + datetime.timedelta(days=3)).isoformat()
            # Record what actually went out, so the guard above can see it next time and the
            # scorecard stops depending on hand-maintained history.
            l.setdefault("sent_log", []).append(
                {"date": today, "subject": l["draft_subject"], "sha": h, "note": "sent by send_batch"})
            s.setdefault("send_history", []).append(
                {"date": today, "lead": lid, "email": to,
                 "method": l.get("email_method", l.get("verification", "unknown")),
                 "outcome": "sent — awaiting bounce window"})
            print(f">>> SENT to {to}, BCC {user}")
            sent += 1
    if a.send and sent:
        STATE.write_text(json.dumps(s, indent=2))
        print(f"\nstate updated ({sent} lead(s) moved to contacted).")
    elif a.send:
        # Every lead was skipped or blocked. Saying "stages moved to contacted" here would
        # be a false record of an outreach that never happened.
        print("\nNothing was transmitted, so state is unchanged.")
    else:
        print("\nDRY-RUN only. Re-run with --send to transmit.")

if __name__ == "__main__":
    main()
