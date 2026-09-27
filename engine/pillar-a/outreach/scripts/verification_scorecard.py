#!/usr/bin/env python3
"""
Close the loop on email verification: which sourcing method actually lands?

Every send is evidence. This reads crm/pipeline-state.json and scores each
verification method by delivered-vs-bounced, so the pipeline stops trusting a
method the data says is unreliable.

The distinction that matters (learned the hard way on 2026-07-26):

  DIRECTLY OBSERVED  — the exact address appears in public git commit history.
                       This is verification. 2/2 delivered so far.
  PATTERN-INFERRED   — the org's pattern is confirmed from other employees, but
                       THIS person's address was never observed. This is a guess
                       with good priors, not verification. Facilio proved it:
                       firstname@facilio.com was correctly confirmed from three
                       employees, yet yogendrababu@facilio.com still bounced,
                       because a pattern cannot tell you which form of someone's
                       name is used as the local part.
  SCRAPER PATTERN    — RocketReach/LeadIQ percentages. 2/5. Do not trust.

Run:  python3 pillar-a/outreach/scripts/verification_scorecard.py
"""
import json
import pathlib
from collections import defaultdict

STATE = pathlib.Path(__file__).resolve().parents[3] / "crm" / "pipeline-state.json"

# email_status -> which method produced the address
METHOD = {
    "delivered": None,          # resolved by evidence text, see classify()
    "verified-in-use": "git — directly observed",
    "pattern-confirmed": "git — pattern-inferred",
    "known-good": "previously delivered",
    "guessed": "scraper pattern",
    "bounced": None,
    "unverified-blocked": "blocked (no method worked)",
}


def classify(lead):
    """Best-effort attribution of the method that produced this address."""
    ev = (lead.get("email_evidence") or "").upper()
    if "GIT-VERIFIED" in ev:
        return "git — directly observed"
    if "GIT-CONFIRMED" in ev:
        return "git — pattern-inferred"
    if "USED IN THE FIRST SEND" in ev or "NO BOUNCE" in ev:
        return "previously delivered"
    if any(k in ev for k in ("ROCKETREACH", "LEADIQ", "CONTACTOUT", "PATTERN-HIGH", "SCRAPE")):
        return "scraper pattern"
    return "unattributed"


def outcome(lead):
    st = lead.get("email_status") or ""
    if st == "delivered" or lead.get("delivery_confirmed"):
        return "delivered"
    if st == "bounced" or lead.get("bounced"):
        return "bounced"
    return None  # not yet sent, no evidence either way


def main():
    state = json.loads(STATE.read_text())
    tally = defaultdict(lambda: {"delivered": 0, "bounced": 0, "who": []})

    # Prefer the append-only send_history. Current lead state is NOT a reliable
    # record: when a bounced address is replaced by a working one, the failure
    # disappears from the lead. History is the only honest source of outcomes.
    history = state.get("send_history") or []
    if history:
        for h in history:
            o = h.get("outcome")
            if o not in ("delivered", "bounced"):
                continue
            m = h.get("method") or "unattributed"
            tally[m][o] += 1
            tally[m]["who"].append(f"{h.get('lead')} ({'OK' if o == 'delivered' else 'BOUNCE'})")
    else:
        for l in state.get("leads", []):
            o = outcome(l)
            if not o:
                continue
            m = classify(l)
            tally[m][o] += 1
            tally[m]["who"].append(f"{l.get('id')} ({'OK' if o == 'delivered' else 'BOUNCE'})")

    print("Verification scorecard — delivered vs bounced, by how the address was found\n")
    order = ["git — directly observed", "previously delivered", "self-sourced + BuiltWith",
             "git — pattern-inferred", "scraper pattern", "unattributed"]
    rows = sorted(tally.items(), key=lambda kv: order.index(kv[0]) if kv[0] in order else 99)
    for method, t in rows:
        n = t["delivered"] + t["bounced"]
        rate = (100.0 * t["delivered"] / n) if n else 0.0
        print(f"  {method:<26} {t['delivered']}/{n}  ({rate:.0f}% delivered)")
        print(f"  {'':<26} {', '.join(t['who'])}")
    tot_d = sum(t["delivered"] for t in tally.values())
    tot_n = sum(t["delivered"] + t["bounced"] for t in tally.values())
    print(f"\n  {'OVERALL':<26} {tot_d}/{tot_n}  ({100.0*tot_d/tot_n:.0f}% delivered)" if tot_n else "")

    risky = [l for l in state.get("leads", [])
             if outcome(l) is None
             and classify(l) == "git — pattern-inferred"
             and (l.get("email") or "").strip()]
    if risky:
        print("\n  ⚠ Queued but PATTERN-INFERRED (not observed) — bounce risk:")
        for l in risky:
            print(f"      {l['id']:<13} {l['email']:<28} {l.get('contact','')}")


if __name__ == "__main__":
    main()
