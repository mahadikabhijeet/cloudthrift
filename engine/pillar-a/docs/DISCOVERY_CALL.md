# Discovery Call Guide — 30-Minute Script

## Before the Call

- [ ] Look up the prospect on LinkedIn — role, tenure, background
- [ ] Check Crunchbase — funding stage, investors, recent rounds
- [ ] Look at their job posts — what infrastructure roles are they hiring?
- [ ] Scan their engineering blog or GitHub — what services do they use?
- [ ] Have the one-pager PDF open, ready to screen-share
- [ ] Have the dashboard demo ready (`python -m uvicorn app.main:app --port 8000`)
- [ ] Know your pricing model for this account size

---

## Call Structure (30 min)

```
0:00–2:00   Opening & agenda
2:00–15:00  Discovery questions
15:00–23:00 Platform walkthrough / value demonstration
23:00–28:00 Pricing, objections, next steps
28:00–30:00 Confirm action items
```

---

## Opening (0–2 min)

> "Thanks for making time — I'll keep this tight, 30 minutes.
> Quick agenda: I'll ask you a few questions about your AWS setup, show you what the audit covers and what a real output looks like, and then we'll talk about whether it makes sense for [Company]. Sound good?"

*Goal: Set expectations. They agreed to 30 minutes — respect that.*

---

## Discovery Questions (2–15 min)

Ask these in a conversational way. Don't use all of them — pick 4–5 based on flow.

### AWS Spend & Scale
- "Roughly how much is [Company] spending on AWS per month — ballpark is fine?"
- "How many AWS accounts are you running — single payer, or multiple accounts in an Org?"
- "Which regions are you in? Just one or spread across the globe?"

### Team & Process
- "Who owns cloud cost on your team today — is it a specific role, or is it spread across engineering?"
- "Do you have anything in place for cost visibility — Cost Explorer, Budgets alerts, anything like that?"
- "Has cloud cost come up in board conversations or planning cycles?"

### Pain Points
- "What's your biggest infrastructure cost headache right now?"
- "Have you ever done a cost optimization pass internally? What happened?"
- "Is there a specific area — compute, database, networking — where you feel the bill is higher than it should be?"

### Timeline & Motivation
- "Is there a specific reason this came up now — budget cycle, board review, something else?"
- "How quickly would you want to act on the findings if the audit surfaced meaningful savings?"

### Decision Making
- "Is there anyone else who'd be involved in approving a small consulting engagement?"

---

## Platform Walkthrough (15–23 min)

Show, don't tell. 8 minutes max.

**Sequence:**
1. **The audit scope** (1 min) — Share screen, show the one-pager PDF. "These are the 20+ checks we run across 5 categories and 18 regions."

2. **A real dashboard** (3 min) — Open the demo dashboard. "This is what the output looks like. Every finding is here, filterable by severity, category, or region. Click any finding to expand the recommendation."
   - Click a Critical finding
   - Show the description, recommendation, and metadata
   - Click the severity card to filter

3. **The PDF report** (1 min) — "The same data is in a PDF — page 1 is the executive summary with headline savings and top 3 findings; the rest is the full findings table. This is what you'd share with your CFO or board."

4. **The access model** (2 min) — "Here's how the access works. You run this one CloudFormation command. It creates a read-only role — here's the exact policy. No write permissions. You delete the role when we're done." *(Show `client-security-guarantee.md` briefly)*

5. **Timeline** (30 sec) — "Once you run the command and send us the Role ARN, we start immediately. Full report within 48 hours."

---

## Pricing & Next Steps (23–28 min)

**Introduce pricing:**
> "For an account your size — roughly $[X]k/month — I'd normally structure this as [Fixed fee of $X / 20% of savings found with a $500 minimum]. Which model makes more sense for how your team thinks about consulting spend?"

**If they say fixed fee:**
> "Great. That's $[X]. Once you confirm, I'll send the onboarding instructions — it's one CloudFormation command on your side, takes 5 minutes. We start the audit within 24 hours of getting access."

**If they say % of savings:**
> "Perfect. The findings are fully documented — each one has the methodology and the exact number. You'll see exactly how we calculated it. And if we find less than $2,500/month, you only pay our $500 minimum."

**Common objections (handle briefly, don't over-explain):**

| Objection | Quick response |
|-----------|---------------|
| "Need to check with my CTO/CFO" | "Of course — want me to send a short email you can forward? Makes it easy to share context." |
| "Our security team needs to review the role" | "Smart. The CloudFormation template is open-source — here's the link. I can also join a 15-min call with your security team if that helps." |
| "Can we start next month?" | "Absolutely — I'll send you the instructions and you can kick it off whenever. No rush." |
| "This seems like something we could do ourselves" | "You could — the checks are based on standard AWS APIs. The question is time: our scan covers 18 regions and 20+ check types automatically. How long would your team spend to do that manually?" |

---

## Confirm Action Items (28–30 min)

> "To recap — I'll send you [the one-pager / a proposal / the security doc] today. On your side, [the CFO needs to sign off / your security team reviews the template / you just need to run the CloudFormation command]. Does that sound right?"

*Always end with a clear next action on their side and a date.*

---

## After the Call — Within 2 Hours

- [ ] Send the agreed follow-up (one-pager, proposal, or both)
- [ ] Log call notes in CRM — stage, key pain points, objections, next action
- [ ] If they said "yes": send `CLIENT_ONBOARDING.md` instructions
- [ ] If they said "maybe": set a 5-day follow-up reminder
- [ ] If they said "no": log as Closed/Lost with reason

---

## Call Notes Template

```
Date:
Company:
Contact (Name / Title):
AWS Spend (est.):
AWS Accounts (#):
Regions:
Current FinOps tools:
Key pain points:
Decision process:
Timeline:
Pricing model discussed:
Outcome:  [ ] Yes — onboarding  [ ] Maybe — follow up  [ ] No
Next action + date:
Notes:
```
