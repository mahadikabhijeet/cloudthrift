# Outreach Templates — FinOps Cold Outreach

## Before You Send: Personalisation Checklist

- [ ] Replace every `[PLACEHOLDER]` with real values
- [ ] Look up their AWS usage on StackShare, their job posts, or blog posts
- [ ] Find their actual name (no "Hi there")
- [ ] Write the first sentence yourself — never copy-paste the opening line
- [ ] Check: do they already use Spot.io, Cloudability, or Harness? (skip if yes)

---

## Cold Email — Template A (Hook: savings number)

**When to use:** You have a rough sense of their AWS spend (job posts, blog posts, Crunchbase).

**Subject lines (A/B test these):**
- `Quick AWS cost question for [Company]`
- `Found $[X]k/mo in savings at a similar [industry] company`
- `[Company]'s AWS bill — 5-min question`

---

> Hi [First Name],
>
> I run a read-only AWS cost audit tool — no agents, no write access, nothing deployed. One CloudFormation command and a 48-hour scan.
>
> We ran it on a [Series B / similar-stage] [SaaS / fintech / etc.] company last month and found $[X,XXX]/month in savings they didn't know about — mostly stopped instances with attached EBS, gp2→gp3 migrations, and a Savings Plans gap.
>
> Would it be worth a 20-minute call to see if your account has the same profile?
>
> [Your name]

---

## Cold Email — Template B (Hook: teaser scan)

**When to use:** You have their company name and can run a teaser scan on their public footprint (or a similar-profile account).

**Subject lines:**
- `Quick scan of [Company]'s AWS footprint`
- `3-minute AWS scan — found a few things`
- `[Company] — potential $[X]k AWS savings`

---

> Hi [First Name],
>
> I ran a quick 3-minute scan on [Company's] public AWS resource footprint — the kind of check that doesn't require any access, just public metadata.
>
> Spotted [N] things worth looking at: [1 specific finding, e.g., "a few gp2 volumes that look like gp3 migration candidates"] and what looks like a Savings Plans gap based on your region profile.
>
> Full audit (read-only, 48 hours, then you delete the role) would give the complete picture. Happy to walk you through what we'd find on a 20-minute call.
>
> [Your name]

---

## Cold Email — Template C (Hook: specific pain point)

**When to use:** You've seen their job posts, blog posts, or talks that hint at cost pressure.

**Subject lines:**
- `Re: [their blog post title / conference talk]`
- `Cost efficiency at [Company] — quick question`

---

> Hi [First Name],
>
> Saw your [post/talk] on [topic] — resonated, especially the part about [specific detail].
>
> We built a read-only AWS cost audit that typically surfaces $30k–$150k/year in savings for [Series B / similar-stage] companies. The whole setup is one CloudFormation command; the role gets deleted when we're done.
>
> Would a 20-minute call be useful before your next [board review / Q3 planning / budget cycle]?
>
> [Your name]

---

## LinkedIn Connection Request (300 character limit)

> Hi [First Name] — I build FinOps tooling for AWS-native SaaS companies. Ran a cost audit on a [similar company] last month and found $[X]k/mo in savings. Thought it might be relevant for [Company]. Happy to connect.

---

## LinkedIn Follow-Up DM (after connection accepted, Day 2–3)

> Thanks for connecting! The audit I mentioned is a read-only scan — one CloudFormation command, 48 hours, then you delete the role. We audited [company type] recently and found savings across stopped instances, Savings Plans gaps, and gp2→gp3 migrations. Want me to send the one-pager?

---

## Follow-Up DM (if no reply after 5 days)

> Hey [First Name] — just following up in case this got buried. Happy to send the 1-page overview of what the audit covers. No commitment needed — just curious if AWS costs are on your radar for [Q3 / this quarter / upcoming board review].

---

## Subject Line Variations (for A/B testing)

```
Savings angle:
  "Found $X/mo at a company like [theirs]"
  "AWS cost audit — [Company]"
  "Quick question about [Company]'s AWS spend"

Curiosity angle:
  "3 AWS findings from a quick scan"
  "Something I noticed about [Company]'s infrastructure"
  "Fast question about [Company]'s cloud setup"

Relevance angle:
  "Re: [their blog post / job post / talk]"
  "[Company] + AWS cost optimization"
  "Platform engineering at [Company]"
```

---

## What NOT to Do

- Long emails (>5 sentences in the first message)
- Listing all features in the first email
- "I hope this email finds you well"
- "My company offers..."
- Sending the same email to CTO and VP Eng at the same company (they'll talk)
- Following up more than 3 times on a cold thread

---

## Tracking What Works

After 20+ sends, track:
- Open rate by subject line (use Instantly.ai or Lemlist)
- Reply rate by template variant
- Booked call rate by industry vertical
- Savings number that generates the most curiosity (test $X,XXX vs $XX,XXX)
