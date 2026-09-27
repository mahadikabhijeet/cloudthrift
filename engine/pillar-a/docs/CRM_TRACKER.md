# CRM Pipeline Tracker

## Stages

```
Cold → Contacted → Replied → Call Booked → Call Done → Proposal Sent → Onboarded → Delivered → Closed Won
                                                                                                ↓
                                                                                           Closed Lost
```

| Stage | What it means | SLA |
|-------|---------------|-----|
| **Cold** | On your list, not yet contacted | — |
| **Contacted** | Day 1 email sent | — |
| **Replied** | Any reply (positive, question, or "not now") | — |
| **Call Booked** | Call scheduled | Confirm 24h before |
| **Call Done** | Discovery call completed | Send follow-up same day |
| **Proposal Sent** | Written proposal or pricing sent | Follow up in 3 days |
| **Onboarded** | `CLIENT_ONBOARDING.md` sent; waiting for Role ARN | Follow up in 2 days |
| **Audit Running** | Role ARN received; audit in progress | — |
| **Delivered** | Report + dashboard sent | Schedule walkthrough call |
| **Closed Won** | Invoice paid, engagement complete | Ask for testimonial |
| **Closed Lost** | Decided not to proceed | Log reason |
| **Nurture** | Not now — revisit in 90 days | Set reminder |

---

## Notion Table Template

Set up a Notion database with these properties:

| Column | Type | Notes |
|--------|------|-------|
| Company | Title | Company name |
| Contact | Text | Full name + title |
| Email | Email | Primary contact email |
| LinkedIn | URL | Profile link |
| Est. AWS Spend | Number | Monthly $, estimate |
| Stage | Select | Pipeline stage (above) |
| Source | Select | Cold/LinkedIn/Referral/Inbound |
| Priority | Select | High / Medium / Low |
| Next Action | Text | Exactly what to do next |
| Next Action Date | Date | When to take the action |
| Pricing Model | Select | Fixed/% of savings/Retainer |
| Price Quoted | Number | $ amount |
| Savings Found | Number | $ savings identified (post-audit) |
| Fee Earned | Number | $ invoiced |
| Notes | Text | Call notes, key context |
| Last Updated | Last edited time | Auto |

---

## Notion Views to Create

### 1 — Active Pipeline (Kanban)
- **View type:** Board
- **Group by:** Stage
- **Filter:** Stage is not "Closed Won", "Closed Lost", "Cold"
- **Sort:** Next Action Date (ascending)
- **Use for:** Daily stand-up, what needs attention today

### 2 — My Queue (Table)
- **View type:** Table
- **Filter:** Next Action Date is on or before [today + 2 days] AND Stage not in [Closed, Nurture]
- **Sort:** Next Action Date (ascending)
- **Use for:** Daily task list

### 3 — Metrics (Gallery or Table)
- **View type:** Table
- **Filter:** Stage in [Closed Won, Delivered]
- **Properties shown:** Company, Savings Found, Fee Earned, Stage, Pricing Model
- **Use for:** Revenue tracking

### 4 — Full Pipeline (Table)
- **View type:** Table
- **No filter**
- **Sort:** Last Updated (descending)
- **Use for:** Full account list, searching

---

## Tracking Formula — Conversion Rates

Track these monthly:

```
Contacted → Replied:          (# Replied / # Contacted) × 100  target: > 8%
Replied → Call Booked:        (# Call Booked / # Replied) × 100  target: > 50%
Call Done → Proposal Sent:    (# Proposal Sent / # Call Done) × 100  target: > 60%
Proposal → Closed Won:        (# Closed Won / # Proposal Sent) × 100  target: > 40%
End-to-end (Cold → Won):      (# Closed Won / # Contacted) × 100  typical: 2–5%
```

---

## Weekly Review Checklist

Every Monday (15 min):

- [ ] Move all stale items to correct stage
- [ ] Any call done last week → was proposal sent? If not, send it
- [ ] Any proposal sent > 5 days ago with no reply → follow up
- [ ] Any onboarded accounts not started → nudge for Role ARN
- [ ] Any Nurture items due this week → restart outreach
- [ ] Check metrics: reply rate, call booked rate, won rate this month
- [ ] Add 10–20 new Cold prospects to keep top of funnel full

---

## Quick HubSpot Free Tier Setup (alternative to Notion)

If you prefer HubSpot (free for 2 users, unlimited contacts):

1. Create a **Pipeline** named "FinOps Audit"
2. Add these **Deal Stages** with win probability:
   - Replied (10%)
   - Call Booked (25%)
   - Call Done (40%)
   - Proposal Sent (60%)
   - Onboarded (80%)
   - Delivered (90%)
3. Create a **Contact** for each prospect, associated with a **Company**
4. Create a **Deal** per engagement, linked to the contact
5. Set **Close Date** = 30 days from proposal sent (nudges you to follow up)
6. Use **Tasks** for Next Action reminders
