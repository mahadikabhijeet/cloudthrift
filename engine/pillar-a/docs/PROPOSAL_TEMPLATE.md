# Proposal Template

*Copy this, fill in the [PLACEHOLDERS], and send as a clean PDF or email body.*
*Keep it to 1 page. Long proposals lose deals.*

---

## FinOps Cloud Cost Audit — Proposal for [CLIENT_COMPANY]

**Prepared for:** [CONTACT_NAME], [CONTACT_TITLE]
**Date:** [DATE]
**Valid for:** 30 days

---

### What We'll Do

A full read-only cost audit of [CLIENT_COMPANY]'s AWS environment — covering compute, database, network, storage, and Savings Plans/Reserved Instance coverage across all enabled regions.

Based on our conversation, [CLIENT_COMPANY] is running approximately $[AWS_SPEND]/month on AWS with [NUMBER_OF_ENGINEERS] engineers. At that scale, our audits typically surface $[LOW_ESTIMATE]–$[HIGH_ESTIMATE]/month in addressable savings opportunities.

---

### What You Get

| Deliverable | Detail |
|-------------|--------|
| Interactive Dashboard | Every finding — filterable by severity, service, region |
| PDF Report | Executive summary + full findings table (board-ready) |
| Priority Recommendations | Top 5 findings flagged for immediate action |
| Per-Finding Fix Instructions | Exact CLI command or console steps for each issue |
| 30-min Walkthrough Call | We present findings, answer questions, prioritise |

---

### Engagement Scope

**Checks included:**
- Infrastructure hygiene: unattached EBS, gp2→gp3 migrations, orphaned snapshots, idle Elastic IPs, load balancers with no healthy targets
- Compute strategy: idle EC2 (14-day CloudWatch), stopped instances, Graviton migration opportunities, Spot Fleet candidates
- Database tuning: non-prod RDS stop/start automation, idle RDS, single-AZ production gaps
- Network & storage: NAT Gateway charges, inter-AZ traffic, S3 lifecycle gaps
- Savings Plans & RIs: EC2/Lambda/Fargate SP coverage, RDS/ElastiCache/Redshift/OpenSearch RI coverage, DynamoDB reserved capacity, EC2 rightsizing recommendations

**Regions:** All enabled AWS regions (or [SPECIFIC_REGION_LIST] if preferred)
**Accounts:** [ACCOUNT_IDS_OR_"Single account"]

---

### What [CLIENT_COMPANY] Needs to Do

One CloudFormation command (~5 minutes):

```bash
aws cloudformation deploy \
  --template-file client-iam-role.yaml \
  --stack-name finops-audit-role \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    CentralAccountId=[OUR_ACCOUNT_ID] \
    ExternalId=[YOUR_EXTERNAL_ID] \
    RoleName=FinOps-Audit-ReadOnly-Role
```

Then send us the Role ARN output. That's it.

The role is read-only with zero write permissions. Your security team can review the open-source template at: `[GITHUB_LINK]`

---

### Investment

**[CHOOSE ONE OF:]**

> **Option A — Fixed Fee**
> $[FIXED_FEE] for the complete audit, report, and walkthrough call.
> Payment due on delivery of the report.

> **Option B — Percentage of Savings Found**
> 20% of estimated monthly savings identified, minimum $500.
> Invoiced after report delivery. Savings methodology fully documented.
> Example: if we find $15,000/month in savings, the fee is $3,000.

> **Option C — Ongoing Monitoring Retainer**
> $[RETAINER_AMOUNT]/month for [quarterly / monthly] re-audits, dashboard access, and monthly review calls.
> Cancel anytime.

---

### Timeline

| Step | Owner | When |
|------|-------|------|
| Run CloudFormation + send Role ARN | [CLIENT_COMPANY] | Day 0 |
| Audit runs | Us | Day 0–2 |
| Report delivered | Us | Day 2 |
| Walkthrough call | Both | Day 3–5 |
| Role deletion (optional) | [CLIENT_COMPANY] | After call |

---

### Security & Access

- **Read-only** — We can see resource metadata and billing figures. We cannot start, stop, modify, or delete any resource.
- **ExternalId protected** — Your role can only be assumed with our unique shared secret. Nobody else can use it.
- **Fully deletable** — One command removes all access: `aws cloudformation delete-stack --stack-name finops-audit-role`
- **Open source** — Every line of our setup is open-source. Your security team can audit it before running anything.

---

### Next Steps

1. Review this proposal and let me know if you'd like to adjust scope or pricing
2. If ready to proceed: run the CloudFormation command above and reply with the Role ARN
3. We'll confirm receipt and start the audit within 24 hours

Questions? Reply to this email or book a follow-up at [CALENDLY_LINK].

---

*[YOUR_NAME]*
*[YOUR_EMAIL]*
*[YOUR_LINKEDIN]*
