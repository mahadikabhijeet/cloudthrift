# Client Onboarding — FinOps Audit Platform

Step-by-step reference for every new client engagement.
Covers: pre-engagement, client setup, what to collect, auditor setup, running the audit.

---

## Overview

```
You (auditor, local laptop)          Client (their AWS account)
────────────────────────────         ──────────────────────────
1. Generate ExternalId           →   2. Client runs setup script
                                 ←   3. Client sends: Account ID + Role ARN
4. Add to accounts.json
5. Run audit locally
6. Deliver report
```

The audit engine runs entirely on your laptop — nothing is deployed to AWS
except the read-only IAM role in the client's account (IAM is free).

---

## Step 1 — Before you contact the client

Generate a unique ExternalId for this client. It is a shared secret;
treat it like a password — store it securely, never commit it.

```bash
python3 -c "import secrets; print('finops-' + secrets.token_hex(12))"
# example: finops-a3f92b1c8e47d05f
```

Note down:
- `CLIENT_NAME`     — short slug, no spaces (e.g. `acme-prod`)
- `EXTERNAL_ID`     — generated above
- `YOUR_ACCOUNT_ID` — your auditor AWS account ID (the account you run audits from)

---

## Step 2 — What to send the client

Send them **one** of the two setup options below plus a short message.

### Files to attach

| Option | File to send | When to use |
|--------|-------------|-------------|
| A — CloudFormation | `infra/cloudformation/client-iam-role.yaml` | Most clients (console or CLI) |
| B — CLI script | `infra/scripts/setup-client-role.sh` | Clients comfortable with bash |
| Fallback | `infra/cloudformation/client-iam-role-inline-only.yaml` | If client's IAM restricts `iam:AttachRolePolicy` |

### Message template

> Hi [Name],
>
> To run the cost audit I need a read-only IAM role in your AWS account.
> Please run the attached setup using your AWS CLI (admin or IAM permissions required).
>
> **Your values for the setup:**
> ```
> CentralAccountId : <YOUR_ACCOUNT_ID>
> ExternalId       : <EXTERNAL_ID>
> RoleName         : FinOps-Audit-ReadOnly-Role
> ```
>
> **Option A — CloudFormation (recommended):**
> ```bash
> aws cloudformation deploy \
>   --template-file client-iam-role.yaml \
>   --stack-name finops-audit-role \
>   --capabilities CAPABILITY_NAMED_IAM \
>   --parameter-overrides \
>     CentralAccountId=<YOUR_ACCOUNT_ID> \
>     ExternalId=<EXTERNAL_ID> \
>     RoleName=FinOps-Audit-ReadOnly-Role \
>     Environment=prod
> ```
>
> **Option B — Shell script:**
> ```bash
> export FINOPS_CENTRAL_ACCOUNT_ID=<YOUR_ACCOUNT_ID>
> export FINOPS_EXTERNAL_ID=<EXTERNAL_ID>
> bash setup-client-role.sh --mode cli
> ```
>
> Once done, please send me:
> 1. Your AWS Account ID
> 2. The Role ARN (run the command below to get it):
>    ```bash
>    aws cloudformation describe-stacks \
>      --stack-name finops-audit-role \
>      --query 'Stacks[0].Outputs[?OutputKey==`RoleArn`].OutputValue' \
>      --output text
>    ```
>
> The role is read-only. You can review the exact permissions in the attached template.
> It can be deleted after the engagement with `aws cloudformation delete-stack --stack-name finops-audit-role`.

---

## Step 3 — What to collect from the client

You need exactly three things:

| Item | Example | How client gets it |
|------|---------|-------------------|
| Account ID | `123456789012` | `aws sts get-caller-identity --query Account` |
| Role ARN | `arn:aws:iam::123456789012:role/FinOps-Audit-ReadOnly-Role` | CFN output (command above) or `aws iam get-role --role-name FinOps-Audit-ReadOnly-Role --query Role.Arn` |
| ExternalId confirmation | `finops-a3f92b1c8e47d05f` | You already have this — just confirm they used it |

---

## Step 4 — Add client to accounts.json

Edit `infra/accounts.json` (gitignored — never commit it).
Add one entry per client:

```json
{
  "default_region": "us-east-1",
  "accounts": [
    {
      "id":          "<CLIENT_ACCOUNT_ID>",
      "name":        "<CLIENT_NAME>",
      "env":         "prod",
      "role_arn":    "<ROLE_ARN_FROM_CLIENT>",
      "external_id": "<EXTERNAL_ID_YOU_GENERATED>",
      "region":      "us-east-1",
      "enabled":     true
    }
  ]
}
```

**Multiple clients** — just add more entries to the `accounts` array.
Use `"enabled": false` to skip a client without deleting their entry.

### If you have your own AWS credentials as the base for STS

If you're not using the default AWS profile, add `"profile": "your-profile-name"` to the entry.
The `profile` field is optional — omit it to use the default credential chain.

---

## Step 5 — Verify before running

```bash
# Confirm accounts.json is wired correctly
python src/run_all_accounts.py --env prod --dry-run

# Expected output per client:
#   [prod      ] acme-prod            123456789012  →  arn:aws:iam::123456789012:role/FinOps-Audit-ReadOnly-Role (ExternalId set)
```

---

## Step 6 — Run the audit

```bash
# Single region — quick smoke test for a new client (~5-10 min)
python src/run_all_accounts.py \
  --filter <CLIENT_NAME> \
  --region-list us-east-1

# All 18 standard regions — full audit (~60-90 min per account)
python src/run_all_accounts.py \
  --filter <CLIENT_NAME> \
  --region-list "us-east-1,us-west-2,ca-central-1,sa-east-1,eu-west-1,eu-west-2,eu-west-3,eu-central-1,ap-southeast-1,ap-southeast-2,ap-northeast-1,ap-south-1,us-west-1,ap-east-1,af-south-1,eu-north-1,ap-northeast-2,me-central-1"

# All enabled accounts at once
python src/run_all_accounts.py --env prod --all-regions
```

Output lands in `dashboard/data/dashboard_<account_id>_<date>.json`.
Progress is checkpointed after each module — partial results survive if a run is interrupted.

---

## Step 7 — View results

```bash
cd dashboard
DATA_DIR=data python -m uvicorn app.main:app --port 8000
# Open http://localhost:8000
```

---

## Troubleshooting

### `AccessDenied` on `sts:AssumeRole`

The IAM user / role you're running the audit from doesn't have permission to assume the client role.

```bash
# Add sts:AssumeRole permission to your auditor IAM user
aws iam put-user-policy \
  --user-name <YOUR_IAM_USER> \
  --policy-name AllowFinOpsRoleAssumption \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": "sts:AssumeRole",
      "Resource": "arn:aws:iam::<CLIENT_ACCOUNT_ID>:role/FinOps-Audit-ReadOnly-Role"
    }]
  }'
```

### `SignatureDoesNotMatch` — Signature expired

Your system clock is out of sync with AWS (tolerance: ±5 min). Not an SSO issue.

```bash
# Linux / WSL
sudo timedatectl set-ntp true && sudo systemctl restart systemd-timesyncd
# or: sudo ntpdate -u pool.ntp.org

# macOS
sudo sntp -sS time.apple.com

# WSL after laptop sleep
sudo hwclock --hctosys
```

### `ExpiredTokenException`

SSO session expired. Re-authenticate:
```bash
aws sso login --profile <profile>
```

### `iam:AttachRolePolicy` denied during client setup

Client's IAM restricts attaching managed policies. Send them the inline-only fallback template:
```
infra/cloudformation/client-iam-role-inline-only.yaml
```
Both templates create identical effective permissions; the inline-only version embeds them directly instead of attaching AWS-managed policies.

### CFN stack in `ROLLBACK_COMPLETE` state

Client's previous attempt failed. They need to delete the stuck stack first:
```bash
aws cloudformation delete-stack --stack-name finops-audit-role
# wait ~30 seconds, then re-run the deploy command
```

### CE API returns `AccessDenied` (Savings Plans / RI coverage findings missing)

Cost Explorer API requires payer/billing account access. If the client account is a linked account under an AWS Organization, the payer account admin needs to enable **"Linked account access"** in Cost Explorer settings. The audit still runs and produces all other findings — CE-based findings are simply skipped with a log message.

---

## Self-test (your own account as both client and auditor)

When `CentralAccountId` = your own account ID, AWS allows same-account role assumption.

```bash
# Deploy role (client side)
aws cloudformation deploy \
  --template-file infra/cloudformation/client-iam-role.yaml \
  --stack-name finops-audit-role \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    CentralAccountId=<YOUR_ACCOUNT_ID> \
    ExternalId=<YOUR_EXTERNAL_ID> \
    RoleName=FinOps-Audit-ReadOnly-Role \
    Environment=prod

# Get role ARN
aws cloudformation describe-stacks \
  --stack-name finops-audit-role \
  --query 'Stacks[0].Outputs[?OutputKey==`RoleArn`].OutputValue' \
  --output text

# accounts.json entry
# {
#   "id":          "<YOUR_ACCOUNT_ID>",
#   "name":        "self-test",
#   "env":         "prod",
#   "role_arn":    "arn:aws:iam::<YOUR_ACCOUNT_ID>:role/FinOps-Audit-ReadOnly-Role",
#   "external_id": "<YOUR_EXTERNAL_ID>",
#   "region":      "us-east-1",
#   "enabled":     true
# }
```

---

## Cleanup after engagement

```bash
# Client runs this to remove the role when engagement is complete
aws cloudformation delete-stack --stack-name finops-audit-role

# You run this to archive the client
# In accounts.json: set "enabled": false  (keeps the record, skips future runs)
```
