# Pricing Model — FinOps Cloud Cost Audit

## The Three Models

### Option A — Fixed Fee Per Audit

| Account size (est. AWS spend) | Price |
|------------------------------|-------|
| Small (< $20k/mo) | $500 |
| Medium ($20k–$80k/mo) | $1,000 |
| Large ($80k–$200k/mo) | $2,000 |
| Enterprise (> $200k/mo) | Custom |

**Pros:** Simple to close. No disputes. Client knows exactly what they're paying.
**Cons:** No upside if you find $200k/year in savings for a small fee.
**When to use:** First 5–10 clients. Getting to testimonials fast. Client is budget-sensitive.

---

### Option B — Percentage of First-Month Savings Found

> **Fee = 20% of the estimated monthly savings identified**
>
> Example: Audit finds $15,000/month in savings → Fee = $3,000

**Minimum fee:** $500 (protects you if the account is already well-optimized)
**Maximum fee cap:** $5,000 (optional — use to close risk-averse clients)
**Savings definition:** Estimated monthly savings as reported in the audit output (documented, transparent)

**Pros:** Aligns incentives. Easier to sell — client only pays if you find something.
**Cons:** Client may dispute estimated savings numbers. Longer sales conversation. Bad if you find little.
**When to use:** Confident in the account having savings. Client is value-conscious, not budget-constrained.

**How to present:**
> "If we find nothing meaningful, you pay nothing beyond our minimum. If we find $30k/month, you pay $6,000 for a $360,000/year opportunity. Most clients see this as a no-brainer."

---

### Option C — Monthly Retainer (Ongoing Monitoring)

| Plan | Price | Cadence | Includes |
|------|-------|---------|----------|
| Starter | $200/mo | Quarterly audit | Dashboard access, email alerts |
| Growth | $400/mo | Monthly audit | Above + 30-min monthly review call |
| Scale | $800/mo | Weekly scan (teaser) + monthly full | Above + Slack integration, priority support |

**Pros:** Recurring revenue. Catches new issues as infrastructure grows. Clients love ongoing visibility.
**Cons:** Harder first sale. Need to deliver ongoing value.
**When to use:** After initial one-time audit. Client has fast-growing infrastructure. Client wants ongoing monitoring.

**Upsell path:**
```
One-time audit ($1,000) → "Want us to re-run this quarterly?" → Starter retainer ($200/mo)
```

---

## Recommended Starting Model

**Start with Option A (fixed fee).** Reasons:
1. Easiest to close — no "how do you define savings?" negotiation
2. Gets you to 5 paying clients fastest
3. Testimonials come quickly
4. Once you have 3+ case studies with dollar figures, shift to Option B for larger accounts

**Typical progression:**
- Clients 1–5: Fixed fee ($500–$1,000)
- Clients 6–15: Mix of fixed fee and % of savings
- Clients 15+: % of savings for new clients, retainers for existing

---

## Packaging the Deliverable

Every audit (any model) includes:

| Deliverable | What it is |
|-------------|-----------|
| Interactive Dashboard | Web-based, filterable by severity/category/region |
| PDF Report | Executive summary + full findings table |
| Priority Order | Top 5 findings flagged for immediate action |
| Recommendations | Per-finding: exact CLI/console command to fix it |
| 30-min Walkthrough Call | Video call to present findings, answer questions |
| Role Deletion Instruction | How to remove our access in one command |

---

## Objection Handling

**"$1,000 is expensive for a tool that might find nothing."**
> "Fair point. That's why many clients prefer the percentage model — you only pay 20% of what we actually find. If we find $10,000/month in savings, that's a 200× return in year one. If we find little, the fee is our minimum of $500."

**"Our engineering team can do this themselves."**
> "Absolutely — and they probably have some of the basics covered. Our audit checks 18 AWS regions, 20+ check types, CloudWatch metrics, Cost Explorer data, and Savings Plans coverage gaps. Most teams find 3–5 things on their own; we typically surface 15–30. The question is whether the delta is worth $1,000."

**"Can we pay after we verify the savings?"**
> "Yes. We can structure it as: $0 upfront + 20% of savings found, invoiced after the report. The savings estimate is fully documented in the PDF — each finding has its methodology."

**"We already use AWS Cost Explorer / Trusted Advisor."**
> "Cost Explorer shows your spend by service. Trusted Advisor catches some basics. Our audit goes deeper: per-instance CloudWatch utilization, cross-AZ traffic patterns, Savings Plans coverage by service, RDS weekend automation opportunities. Most clients who use CE still find 5–10 new things they hadn't acted on."

**"What if our security team won't approve the role?"**
> "The role is built on AWS-managed policies — your security team can read them in the AWS console or in our open-source CloudFormation template before running anything. We can also schedule a 15-minute call with your security team if that helps. The role is fully deletable after the engagement with one command."

---

## Proposal Structure

When sending a written proposal (see `PROPOSAL_TEMPLATE.md`):

1. **Summary of what we'll audit** (2 sentences)
2. **Why it's relevant for them** (1–2 specific facts about their setup)
3. **Deliverables** (bullet list)
4. **Pricing** (the option you discussed, clearly stated)
5. **Next step** (they run 1 CFN command; you start the audit within 24h)
6. **Timeline** (audit complete within 48h of access)

Keep it to 1 page. Long proposals lose deals.
