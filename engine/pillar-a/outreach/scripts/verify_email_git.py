#!/usr/bin/env python3
"""Verify a prospect's email by mining public git commit history.

Why this exists: pattern-% guessing from scrapers (RocketReach/LeadIQ) measured ~40%
accurate in the 2026-07-25 batch — Protex AI scored 87% and still bounced. Public commit
history, by contrast, shows addresses that were *actually in use* by real employees.
Free, no signup, no LinkedIn login.

Caveat learned from Griffin: companies often run two address shapes at once, first@ for
early staff and first.last@ for later hires, and sometimes two mail domains. Read the
full output, don't just take the top hit.

Usage:
    python3 verify_email_git.py <github-org> [corp-domain] [--repos N]
    python3 verify_email_git.py griffinbank griffin.sh
    python3 verify_email_git.py qdrant qdrant.tech --repos 6

Unauthenticated GitHub API allows 60 requests/hour; each run costs 1 + N requests.
"""
import argparse
import collections
import json
import sys
import urllib.request

API = "https://api.github.com"


def get(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "cloudthrift-outreach"})
        return json.load(urllib.request.urlopen(req, timeout=25))
    except Exception as exc:
        return {"__err": str(exc)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("org", help="GitHub org login, e.g. griffinbank")
    ap.add_argument("domain", nargs="?", default=None,
                    help="corporate mail domain to highlight, e.g. griffin.sh")
    ap.add_argument("--repos", type=int, default=4,
                    help="how many most-recently-pushed repos to scan (default 4)")
    args = ap.parse_args()

    repos = get(f"{API}/orgs/{args.org}/repos?per_page=100&sort=pushed")
    if isinstance(repos, dict):
        print(f"error listing repos: {repos.get('__err') or repos.get('message')}")
        return 1
    if not repos:
        print(f"{args.org}: 0 public repos — git method yields nothing here, "
              f"fall back to manual LinkedIn verification.")
        return 2

    print(f"{args.org}: {len(repos)} public repos, scanning {min(args.repos, len(repos))}")
    counts = collections.Counter()
    for repo in sorted(repos, key=lambda r: r.get("pushed_at") or "", reverse=True)[:args.repos]:
        commits = get(f"{API}/repos/{args.org}/{repo['name']}/commits?per_page=100")
        if isinstance(commits, dict):
            continue
        for c in commits:
            a = c["commit"]["author"]
            counts[(a["name"], a["email"])] += 1

    if args.domain:
        stem = args.domain.split(".")[0].lower()
        corp = [(n, e, k) for (n, e), k in counts.items() if stem in e.lower()]
        print(f"\n--- addresses on the corporate domain ({args.domain}) ---")
        for n, e, k in sorted(corp, key=lambda t: -t[2]):
            print(f"  {k:4}  {n}  <{e}>")
        if not corp:
            print("  (none — employees commit with personal addresses, or the corp "
                  "domain differs from what you assumed)")

    print("\n--- top authors overall ---")
    for (n, e), k in counts.most_common(20):
        print(f"  {k:4}  {n}  <{e}>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
