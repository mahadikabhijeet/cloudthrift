# Gemini Lead Discovery Prompt

Paste this into Gemini Advanced (gemini.google.com). Gemini has built-in Google Search —
it will actually look things up rather than hallucinate. Edit the [VARIABLES] before sending.

---

## Prompt (copy everything below the line)

---

You are a lead researcher for a FinOps consulting firm that helps AWS-native tech companies reduce cloud costs by 20–40%. 

**My ideal client:**
- Series A, B, or C funded SaaS/tech company
- 20–200 employees, at least 30% are engineers
- AWS-native (uses EC2, RDS, ECS/EKS, Lambda, S3 at meaningful scale)
- No dedicated FinOps team and not using tools like Spot.io, Cloudability, CloudHealth, Harness, or Apptio
- Vertical: [FILL IN: SaaS / fintech / healthtech / developer tools / e-commerce]
- Region: [FILL IN: US / Europe / India / Global]
- Funded in the last: [FILL IN: 12 months / 24 months / 36 months]

**Your task:**
Using Google Search, find [FILL IN: 15 / 25 / 50] companies that match these criteria.

For each company, search for and verify:
1. Company name + website URL
2. Funding stage (Series A/B/C) + approximate amount
3. Total employee count + rough engineering team size
4. AWS usage signals — look in: job posts (search "site:linkedin.com/jobs [company] AWS"), engineering blog, GitHub, StackShare, or Crunchbase tech stack
5. Whether they use any FinOps tools — search "[company] Spot.io OR Cloudability OR CloudHealth"
6. Best contact: CTO, VP Engineering, Head of Platform/Infrastructure (search LinkedIn)
7. One strong personalisation hook — a recent blog post, job post milestone, product launch, or funding news that I can reference in a cold email
8. Estimated AWS spend range based on: team size × $500–$2,000/engineer/month (rough)

**Search queries to use:**
- `"[vertical]" "Series B" OR "Series A" AWS SaaS 2024 site:techcrunch.com`
- `"[vertical]" startup AWS engineering infrastructure 2024`
- `site:linkedin.com/jobs "[company]" "AWS" "Platform Engineer" OR "DevOps" OR "SRE"`
- `"[company]" engineering blog AWS`
- `"[company]" FinOps OR "cloud cost" OR "AWS cost"`

**Output format — one row per company:**

| Company | Website | Funding | Employees | Engineers (est) | AWS Signals | FinOps Tool Detected | Best Contact | Title | LinkedIn URL | Personalisation Hook | Est AWS Spend/mo | ICP Score (1–12) | Notes |
|---------|---------|---------|-----------|-----------------|-------------|---------------------|--------------|-------|--------------|---------------------|------------------|-------------------|-------|

**ICP scoring (add scores up to 12):**
- AWS spend likely > $30k/mo → 4 points
- No FinOps tool detected → 3 points
- Decision-maker reachable (LinkedIn + public email pattern) → 3 points
- Series A/B/C → 2 points

**Rules:**
- Only include companies where you found actual evidence of AWS usage (job post, blog, StackShare)
- Mark "FinOps Tool Detected = unknown" if you can't find evidence either way
- Do NOT guess — if you can't find a data point, write "not found"
- For LinkedIn URLs, only include if you're confident it's the right person
- Flag any company where the LinkedIn contact looks like they already have a FinOps person

After the table, add a **Top 5 Picks** section with your recommended priority order and why.

---

## After Getting Gemini's Output

1. Copy the table into `pillar-a/outreach/leads.csv` (see `leads_template.csv` for column format)
2. Delete any row with ICP Score < 7
3. For the "unknown" FinOps tool rows — do a quick manual check before running the research script
4. Run: `python pillar-a/outreach/scripts/batch_pipeline.py --input leads.csv --output output/`

---

## Alternative: Gemini for Single Company Deep-Dive

If you already know the company but want Gemini to research it before running the script:

---

You are researching a company for a FinOps cold outreach. Use Google Search to find everything you can.

**Company:** [COMPANY NAME]
**Website:** [URL if known]

Find and report:
1. What the company does (one sentence)
2. Funding: stage, amount, date, investors
3. Headcount: total + engineering estimate
4. AWS usage evidence: job posts, blog posts, tech blog, StackShare, GitHub
5. Estimated monthly AWS spend range
6. Whether they use Cloudability, Spot.io, CloudHealth, Harness, or Apptio
7. Best contact for FinOps outreach (CTO, VP Eng, Head of Infra) — name, title, LinkedIn URL, email if findable
8. 3 specific facts I could reference in a cold email (recent blog post, job post, product launch, quote from a talk)
9. ICP score out of 12 (use the scoring above)
10. Recommended: yes/no to pursue

Be specific about your sources. Mark anything you couldn't verify.
