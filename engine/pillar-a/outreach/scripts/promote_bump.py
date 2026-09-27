#!/usr/bin/env python3
"""
Promote a queued follow-up (bump_subject/bump_body) into the send slot
(draft_subject/draft_body), which is the only thing send_batch.py transmits.

    python3 pillar-a/outreach/scripts/promote_bump.py baseten axiom          # dry-run
    python3 pillar-a/outreach/scripts/promote_bump.py baseten axiom --apply

Why this exists: promotion used to be a hand-edit, and hand-editing 8 leads under
time pressure is how the wrong thing gets sent. Two specific hazards it closes:

  1. It refuses to promote a bump that the address has ALREADY received (checked
     against sent_log). On 2026-08-01 four leads — Metronome, Treasury Prime,
     Qdrant, Griffin — still had their 2026-07-28 bump sitting in draft_*, so a
     careless "promote everything with a bump_*" would have double-sent to them.
  2. It never overwrites sent_subject/sent_body. Those archive the FIRST touch and
     are the only record of what a prospect originally read.

Leaves bump_* in place; send_batch's own duplicate guard is what stops a re-send.
"""
import json, sys, pathlib, argparse, hashlib

ROOT  = pathlib.Path(__file__).resolve().parents[3]
STATE = ROOT / "crm" / "pipeline-state.json"

def body_sha(subject, body):
    return hashlib.sha256(((subject or "") + "\n" + (body or "")).encode()).hexdigest()[:16]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="+")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    s = json.loads(STATE.read_text())
    by_id = {l["id"]: l for l in s["leads"]}
    promoted = 0

    for lid in a.ids:
        l = by_id.get(lid)
        if not l:
            print(f"! no lead {lid}"); continue
        if not l.get("bump_subject") or not l.get("bump_body"):
            print(f"! {lid}: no bump queued, skipping"); continue

        h = body_sha(l["bump_subject"], l["bump_body"])
        prior = next((x for x in l.get("sent_log", []) if x.get("sha") == h), None)
        if prior:
            print(f"! {lid}: REFUSING — this bump already went to {l.get('email')} "
                  f"on {prior.get('date')}. Draft a new touch instead.")
            continue

        print(f"  {lid}: draft_* <- bump_*   ({l['bump_subject']!r}, {len(l['bump_body'].split())} words)")
        if a.apply:
            l["draft_subject"] = l["bump_subject"]
            l["draft_body"]    = l["bump_body"]
        promoted += 1

    if a.apply and promoted:
        STATE.write_text(json.dumps(s, indent=2, ensure_ascii=False))
        print(f"\n{promoted} lead(s) promoted. Now dry-run send_batch.py before --send.")
    elif a.apply:
        print("\nNothing promoted, so state is unchanged.")
    else:
        print(f"\nDRY-RUN only ({promoted} would be promoted). Re-run with --apply.")

if __name__ == "__main__":
    main()
