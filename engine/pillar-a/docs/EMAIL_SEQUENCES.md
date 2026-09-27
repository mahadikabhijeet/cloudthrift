# Email Sequences — Multi-Touch Outreach

## Overview

Three-touch sequence per prospect. Stops automatically on reply.
Configure in Instantly.ai or Lemlist with these exact messages.

```
Day 1  → Cold email (initial outreach)
Day 4  → Follow-up (add proof point or data)
Day 8  → Final bump ("closing the loop")
Reply  → Sequence stops; you take over manually
```

---

## Sequence 1 — "Savings Number" (primary sequence)

**Use for:** Most cold prospects where you have an estimated AWS spend

### Day 1 — Initial outreach

**Subject:** `AWS cost question for [Company]`

> Hi [First Name],
>
> I run a read-only AWS cost audit — one CloudFormation command, 48-hour scan, then you delete the role.
>
> Ran it on a [Series B SaaS / similar profile] last month and found $[X,XXX]/month in savings: stopped instances with EBS still billing, gp2→gp3 migrations, and a Savings Plans gap covering less than 40% of their EC2 spend.
>
> Worth a 20-minute call to see if [Company] has a similar profile?
>
> [Name]

---

### Day 4 — Follow-up

**Subject:** `Re: AWS cost question for [Company]` *(reply to Day 1)*

> Hey [First Name],
>
> Following up in case this got buried — quick addition:
>
> The scan is fully passive. The role we create has zero write permissions — we can't stop, modify, or delete any resource. Your security team can review the exact policy in our open-source template before you run anything.
>
> Happy to send the one-page overview of what we check. Takes 2 minutes to read.
>
> [Name]

---

### Day 8 — Final bump

**Subject:** `Re: AWS cost question for [Company]` *(reply to Day 1)*

> Hi [First Name],
>
> Last note — don't want to keep cluttering your inbox.
>
> If AWS cost efficiency isn't a priority this quarter, totally fine. If it comes up later, feel free to reach back out.
>
> One thing I'll leave you with: the most common finding we see in accounts your size is Savings Plans coverage under 50% — that alone is typically $3k–$8k/month in preventable on-demand spend. Might be worth a quick CE check on your end.
>
> [Name]

---

## Sequence 2 — "Teaser Scan" (for when you can personalise)

**Use for:** Prospects you've researched — you know their stack or region from job posts / blog posts

### Day 1 — Initial outreach

**Subject:** `[Company] AWS footprint — 3 things I noticed`

> Hi [First Name],
>
> I noticed [Company] runs [multi-region / heavy RDS usage / something specific from their blog/job posts] — did a quick surface scan on the public footprint.
>
> Found a couple of things that often indicate larger savings underneath: what looks like gp2 storage in your primary region, and your instance types suggest you might not have Graviton or Savings Plans in place yet.
>
> Full audit is read-only, 48 hours. Happy to share the one-pager if this is on your radar.
>
> [Name]

---

### Day 4 — Follow-up

**Subject:** `Re: [Company] AWS footprint` *(reply to Day 1)*

> Hey [First Name],
>
> Quick follow-up — I put together a brief summary of what the full audit would likely surface for an account with [Company]'s profile.
>
> The three highest-probability findings for [SaaS / fintech / infra-heavy] companies at your stage:
> 1. Compute Savings Plans coverage gap (average: 34% uncovered at Series B)
> 2. Non-prod RDS running 24/7 instead of scheduled stop/start
> 3. gp2 volumes that are trivially upgradeable to gp3 (20% storage savings, zero downtime)
>
> Any of those familiar? Happy to run the real numbers on a 20-minute call.
>
> [Name]

---

### Day 8 — Final bump

**Subject:** `Re: [Company] AWS footprint` *(reply to Day 1)*

> Hi [First Name],
>
> Closing the loop here — I know you're busy.
>
> If AWS cost optimization isn't urgent right now, no worries. The audit will still be here whenever the timing is right.
>
> If it ever comes up on your end, we charge a flat $[price] for the full audit — findings in 48 hours, role deleted after. No ongoing contract.
>
> [Name]

---

## Sequence 3 — "Referral or Warm Intro" (shortened)

**Use for:** Someone referred you, or you have a mutual connection

### Day 1 — Initial outreach

**Subject:** `[Referrer Name] suggested I reach out`

> Hi [First Name],
>
> [Referrer Name] thought our work might be relevant for [Company] — they mentioned you've been looking at cloud cost efficiency.
>
> We run a read-only AWS cost audit — typically surfaces $30k–$150k/year in savings for teams your size. Fully deletable access, 48-hour turnaround.
>
> Worth a quick call this week?
>
> [Name]

---

### Day 5 — Follow-up

**Subject:** `Re: [Referrer Name] suggested I reach out` *(reply to Day 1)*

> Hi [First Name],
>
> Just following up — [Referrer Name] mentioned you're usually responsive so I wanted to make sure this didn't get lost.
>
> Happy to send the one-pager first if you'd prefer to read before chatting. Just reply "send it" and I'll attach it.
>
> [Name]

---

## Sequence Configuration (Instantly.ai / Lemlist)

```yaml
sequence_settings:
  stop_on_reply: true
  stop_on_click: false       # Don't stop just because they opened it
  timezone: prospect_local
  sending_window: "9am–5pm weekdays"
  from_name: "[Your Name]"
  from_email: "[your@email.com]"
  
  daily_sending_limit: 40    # Stay under spam filters
  randomise_send_time: true  # ±45 min from scheduled time
  track_opens: true
  track_clicks: false        # Click tracking adds tracking pixels; some prospects hate this
```

---

## Reply Handling — What to Do Next

| Reply type | Response |
|-----------|----------|
| "Interested, tell me more" | Send the one-pager PDF + book a call via Calendly |
| "Not right now" | Log in CRM as "Nurture", set reminder for 90 days |
| "How does access work?" | Send `client-security-guarantee.md` + offer a 15-min security review call |
| "What's your pricing?" | Send `PRICING.md` summary or discuss on a call (avoid email negotiation) |
| "Not interested" | Unsubscribe immediately, log as "Closed/Lost" in CRM |
| "We already use [competitor]" | Ask what they use — add to your competitor map; unsubscribe |
| No reply to all 3 | Move to "No response" in CRM; can retry in 6 months with new angle |

---

## Metrics to Track

| Metric | Benchmark (cold outreach) |
|--------|--------------------------|
| Open rate | 45–60% (good subject lines) |
| Reply rate | 5–12% (industry average: 2–4%) |
| Positive reply rate | 2–5% |
| Call booked / reply | 60–80% |
| Proposal sent / call | 40–60% |
| Closed / proposal | 30–50% |
