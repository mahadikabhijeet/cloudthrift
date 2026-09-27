#!/usr/bin/env python3
"""
voice_lint.py — preflight check for prospect-facing outreach copy.

Why this exists (2026-07-27): draft_local.py's SYSTEM prompt was itself instructing the
model to write a clickbait "wasted-%" subject, "Hi {name}", invented scarcity ("bandwidth
for 2 consults"), an invented turnaround ("within 48 hours") and a checklist CTA that is
not the real offer. The model obeyed faithfully. Two of those drafts reached real
prospects (Metronome, Treasury Prime, 2026-07-25) before anyone noticed, and a third
invented a valuation figure for Zilliz.

The prompt is fixed, but a prompt is a request and a lint is a guarantee. Same reasoning
as the `<>` preflight guard in the DevOps yt-upload.py: check before the irreversible call.

Rules encode 01-core/writing-voice.md (aios) + the settled offer.
Used by: draft_local.py (flags), send_batch.py (HARD BLOCK before SMTP).

Standalone:  python3 voice_lint.py            # lint every lead that has a draft
             python3 voice_lint.py <id> ...   # lint specific leads
Exit code 1 if any linted lead fails.
"""
import json, re, sys, pathlib

STATE = pathlib.Path(__file__).resolve().parents[3] / "crm" / "pipeline-state.json"

SIG_TAIL = "mob: +91 8329560186"

# (needle, human explanation). Matched case-insensitively against the body.
BODY_BANNED = [
    ("—",                    "em-dash (writing-voice hard no)"),
    (";",                    "semicolon (writing-voice hard no)"),
    ("–",                    "en-dash (writing-voice hard no)"),
    ("’",                    "curly apostrophe (AI tell, use ')"),
    ("“",                    "curly quote (AI tell)"),
    ("”",                    "curly quote (AI tell)"),
    ("!",                    "exclamation mark (writing-voice hard no)"),
    ("subject:",             "literal 'Subject:' leaked into the body"),
    ("hope this email finds you well", "banned AI filler"),
    ("hope this finds you well",       "banned AI filler"),
    ("i wanted to reach out", "banned AI filler"),
    ("delve",                "banned corporate tell"),
    ("leverage",             "banned corporate tell"),
    ("streamline",           "banned corporate tell"),
    ("elevate",              "banned corporate tell"),
    ("unlock",               "banned corporate tell"),
    ("seamless",             "banned corporate tell"),
    ("circle back",          "banned corporate tell"),
    ("synergy",              "banned corporate tell"),
    # invented claims the old prompt mandated — none of these are in the real offer
    ("bandwidth for",        "invented scarcity, not part of the offer"),
    ("consults this month",  "invented scarcity, not part of the offer"),
    ("within 48 hours",      "invented turnaround claim"),
    ("1-page checklist",     "wrong CTA, the offer is a free 30 minute read only scan"),
    ("one page checklist",   "wrong CTA, the offer is a free 30 minute read only scan"),
    ("5-day cost audit",     "wrong offer for a first touch"),
    ("druva",                "employer must never be named"),
]

SUBJ_BANNED = [
    ("%",             "waste-% in the subject is a fabricated claim about their bill"),
    ("(quick check)", "clickbait tic from the old prompt"),
    ("!",             "exclamation mark"),
    ("subject:",      "literal 'Subject:' inside the subject"),
]


def lint_lead(lead, subject_field="draft_subject", body_field="draft_body"):
    """Return a list of human-readable problems. Empty list == clean."""
    problems = []
    subj = (lead.get(subject_field) or "").strip()
    body = (lead.get(body_field) or "").strip()

    # --- subject -------------------------------------------------------
    if not subj:
        problems.append(f"MISSING SUBJECT ({subject_field} is empty or null) "
                        "— would transmit with a blank subject line")
    else:
        low = subj.lower()
        for needle, why in SUBJ_BANNED:
            if needle in low:
                problems.append(f"subject contains {needle!r}: {why}")
        if re.search(r"\d+\s*%", subj):
            problems.append("subject states a % figure about their bill (fabricated claim)")
        if subj[:1].isupper() and not subj.lower().startswith("re:"):
            problems.append("subject starts capitalised — house style is lowercase-ish "
                            "(e.g. \"quick thought on acme's aws spend\")")

    # --- body ----------------------------------------------------------
    if not body:
        problems.append(f"MISSING BODY ({body_field} is empty or null)")
        return problems

    low = body.lower()
    for needle, why in BODY_BANNED:
        if needle.lower() in low:
            problems.append(f"body contains {needle!r}: {why}")

    if not re.match(r"\s*Hey\s+\S", body):
        problems.append('body must open with "Hey <name>," (writing-voice signature opener)')
    if not body.rstrip().endswith(SIG_TAIL):
        problems.append(f"body must end with the signature block ({SIG_TAIL!r}) "
                        "— send_batch.py does not append one")
    if "you owe me nothing" not in low:
        problems.append("body is missing the guarantee line (\"you owe me nothing\")")
    if not re.search(r"30\s*(-|\s)?min", low):
        problems.append("body is missing the free 30 minute read only scan offer")

    # Mangled punctuation (added 2026-08-01). Modal and Depot both reached the send queue
    # reading "...if that is not you,." — the stray comma survived every other gate because
    # nothing here was checking mechanics at the character level. A prospect reads that as
    # carelessness before they read the offer, and it is the cheapest possible thing to catch.
    for pat, why in (
        (r",\s*\.",  "comma immediately before a full stop"),
        (r"\s+,",     "space before a comma"),
        (r"\.\s*\.",  "doubled full stop"),
        (r",,",       "doubled comma"),
        (r"\s+\?",    "space before a question mark"),
        (r"[ \t]{2,}", "doubled space"),
    ):
        if re.search(pat, body):
            problems.append(f"body has {why} — fix before sending")

    words = len(re.sub(re.escape(SIG_TAIL), "", body).split())
    if words > 190:
        problems.append(f"body is {words} words, far above the ~100-140 house length")
    return problems


def main():
    state = json.loads(STATE.read_text())
    ids = sys.argv[1:]
    if ids:
        # explicit request: lint exactly what was asked for, draft fields
        targets = [(l, "draft_subject", "draft_body") for l in state["leads"] if l["id"] in ids]
    else:
        # Sweep mode lints what could still GO OUT, not what already went.
        # For a contacted lead, draft_* is the archived record of the sent message — linting
        # it just re-reports history we cannot change. The next thing that lead sends is its
        # bump, so that is what gets checked.
        targets = []
        for l in state["leads"]:
            if l.get("stage") == "contacted" and l.get("bump_body"):
                targets.append((l, "bump_subject", "bump_body"))
            elif l.get("stage") != "contacted" and (l.get("draft_body") or l.get("draft_subject")):
                targets.append((l, "draft_subject", "draft_body"))

    failed = 0
    for l, sf, bf in targets:
        which = "bump" if sf.startswith("bump") else "draft"
        problems = lint_lead(l, sf, bf)
        if problems:
            failed += 1
            print(f"\n✗ {l['id']} ({l.get('company','?')}) [{which}]")
            for p in problems:
                print(f"    - {p}")
        else:
            print(f"✓ {l['id']} [{which}]")
    print(f"\n{len(targets)-failed}/{len(targets)} clean.")
    if not ids:
        stale = [l["id"] for l in state["leads"]
                 if l.get("stage") == "contacted" and lint_lead(l)]
        if stale:
            print(f"note: {len(stale)} contacted lead(s) hold pre-2026-07-27 copy in draft_* as the "
                  f"record of what was actually sent, not linted here: {', '.join(stale)}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
