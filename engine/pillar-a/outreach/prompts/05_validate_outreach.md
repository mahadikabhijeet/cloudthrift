# Prompt — Pre-Send Outreach Validator

Use this in Claude.ai or Gemini web before sending any AI-generated email.
Paste the prompt below followed by the email you want to validate.

---

## Validation Prompt

You are a senior B2B sales coach reviewing a cold outreach email before it gets sent. 
Your job is to catch anything that would make a CTO or VP Engineering delete or mark it as spam.

Review the email against these criteria and give a PASS / FIX / FAIL rating for each:

**1. Length** — Under 100 words? (count them)
   PASS = under 100 | FIX = 100-130 | FAIL = over 130

**2. Opening line** — Does it reference something specific and real about the company?
   PASS = specific, verifiable fact | FIX = generic but OK | FAIL = "Hope this finds you well" or generic opener

**3. Personalization accuracy** — Is the specific claim in the email something that can be verified?
   PASS = verifiable (blog post title, funding round, specific job post) | FIX = plausible but vague | FAIL = could be invented

**4. Value proposition** — Is there one clear savings number or opportunity?
   PASS = one specific range | FIX = vague benefit | FAIL = no value prop or too many claims

**5. CTA** — Is there exactly one call to action, and is it low-commitment?
   PASS = one CTA, "worth a call?" style | FIX = two CTAs | FAIL = aggressive ask or no CTA

**6. Spam signals** — Scan for: "free", "guaranteed", "act now", "limited time", "solution", "revolutionize", "synergy", excessive exclamation marks, ALL CAPS
   PASS = none found | FAIL = any found

**7. Human-ness** — Read it as if you received it. Does it sound like a real person wrote it?
   PASS = sounds human | FIX = slightly formal/robotic | FAIL = clearly AI-generated or corporate tone

**8. Factual risk** — Does anything in the email sound like it might be hallucinated or unverifiable?
   PASS = everything can be verified | FIX = one thing to double-check | FAIL = claims that could be wrong

**Output format:**
```
OVERALL: [SEND / REVISE / DO NOT SEND]

| Check | Rating | Notes |
|-------|--------|-------|
| Length | PASS/FIX/FAIL | [word count] |
| Opening | PASS/FIX/FAIL | [comment] |
| Personalisation | PASS/FIX/FAIL | [comment] |
| Value prop | PASS/FIX/FAIL | [comment] |
| CTA | PASS/FIX/FAIL | [comment] |
| Spam signals | PASS/FIX/FAIL | [comment] |
| Human-ness | PASS/FIX/FAIL | [comment] |
| Factual risk | PASS/FIX/FAIL | [comment] |

REVISED EMAIL (if REVISE):
[paste the corrected version here]

NOTES FOR SENDER:
[1-3 bullet points on what to verify before sending]
```

---

**Email to review:**
[PASTE YOUR EMAIL HERE]

---

## Quick Human-Check Rules (without AI)

Run these yourself in 60 seconds before sending:

- [ ] Is the first sentence true? (Did they actually write that blog post? Is that real?)
- [ ] Does the email name a real person at the right title?
- [ ] Is the savings range realistic? (Not "$500k/month" for a 30-person startup)
- [ ] Could you send this to your own CTO and not feel embarrassed?
- [ ] Is the email address guessed or verified? (Never send to a guessed email without checking)
- [ ] Have you googled the contact name + company to confirm they still work there?
