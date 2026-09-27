# Client Security Guarantee

Our data collection script provisions a cross-account role utilising AWS-managed
`ViewOnlyAccess` and billing-specific policies. We physically **cannot** read your
customer data, application code, or database contents. We only look at resource
metadata and billing metrics.

## What This Means in Plain English

When you run our setup script, it creates a read-only "visitor pass" inside your
AWS account. Think of it like giving a building inspector a keycard that only opens
the lobby and the electrical panel — they cannot enter your offices or touch anything
on your desks.

Specifically, the role we create:

| Can we see it? | Example |
|---------------|---------|
| ✅ Yes | Which EC2 instance types you are running |
| ✅ Yes | How much you spent on RDS last month |
| ✅ Yes | Whether your Savings Plan coverage is low |
| ✅ Yes | Your CUR billing files (only if you provide the bucket name) |
| ❌ No | The data inside your databases |
| ❌ No | The contents of your application S3 buckets |
| ❌ No | Your source code, secrets, or environment variables |
| ❌ No | Any action that modifies, stops, or deletes a resource |

## How We Prevent Misuse

1. **ExternalId** — A unique secret shared only between you and our platform.
   Even if someone at our company had your Role ARN, they could not assume it
   without the correct ExternalId.

2. **Least-privilege policies** — We use AWS-managed policies reviewed by AWS's
   own security team, plus a narrow custom policy for Trusted Advisor and your
   CUR bucket only.

3. **You hold the off-switch** — Run `teardown-client-role.sh` at any time to
   permanently delete the role. We cannot stop you or restore access after that.

4. **Open source** — Every line of our setup scripts and CloudFormation template
   is in this repository. Your security team can audit exactly what is deployed.

## Reference

Full technical details: [pillar-a/README.md](./README.md)

For questions or concerns, contact your FinOps consultant directly.
