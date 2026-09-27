# Outreach Workflow — Using Claude Project (No API Credits)

Your Claude Pro subscription ($20/mo) covers everything below.
No separate Anthropic API credits needed.

The API-based `research_lead.py` script is kept for when you want to automate
at scale (50+ companies/batch). Until then, use this workflow.

---

## One-Time Setup (do this once in your Claude Project)

Your Claude Project needs 3 documents uploaded as knowledge files.
If you haven't uploaded them yet:

1. Open **claude.ai → Projects → FinOps Platform**
2. Click **+ Add content** for each of the following files:
   - `pillar-a/outreach/prompts/01_research_company.md` → paste as "Research prompt"
   - `pillar-a/outreach/prompts/04_generate_email.md` → paste as "Email generation prompt"
   - `pillar-a/outreach/prompts/05_validate_outreach.md` → paste as "Validation checklist"
   - `pillar-a/docs/ICP.md` → paste as "ICP scoring"

Claude will follow these automatically in every chat in the Project.

---

## Daily Workflow — One Company End to End (~20 min)

### Step 1 — Collect raw data (terminal, ~3 min)

```bash
cd ~/Documents/Projects/finops-platform

python3 pillar-a/outreach/scripts/collect_raw.py "RemotePass" \
    --url https://remotepass.com \
    --notes "Raised Series B $17.4M on May 22 2026 — 2 days ago. CEO Kamal Reggad. Profitable." \
    --output pillar-a/outreach/output/
```

This runs 5 DuckDuckGo searches + scrapes their website.
No Claude API. Takes about 60 seconds.

Output: `pillar-a/outreach/output/remotepass_raw.txt`

---

### Step 2 — Research in Claude Project (~5 min)

1. Open your terminal, print the raw file:
   ```bash
   cat pillar-a/outreach/output/remotepass_raw.txt
   ```

2. Select all → copy

3. Open **Claude Project → FinOps Platform** → new chat

4. Paste and send. Claude will respond with a JSON object:
   ```json
   {
     "company": "RemotePass",
     "qualify": "yes",
     "icp_score": 11,
     "aws_spend_estimate": "$30k-50k/mo",
     "funding": {"stage": "Series B", "amount": "$17.4M", "date": "May 2026"},
     "contacts": [...],
     "aws_signals": [...],
     "finops_tool": "none detected",
     "personalization_hooks": [...],
     "recommendation": "..."
   }
   ```

5. Copy the entire JSON response.

6. Save it locally (optional but useful):
   ```bash
   # Paste the JSON into a new file for your records
   nano pillar-a/outreach/output/remotepass_research.json
   ```

---

### Step 3 — Generate emails in the same Claude Project chat (~5 min)

Still in the same chat, send this follow-up message:

```
Now generate 3 personalised email variants for this company.
Use the research above. Follow the email generation instructions in your knowledge base.
```

Claude will produce 3 variants, each:
- Under 100 words
- With a specific personalised hook (not generic)
- Plain text, no HTML
- One clear CTA

---

### Step 4 — Validate before sending (~3 min)

In the same chat, send:

```
Now validate Variant [X] using the 8-criterion validation checklist in your knowledge base.
Give me a SEND / REVISE / DO NOT SEND verdict with specific notes on each criterion.
```

If it comes back REVISE, ask: `Revise it based on your notes and show me the updated version.`
If it comes back DO NOT SEND, ask for a full rewrite from scratch.

---

### Step 5 — Send (~2 min)

Copy the approved email variant → Gmail → send.

Log it in your CRM tracker (`pillar-a/docs/CRM_TRACKER.md`).

---

## Priority Queue — Work Through in This Order

| # | Company | Contact | Why First | Notes |
|---|---------|---------|-----------|-------|
| 🔥 | RemotePass | Kamal Reggad (CEO) | Series B 2 days ago | Best timing window |
| 1 | Medallion | Derek Lo (CEO) | 12/12, $60-120k/mo, HIPAA | Inc. 5000 hook |
| 2 | Secureframe | Shrav Mehta (CEO) | Irony hook | "You audit compliance…" |
| 3 | Hightouch | Kashish Gupta (CTO) | AI pivot = new spend | Data egress angle |
| 4 | Ashby | Abhik Pramanik (VP Eng) | Revenue 6x'd | Board efficiency pressure |
| 5 | Clumio | Poojan Kumar (CEO) | AWS blog + irony hook | Backup co on AWS |

**After those 6** (need LinkedIn contact search first):
- Taktile (Berlin) — VP Eng, Lambda/DynamoDB job post
- PhotoRoom (Paris) — Head of ML Infra, GPU compute
- Weaviate (Amsterdam) — VP Cloud Eng, vector DB managed service

---

## Cheat Sheet — Commands

```bash
# Research a company
python3 pillar-a/outreach/scripts/collect_raw.py "Company Name" \
    --url https://company.com \
    --notes "any extra context you know" \
    --output pillar-a/outreach/output/

# Print raw data to paste into Claude Project
cat pillar-a/outreach/output/company-name_raw.txt

# List what you've collected so far
ls -la pillar-a/outreach/output/
```

---

## When to Switch to the API Script

Use `research_lead.py` (the automated script with API credits) when:
- You want to process 10+ companies overnight without opening a browser
- You're running the batch pipeline (`batch_pipeline.py`)
- You cancel your Claude.ai subscription and move to API-only

Until then, this workflow is free, faster to iterate on, and gives you more control.

---

## Troubleshooting

**`ddgs` not found:**
```bash
pip install ddgs
```

**DuckDuckGo returns empty results:**
Rate-limited. Wait 60 seconds and try again. Or run with `--url` only (skips searches):
```bash
python3 collect_raw.py "Company" --url https://company.com
```

**Website scrape fails (paywall, cloudflare, etc.):**
The script notes `[scrape failed: ...]` and continues. The search results alone are usually enough for Claude to work with. Supplement manually by copying 1-2 paragraphs from their About page into the `--notes` field.
