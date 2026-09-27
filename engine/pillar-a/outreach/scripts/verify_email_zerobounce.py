#!/usr/bin/env python3
"""
Close the last gap in email verification using ZeroBounce.

Git commit history gives us candidate addresses for free, but it cannot tell us
whether a PATTERN-INFERRED address actually exists. Facilio proved that on
2026-07-26: the firstname@facilio.com pattern was correctly confirmed from four
independent people, the name form was confirmed on LinkedIn, and
yogendrababu@facilio.com still bounced. Only a verifier closes that gap.

Credits are scarce (5 on the free tier), so this script is deliberately stingy:

  - `--credits` and `--sandbox` are FREE, use them to prove the setup works
  - an `unknown` result is never charged by ZeroBounce, so retries are cheap
  - addresses already proven (verified-in-use / delivered) are SKIPPED, never
    re-verified, because spending a credit to re-confirm a delivered address is
    pure waste
  - the script checks the live balance first and refuses to start a run it
    cannot finish

API key: macOS Keychain, service `zerobounce`, account `api`. Store it with
    security add-generic-password -U -s zerobounce -a api -w
Falls back to the ZEROBOUNCE_API_KEY env var.

Usage:
    python3 verify_email_zerobounce.py --credits
    python3 verify_email_zerobounce.py --sandbox
    python3 verify_email_zerobounce.py --dry baseten langfuse
    python3 verify_email_zerobounce.py baseten langfuse
    python3 verify_email_zerobounce.py --email prabhu@facilio.com
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys
import urllib.parse
import urllib.request

STATE = pathlib.Path(__file__).resolve().parents[3] / "crm" / "pipeline-state.json"
BASE = "https://api.zerobounce.net/v2"

KC_SERVICE = os.environ.get("ZB_KEYCHAIN_SERVICE", "zerobounce")
KC_ACCOUNT = os.environ.get("ZB_KEYCHAIN_ACCOUNT", "api")

# status -> (safe_to_send, confidence, label)
VERDICT = {
    "valid":       (True,  97, "zb-valid"),
    "catch-all":   (None,  60, "zb-catch-all"),
    "unknown":     (None,   0, "zb-unknown"),
    "invalid":     (False,  0, "zb-invalid"),
    "spamtrap":    (False,  0, "zb-spamtrap"),
    "abuse":       (False,  0, "zb-abuse"),
    "do_not_mail": (False,  0, "zb-do-not-mail"),
}
# These already have real-world proof. Never spend a credit on them.
PROVEN = {"delivered", "verified-in-use"}


def api_key():
    try:
        r = subprocess.run(
            ["security", "find-generic-password", "-s", KC_SERVICE, "-a", KC_ACCOUNT, "-w"],
            capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return os.environ.get("ZEROBOUNCE_API_KEY")


def call(path, params):
    url = f"{BASE}/{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "cloudthrift-outreach"})
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.load(r)


FINDER_COST = 20  # a SUCCESSFUL guessformat search bills 20 credits; failures bill 0


def credits(key):
    try:
        return int(call("getcredits", {"api_key": key}).get("Credits", -1))
    except Exception as e:
        print(f"  credit check failed: {e}")
        return -1


def find_email(key, domain, first=None, last=None, company=None):
    """Email Finder (guessformat). Use ONLY when git gives no candidate to validate.

    Costs 20 credits on success vs 1 for a validation, so it is 20x the price of
    checking a candidate we already derived for free from commit history. It earns
    that when there is genuinely nothing to check — e.g. Protex AI, whose GitHub org
    has 0 public repos and 0 public members. Undetermined results are free.
    """
    params = {"api_key": key}
    if domain:
        params["domain"] = domain
    if company:
        params["company_name"] = company
    if first:
        params["first_name"] = first
    if last:
        params["last_name"] = last
    return call("guessformat", params)


def validate(key, email):
    return call("validate", {"api_key": key, "email": email, "ip_address": ""})


def show(email, res):
    st = (res.get("status") or "?").lower()
    sub = res.get("sub_status") or ""
    safe, conf, label = VERDICT.get(st, (None, 0, f"zb-{st}"))
    mark = {True: "OK   ", False: "BLOCK", None: "?    "}[safe]
    print(f"  [{mark}] {email:<34} {st}{'/' + sub if sub else ''}"
          f"{'  (no credit charged)' if st == 'unknown' else ''}")
    return st, sub, safe, conf, label


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*", help="lead ids from pipeline-state.json")
    ap.add_argument("--email", help="verify a single raw address, not a lead")
    ap.add_argument("--credits", action="store_true", help="show balance and exit (free)")
    ap.add_argument("--sandbox", action="store_true", help="run free sandbox tests and exit")
    ap.add_argument("--dry", action="store_true", help="show the plan and credit cost, call nothing")
    ap.add_argument("--find", metavar="DOMAIN",
                    help=f"Email Finder: discover an address from a name + domain. "
                         f"Costs {FINDER_COST} credits on success (failures free). Use only "
                         f"when git yields NO candidate to validate.")
    ap.add_argument("--first"), ap.add_argument("--last"), ap.add_argument("--company")
    a = ap.parse_args()

    key = api_key()
    if not key:
        sys.exit(f"No API key. Store it with:\n"
                 f"  security add-generic-password -U -s {KC_SERVICE} -a {KC_ACCOUNT} -w")

    if a.credits:
        print(f"ZeroBounce credits: {credits(key)}")
        return

    if a.sandbox:
        print("Sandbox (free, no credits consumed):")
        for e in ["valid@example.com", "invalid@example.com",
                  "catch_all@example.com", "unknown@example.com",
                  "spamtrap@example.com", "role_based@example.com"]:
            try:
                show(e, validate(key, e))
            except Exception as ex:
                print(f"  {e}: ERROR {ex}")
        print(f"\nCredits still at: {credits(key)}")
        return

    if a.find:
        have = credits(key)
        print(f"Email Finder — {FINDER_COST} credits on success, 0 if undetermined. "
              f"Balance: {have}")
        # --dry costs nothing, so it must short-circuit BEFORE the balance guard.
        if a.dry:
            print(f"  DRY RUN — would search {a.first or '?'} {a.last or ''} @ {a.find}"
                  f" (up to {FINDER_COST} credits). Nothing called.")
            return
        if 0 <= have < FINDER_COST:
            sys.exit(f"Refusing: a successful search needs {FINDER_COST} credits, you have {have}.\n"
                     f"Cheaper path first: mine git for a candidate "
                     f"(verify_email_git.py) and validate it for 1 credit.")
        res = find_email(key, a.find, a.first, a.last, a.company)
        email = (res.get("email") or "").strip()
        conf = res.get("email_confidence") or res.get("confidence") or ""
        if email:
            print(f"  FOUND  {email}   confidence={conf}")
            print(f"  (HIGH = validated in use, MEDIUM = may be in use, LOW = high risk)")
        else:
            print(f"  not determined — {res.get('failure_reason') or res}")
            print("  no credits consumed for an undetermined result")
        print(f"Credits remaining: {credits(key)}")
        return

    if a.email:
        targets = [{"id": "(raw)", "email": a.email, "email_status": ""}]
        state = None
    else:
        if not a.ids:
            sys.exit("give lead ids, or --email, or --sandbox / --credits")
        state = json.loads(STATE.read_text())
        by_id = {l["id"]: l for l in state["leads"]}
        targets = []
        for i in a.ids:
            l = by_id.get(i)
            if not l:
                print(f"  ! no lead '{i}'")
                continue
            if not (l.get("email") or "").strip():
                print(f"  - {i}: no address to verify, skipping")
                continue
            if l.get("email_status") in PROVEN:
                print(f"  - {i}: already {l['email_status']}, skipping (would waste a credit)")
                continue
            targets.append(l)

    if not targets:
        print("nothing to verify")
        return

    have = credits(key)
    print(f"\nCredits available: {have} | addresses to verify: {len(targets)}")
    if a.dry:
        for l in targets:
            print(f"  would verify {l['id']:<13} {l['email']}")
        print(f"\nDRY RUN — nothing called. Would cost up to {len(targets)} credits.")
        return
    if have >= 0 and len(targets) > have:
        sys.exit(f"Refusing to start: need up to {len(targets)} credits, have {have}. "
                 f"Verify fewer ids, most valuable first.")

    print()
    changed = False
    for l in targets:
        try:
            res = validate(key, l["email"])
        except Exception as e:
            print(f"  ! {l['id']}: {e}")
            continue
        if "error" in res:
            sys.exit(f"API error: {res['error']}")
        st, sub, safe, conf, label = show(l["email"], res)
        if state is None:
            continue
        l["zb_status"], l["zb_sub_status"] = st, sub
        if safe is True:
            l["email_status"], l["email_confidence"] = label, conf
            l["email_evidence"] = (l.get("email_evidence", "") +
                                   f" || ZEROBOUNCE {st}: address confirmed to exist.")
        elif safe is False:
            l["email_evidence"] = (l.get("email_evidence", "") +
                                   f" || ZEROBOUNCE {st}/{sub}: DO NOT SEND. Address cleared.")
            l["email"], l["email_confidence"] = "", 0
            l["email_status"] = "unverified-blocked"
            l["decision"] = ""
            l["next_action"] = f"ZeroBounce says {st}/{sub} — find another address before any send."
        else:
            l["email_confidence"] = conf or l.get("email_confidence", 0)
            l["email_evidence"] = (l.get("email_evidence", "") +
                                   f" || ZEROBOUNCE {st}: inconclusive, treat as unverified.")
        changed = True

    if state is not None and changed:
        STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False))
        print(f"\nstate updated -> {STATE}")
    print(f"Credits remaining: {credits(key)}")


if __name__ == "__main__":
    main()
