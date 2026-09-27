# CloudThrift: 60-Second Cloud Diagnostic (Secure IAM Setup)

Welcome to the CloudThrift open-source onboarding repository.

**This is the X-Ray.** Our automated diagnostic engine requires temporary, **strictly read-only** access to your AWS environment's metadata and billing dashboards to filter thousands of noisy alerts down to the top 5 zero-risk financial actions.

**We provide the Surgeon.** Our Senior CloudOps architects use this data to map these savings directly to your 12-month business roadmap, ensuring every change is executed safely with zero downtime.

We believe in complete transparency. Every CloudFormation template in this repository is open-source and heavily commented so your security and engineering teams can verify exactly what permissions are being granted before execution.

---

## Security Guarantee: What We Can and Cannot Do

This process provisions a Cross-Account IAM Role secured by a unique `ExternalId`.
The `ExternalId` is a shared secret known only to you and our platform — it prevents
any other party in our AWS account from assuming your role (the "confused deputy" protection).

**What we CAN do:**
- View resource metadata (instance types, regions, tags — not the data inside)
- View AWS Cost Explorer, Budgets, and Compute Optimizer recommendations
- Read AWS Trusted Advisor checks
- Read the raw billing data in your Cost and Usage Report (CUR) S3 bucket (if you opt in)

**What we CANNOT do:**
- Read your customer data, application code, or database contents
- Download objects from any S3 bucket except the specific billing bucket you designate
- Start, stop, modify, or delete any of your AWS resources
- Access anything not explicitly listed in the policies below

Our data collection script provisions a cross-account role utilising AWS-managed
`ViewOnlyAccess` and billing-specific policies. We physically cannot read your customer
data, application code, or database contents. We only look at resource metadata and
billing metrics.

---

## Policies Granted

### AWS-Managed Policies (maintained by AWS)
| Policy | Purpose |
|--------|---------|
| `ViewOnlyAccess` | Resource metadata — instance types, regions, tags. No data-plane access |
| `AWSBillingReadOnlyAccess` | Cost Explorer, Budgets, billing console |
| `AWSComputeOptimizerReadOnlyAccess` | ML-powered right-sizing recommendations |

### Custom Inline Policy (specific gaps)
| Permission | Purpose |
|-----------|---------|
| `support:DescribeTrustedAdvisorChecks/Result` | Read Trusted Advisor cost checks |
| `s3:ListBucket`, `s3:GetObject` on CUR bucket | Read your billing CSV files (opt-in only) |

---

## How to Grant Access (Client Instructions)

### Prerequisites
- AWS CLI installed and authenticated with a role that can create IAM roles
  (typically an Administrator or IAM-admin role in your account)
- Bash environment (Linux, macOS, or WSL on Windows)

### Option A — CloudFormation (recommended)

CloudFormation creates a versioned, auditable stack. You can inspect it in the
AWS Console under **CloudFormation → Stacks** at any time.

```bash
# Set your secrets in the shell (never commit these values)
export FINOPS_CENTRAL_ACCOUNT_ID=<provided by FinOps team>
export FINOPS_EXTERNAL_ID=<provided by FinOps team>

# Optional: if you have CUR enabled, set your bucket name
export FINOPS_CUR_BUCKET=your-cur-billing-bucket-name

# Run setup
chmod +x pillar-a/scripts/setup-client-role.sh
./pillar-a/scripts/setup-client-role.sh --env prod --profile <your-aws-profile>
```

The script prints the **Role ARN** at the end. Send that ARN to your FinOps consultant.

### Option B — Direct AWS CLI (simpler alternative)

Prefer to see every command executed? Use `--mode cli`:

```bash
export FINOPS_CENTRAL_ACCOUNT_ID=<provided by FinOps team>
export FINOPS_EXTERNAL_ID=<provided by FinOps team>

./pillar-a/scripts/setup-client-role.sh --mode cli --profile <your-aws-profile>
```

This calls the AWS CLI directly — no CloudFormation. A local `.finops_audit_state`
file is created for teardown. Keep it in the same directory.

---

## Teardown: How to Revoke Access

You retain complete control. Run the teardown at any time to permanently remove our access.

**If you used CloudFormation (Option A):**
```bash
./pillar-a/scripts/teardown-client-role.sh --profile <your-aws-profile>
```

**If you used CLI (Option B):**
```bash
./pillar-a/scripts/teardown-client-role.sh --mode cli --profile <your-aws-profile>
```

Both paths detach all policies and delete the IAM role, leaving **zero footprint**
in your AWS environment.

---

## For the FinOps Team: Internal Audit Workflow

Once the client provides the Role ARN:

1. **Assume role** — `sts:AssumeRole` with the per-client `ExternalId`
2. **Run audit engine** — `pillar-b/engine/main.py --role-arn <arn> --external-id <id>`
3. **Review output** — PDF report + JSON dashboard payload
4. **Notify client** — data pull complete, safe to run teardown

See `pillar-b/` for the full audit engine implementation.

---

## Files in This Folder

```
pillar-a/
├── cloudformation/
│   ├── client-iam-role.yaml          CloudFormation template (primary IaC)
│   └── parameters/
│       ├── dev.json                  Dev environment parameter defaults
│       └── prod.json                 Prod environment parameter defaults
├── scripts/
│   ├── setup-client-role.sh          Setup: CloudFormation or CLI mode
│   └── teardown-client-role.sh       Teardown: CloudFormation or CLI mode
├── client-security-guarantee.md      One-pager for client security conversations
└── README.md                         This file
```
