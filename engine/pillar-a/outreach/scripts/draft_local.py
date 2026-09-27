#!/usr/bin/env python3
"""
Local-first outreach drafter for CloudThrift.

Drafts first-touch cold emails on the LOCAL Ollama `sales` persona
(qwen2.5:7b-instruct) — free, private, offline. Local-first per CLAUDE.md §10:
the cloud is never called here; if the local server is down it tells you to start it.

Reads  crm/pipeline-state.json, drafts for every ON-TARGET lead that has no draft
yet (or --id / --force), tailors the guarantee to that lead's estimate, and writes
draft_subject / draft_body back. Then review on the dashboard and send.

Run:
    python3 pillar-a/outreach/scripts/draft_local.py                 # all missing
    python3 pillar-a/outreach/scripts/draft_local.py --id griffin --force
    python3 pillar-a/outreach/scripts/draft_local.py --all-on-target --force
"""
import json, os, sys, re, argparse, urllib.request, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from voice_lint import lint_lead          # preflight: see voice_lint.py header

OLLAMA = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
MODEL  = os.environ.get("LOCAL_SALES_MODEL", "qwen2.5:7b-instruct")
ROOT   = pathlib.Path(__file__).resolve().parents[3]
STATE  = ROOT / "crm" / "pipeline-state.json"

# REWRITTEN 2026-07-27. The previous version of this prompt is the direct cause of every
# defect found in the 07-25 and 07-27 drafts: it ORDERED a "wasted-%" clickbait subject,
# "Hi {first}", the "bandwidth for 2 consults" scarcity, the "within 48 hours" claim, and a
# 1-page-checklist CTA that is not the offer we actually sell. The model was obedient; the
# spec was wrong. This version encodes 01-core/writing-voice.md and the real offer, and
# every output is checked by voice_lint.py before it can be sent.
SYSTEM = """You are Abhijeet Mahadik, a Senior Staff Cloud Engineer who runs AWS FinOps
audits on the side, writing ONE short cold outreach email in his own voice. Follow this
STRUCTURE but vary the wording so no two emails read the same:

1. Subject: lowercase, casual, specific, like he typed it fast. Shape:
   "quick thought on {company}'s <what drives their bill> spend" (e.g. "quick thought on
   acme's ingest spend"). NEVER a question, NEVER a percentage, NEVER "(quick check)",
   NEVER Title Case. It must not make any claim about their actual bill.
2. "Hey {first}, hope things are good at your end." — always this opener, always "Hey".
3. One flowing paragraph: what their workload means for where AWS money goes, then a
   trailing comma-run of 2-3 workload-specific leaks drawn ONLY from the findings given,
   then a blameless closing clause ("it is rarely anyone's fault, it just accumulates
   while you ship"). Long comma-connected sentences, not short punchy marketing lines.
4. Then, close to verbatim: "I am a senior staff engineer looking after petabyte scale
   infrastructure, and I run read only AWS cost audits. Happy to do a free 30 minute scan
   and show you what is leaking. If I don't find at least {guarantee} a month, you owe me
   nothing." (NEVER name the employer.)
5. One yes/no CTA on its own line: "Worth a look?"
6. Signature block, exactly:
Abhijeet Mahadik
Senior Staff Cloud Engineer
linkedin.com/in/abhijeet-mahadik-ab326b42
mob: +91 8329560186

ABSOLUTELY FORBIDDEN, these have all reached real prospects before and must never recur:
- Inventing scarcity ("bandwidth for N consults"), turnaround times ("within 48 hours"),
  or any offer other than the free 30 minute read only scan plus the guarantee above.
- Stating or implying a percentage of THEIR bill that is wasted. You do not know it.
- Any financial figure not given to you verbatim below. Do NOT restate funding as
  valuation, do NOT convert one into the other, do NOT round or embellish. If a number
  is not in the facts, it does not go in the email.
- Em-dashes, en-dashes, exclamation marks, curly quotes, "Hi", "hope this finds you well",
  "reach out", "leverage", "streamline", "delve", "unlock", "seamless".

Real facts only, taken verbatim from the input. 100-140 words before the signature.
Output EXACTLY:
Subject: <subject line>
Body: <body including the signature block>"""

def ollama(system, prompt):
    req = urllib.request.Request(
        f"{OLLAMA}/api/generate",
        data=json.dumps({"model": MODEL, "system": system, "prompt": prompt,
                         "stream": False, "options": {"temperature": 0.7}}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())["response"]

def clean(text):
    # normalise the AI tells the model keeps emitting, so the lint fails on substance
    # rather than on punctuation it costs nothing to fix here (2026-07-28)
    text = text.replace("—", ",").replace("–", ",").replace(" - ", ", ").replace("!", ".")
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"').replace(";", ",")
    text = re.sub(r"hope this (email )?finds you well[.,]?\s*", "", text, flags=re.I)
    return text.strip()

def build_prompt(l):
    first = (l.get("contact") or "there").split()[0]
    # The TAILORED guarantee is what we actually promise. Never the flat $20k, and never
    # a "typical savings" band, which the old prompt turned into an invented claim.
    guarantee = f"{max(1, int(l.get('guarantee_usd') or 5000) // 1000)}k"
    findings = "; ".join((l.get("findings") or ["idle instances", "unattached storage"])[:3])

    # Do NOT feed `notes` to the model. It carries internal reasoning (headcount ESTIMATES,
    # CONTACT/MODEL CAVEATs, email evidence) and on 2026-07-27 the model read
    # "Series B extension, $60M (total ~$113M)" out of Zilliz's notes and wrote it back as
    # "total valuation close to $113M" — a fabricated figure, to a co-founder. Only an
    # explicit, human-written `personalization` line is ever quotable.
    personal = (l.get("personalization") or "").strip()
    facts = (f"Company: {l['company']} ({l.get('geo','')})\n"
             f"Contact first name: {first}\n"
             f"What they do: {l.get('about','')}\n"
             f"Workload-specific waste examples to draw from: {findings}\n"
             f"Guarantee figure to state: {guarantee}\n")
    facts += (f"Approved personalization detail (quote only this, nothing else): {personal}"
              if personal else
              "No approved personalization detail. Write from the workload only, and do NOT "
              "mention funding, valuation, headcount, customer counts or any other number.")
    sysf = (SYSTEM.replace("{first}", first)
                  .replace("{guarantee}", guarantee)
                  .replace("{company}", l['company']))
    return sysf, f"Write the email using ONLY these facts:\n{facts}"

def parse(out, l):
    def grab(label):
        m = re.search(label + r"\s*[:*]*\s*(.+?)(?:\n\s*\n|$)", out, re.I | re.S)
        return m.group(1).strip(" *\n") if m else ""
    subj, body = grab("subject"), grab("body")
    if not body:                                   # model skipped the Body: label
        m = re.search(r"(Hey\s+.+)", out, re.S)
        body = (m.group(1).strip() if m else out.strip())   # last resort: whole output
    if not subj:                                   # synthesize a house-style subject
        subj = f"quick thought on {l['company'].split('/')[0].strip().lower()}'s aws spend"
    return subj.splitlines()[0].strip(), clean(body)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id"); ap.add_argument("--force", action="store_true")
    ap.add_argument("--all-on-target", action="store_true")
    a = ap.parse_args()
    s = json.loads(STATE.read_text())

    # health check — fail loud, never silently fall back to cloud
    try:
        urllib.request.urlopen(f"{OLLAMA}/api/tags", timeout=5)
    except Exception:
        sys.exit(f"Local Ollama not reachable at {OLLAMA}. Start it:  ollama serve  (model: {MODEL})")

    todo = []
    for l in s["leads"]:
        if a.id and l["id"] != a.id: continue
        if not a.id and not l.get("on_target"): continue           # on-target only by default
        if l.get("draft_body") and not (a.force or a.all_on_target): continue
        todo.append(l)

    if not todo:
        print("Nothing to draft (use --force to redraft)."); return
    for l in todo:
        sysf, prompt = build_prompt(l)
        print(f"drafting {l['company']} on {MODEL} …", flush=True)
        try:
            subj, body = parse(ollama(sysf, prompt), l)
        except Exception as e:
            print(f"  ! local draft failed for {l['company']}: {e}"); continue
        if subj and body:
            l["draft_subject"], l["draft_body"] = subj, body
            problems = lint_lead(l)
            l["draft_lint_clean"] = not problems
            if problems:
                # Not a failure to hide: the draft is kept so it can be repaired, but it is
                # marked, and send_batch.py will refuse to transmit it until it lints clean.
                print(f"  ⚠ {subj}")
                print(f"    LINT FAILED ({len(problems)}), needs an Opus rewrite before sending:")
                for p in problems:
                    print(f"      - {p}")
            else:
                print(f"  ✓ {subj}")
        else:
            print(f"  ! could not parse model output for {l['company']}")
    STATE.write_text(json.dumps(s, indent=2))
    print(f"\nSaved drafts → {STATE}. Review on the dashboard before sending.")
    dirty = [l["id"] for l in todo if l.get("draft_body") and not l.get("draft_lint_clean", True)]
    if dirty:
        print(f"⚠ {len(dirty)} draft(s) failed the voice lint and are BLOCKED from sending: "
              f"{', '.join(dirty)}")

if __name__ == "__main__":
    main()
