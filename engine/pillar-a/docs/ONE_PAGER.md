# FinOps Cloud Cost Audit
## Stop Overpaying for AWS — Find Your Savings in 48 Hours

*This is the source content for the one-pager PDF. Generate the PDF with:*
*`python pillar-a/scripts/generate_one_pager_pdf.py`*

---

### The Problem

Most engineering teams overpay for AWS by 20–40% — not because they're careless, but because cost optimization is time-consuming, AWS pricing is complex, and engineers are focused on shipping product.

We built a fully automated read-only audit that surfaces your savings in 48 hours.

---

### What We Check (20+ automated checks, 18 AWS regions)

**Infrastructure Hygiene**
- Unattached EBS volumes (zombie resources billing you every month)
- Orphaned snapshots older than 90 days
- Unassociated Elastic IPs ($3.65/mo each, adds up fast)
- gp2 volumes ready for gp3 migration (20% cheaper, zero downtime)
- Load balancers with no healthy targets ($16/mo each)

**Compute Strategy**
- Idle EC2 instances (< 5% CPU over 14 days — CloudWatch verified)
- Stopped instances with EBS still billing
- x86 instances ready for Graviton migration (20% better price/perf)
- Auto Scaling Groups that should run on Spot (60–80% savings)

**Database Tuning**
- Non-prod RDS running 24/7 — weekend stop/start saves $50–$400/mo each
- Idle RDS instances (< 1 connection over 14 days)
- Single-AZ production databases (reliability risk + cost optimisation)

**Network & Storage**
- NAT Gateway data-processing charges (VPC Endpoints cut this 40%)
- Inter-AZ traffic patterns worth architectural review
- S3 buckets without lifecycle/tiering policies

**Savings Plans & Reserved Instances**
- Savings Plans coverage gaps for EC2, Lambda, and Fargate
- Reserved Instance gaps for RDS, ElastiCache, Redshift, OpenSearch
- DynamoDB reserved capacity opportunity
- EC2 rightsizing recommendations from Cost Explorer

---

### Sample Findings (representative account, Series B SaaS, $55k/mo AWS spend)

| Finding | Est. Savings/mo |
|---------|----------------|
| Compute Savings Plans coverage only 31% | $4,200 |
| 3 non-prod RDS instances running 24/7 | $1,240 |
| 12 gp2 volumes → gp3 migration | $890 |
| NAT Gateway data-processing charges | $780 |
| 23 orphaned EBS snapshots | $340 |
| 2 unattached EBS volumes | $220 |
| **Total identified** | **$7,670/mo ($92,040/yr)** |

---

### What You Get

✅ **Interactive Dashboard** — every finding, filterable by severity, service, and region

✅ **PDF Report** — executive summary + full findings table (ready for CFO/board)

✅ **Priority-Ordered Recommendations** — each finding includes the exact CLI command or console steps to fix it

✅ **30-Minute Walkthrough Call** — we present findings and help prioritise

---

### How It Works

```
1. You run ONE command          (~5 minutes, CloudFormation)
2. We run the full audit        (~48 hours)
3. You receive the report       (PDF + interactive dashboard)
4. You delete the role          (one command — access removed permanently)
```

**No data leaves your AWS account. No write permissions. Fully open-source.**

---

### Security

The role we create can only READ resource metadata and billing figures.
It cannot start, stop, modify, or delete anything.
Your security team can review the exact permissions at:
`github.com/[your-repo]/pillar-a/cloudformation/client-iam-role.yaml`

---

### Pricing

| Option | Price |
|--------|-------|
| Fixed fee (small: < $20k/mo AWS) | $500 |
| Fixed fee (medium: $20k–$80k/mo) | $1,000 |
| Fixed fee (large: $80k–$200k/mo) | $2,000 |
| % of savings found (min $500) | 20% |

---

*Ready to see what's in your account?*
*[YOUR_EMAIL] · [YOUR_CALENDLY_LINK]*
