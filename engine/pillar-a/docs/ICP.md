# Ideal Customer Profile — FinOps Cloud Cost Audit

## Best-Fit Client

| Signal | Detail |
|--------|--------|
| **Company stage** | Series A, B, or C — post product-market fit, pre-dedicated FinOps team |
| **Team size** | 20–200 engineers |
| **Cloud spend** | $10k–$200k/month on AWS (sweet spot: $30k–$80k) |
| **Infrastructure** | AWS-native — not multi-cloud, not heavily Kubernetes-only |
| **FinOps maturity** | No full-time cloud cost engineer; engineers manage infra as a side responsibility |
| **Vertical** | SaaS, developer tooling, e-commerce, fintech, healthtech, edtech |

## Green Flags (pursue actively)

- Engineering blog posts about AWS, ECS/EKS, RDS, Lambda
- Recent funding round (new budget pressure, board asking about burn)
- Job postings for SRE or Platform Engineering (but NOT for FinOps/Cloud Cost)
- GitHub repos using Terraform/CDK (sophisticated enough to act on recommendations)
- Using AWS services across multiple regions (higher savings surface)
- CTO or Head of Infrastructure is reachable on LinkedIn
- Company has cost mentions in public investor decks or interviews ("we need to get efficient")

## Yellow Flags (pursue but calibrate)

- Fewer than 5 engineers (too small — savings won't justify your time)
- AWS spend < $10k/month (smaller savings opportunity per engagement)
- Uses GCP or Azure alongside AWS (cross-cloud complexity)
- Already on AWS Enterprise Support or has AWS TAM (may have some optimization guidance already)
- Kubernetes-heavy (some of our checks are EC2/RDS-centric; findings may be fewer)

## Red Flags (skip or de-prioritize)

- Enterprise (1000+ employees) with a dedicated FinOps or Cloud Economics team
- Account is managed by an AWS reseller/MSP (they own billing, client can't act alone)
- Already subscribes to Cloudability, Apptio, Spot.io, Harness Cloud Cost, or CloudHealth
- AWS Organization payer account is under a holding company — client is a linked account only (CE API access may be blocked; findings reduced)
- Government or defense (procurement cycles too long, compliance blocks role assumption)

## Where to Find Them

### LinkedIn (Sales Navigator)

```
Industry: Computer Software, Internet, Financial Services, Health Care
Company size: 11–200, 201–500
Seniority: Director, VP, C-Level
Title keywords: CTO, VP Engineering, Head of Infrastructure, Platform Lead, DevOps Lead
Tech stack filter: Amazon Web Services (via Dux-Soup or Clay enrichment)
```

### Apollo.io

```
Title: CTO OR "VP Engineering" OR "Head of Infrastructure" OR "Platform Engineering"
Employee count: 20–500
Technology: AWS
Funding: Series A, Series B, Series C
Keywords (company): cloud, SaaS, infrastructure
Exclude: "FinOps" OR "Cloud Cost" in company description
```

### Inbound signals to watch

- Companies that star your GitHub repo
- Replies to a tech blog post or LinkedIn article you write on AWS costs
- Referrals from existing clients ("my friend's company has the same problem")
- AWS community Slack/Discord — questions about cost optimization

## Prioritization Matrix

| Criteria | Weight | Scoring |
|----------|--------|---------|
| Est. AWS spend > $30k/mo | 40% | 3 = confirmed, 2 = estimated, 1 = unclear |
| No existing FinOps tool | 30% | 3 = confirmed, 2 = likely, 0 = has one |
| Decision-maker reachable | 20% | 3 = direct contact, 2 = 1 hop, 1 = cold |
| Series A/B/C funded | 10% | 3 = yes, 1 = bootstrapped |

**Score ≥ 8/12 → Priority outreach. Score 5–7 → Normal queue. Score < 5 → Skip.**

## Discovery Call Qualification (BANT)

| Dimension | Qualifying question |
|-----------|---------------------|
| **Budget** | "Do you have a budget or approval process for one-time consulting work?" |
| **Authority** | "Are you the person who decides on cost-optimization tooling, or is there someone else?" |
| **Need** | "How much do you spend on AWS per month, roughly? Has that been a topic in exec conversations?" |
| **Timeline** | "Is there a near-term milestone — board review, budget cycle — where having this data would be useful?" |

Minimum viable client: Has the need (AWS spend is noticeable), has authority to say yes to a fixed-fee engagement, and has a timeline within 4 weeks.
