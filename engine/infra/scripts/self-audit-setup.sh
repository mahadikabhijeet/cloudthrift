#!/usr/bin/env bash
# ==============================================================================
# Self-Audit Setup — audit YOUR OWN AWS account with the FinOps platform.
#
# This is a streamlined version of setup-client-role.sh for the case where
# the account being audited IS the account running the platform. It:
#   1. Detects your account ID automatically
#   2. Generates a random ExternalId (saved to .self-audit-state)
#   3. Creates the read-only IAM role in your account
#   4. Prints the exact `python` command to run the audit
#
# Usage:
#   cd <repo-root>
#   bash infra/scripts/self-audit-setup.sh [--mode cfn|cli] [--profile <profile>] [--region <region>]
#
# Requirements:
#   - AWS CLI v2 configured with credentials that have IAM permissions
#   - jq (only for --mode cfn — NOT required for the default cli mode)
#
# The role created here grants READ-ONLY access only. It cannot modify, delete,
# or create any resource in your account. See infra/client-security-guarantee.md.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TEMPLATE="${REPO_ROOT}/infra/cloudformation/client-iam-role.yaml"
STATE_FILE="${SCRIPT_DIR}/.self-audit-state"

MODE="cli"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"
PROFILE="${AWS_PROFILE:-default}"
ROLE_NAME="FinOps-Self-Audit-Role"
STACK_NAME="finops-self-audit-role"
ENV="dev"

usage() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Options:
  --mode     cli (direct AWS CLI, default) or cfn (CloudFormation — requires jq + iam:AttachRolePolicy)
  --profile  AWS CLI profile to use (default: default)
  --region   AWS region (default: us-east-1)
  -h, --help Show this help

No environment variables required — everything is auto-detected.
EOF
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)    MODE="$2";    shift 2 ;;
    --profile) PROFILE="$2"; shift 2 ;;
    --region)  REGION="$2";  shift 2 ;;
    -h|--help) usage ;;
    *)         echo "Unknown option: $1"; usage ;;
  esac
done

[[ "$MODE" =~ ^(cfn|cli)$ ]] || { echo "ERROR: --mode must be cfn or cli" >&2; exit 1; }

# ---- Check AWS CLI is available and credentials work -------------------------
if ! command -v aws &>/dev/null; then
  echo "ERROR: AWS CLI not found. Install it from https://aws.amazon.com/cli/" >&2
  exit 1
fi

echo "Checking AWS credentials..."
CALLER_IDENTITY=$(aws sts get-caller-identity --profile "$PROFILE" --region "$REGION" --output json 2>&1) || {
  echo ""
  echo "ERROR: AWS credentials are not configured or are invalid."
  echo ""
  echo "To fix this, run ONE of the following:"
  echo "  aws configure                          # enter key/secret interactively"
  echo "  aws configure sso                      # use AWS SSO / Identity Center"
  echo "  export AWS_ACCESS_KEY_ID=...           # set env vars directly"
  echo "  export AWS_SECRET_ACCESS_KEY=..."
  echo ""
  echo "If you have multiple profiles, pass --profile <name> to this script."
  exit 1
}

ACCOUNT_ID=$(echo "$CALLER_IDENTITY" | grep -o '"Account": "[0-9]*"' | grep -o '[0-9]*')
CALLER_ARN=$(echo "$CALLER_IDENTITY" | grep -o '"Arn": "[^"]*"' | cut -d'"' -f4)

# ---- Generate or load ExternalId ---------------------------------------------
if [[ -f "$STATE_FILE" ]]; then
  # shellcheck source=/dev/null
  source "$STATE_FILE"
  echo "Loaded existing state from ${STATE_FILE}"
  echo "  Account ID  : ${ACCOUNT_ID}"
  echo "  External ID : ****${EXTERNAL_ID: -4}"
else
  if command -v openssl &>/dev/null; then
    EXTERNAL_ID=$(openssl rand -hex 16)
  else
    # Fallback: use $RANDOM + date (not cryptographically strong but fine for dev)
    EXTERNAL_ID="finops-$(date +%s)-${RANDOM}${RANDOM}"
  fi
fi

echo ""
echo "=================================================="
echo " FinOps Platform — Self-Audit Setup"
echo "=================================================="
echo " Account ID  : ${ACCOUNT_ID}"
echo " Caller      : ${CALLER_ARN}"
echo " Role Name   : ${ROLE_NAME}"
echo " Mode        : ${MODE}"
echo " Region      : ${REGION}"
echo " Profile     : ${PROFILE}"
echo " External ID : ****${EXTERNAL_ID: -4}  (saved to ${STATE_FILE})"
echo "=================================================="
echo ""

# Save state so teardown and the run command can reference it later
cat > "$STATE_FILE" <<EOF
ACCOUNT_ID=${ACCOUNT_ID}
EXTERNAL_ID=${EXTERNAL_ID}
ROLE_NAME=${ROLE_NAME}
STACK_NAME=${STACK_NAME}
PROFILE=${PROFILE}
REGION=${REGION}
MODE=${MODE}
EOF
chmod 600 "$STATE_FILE"  # ExternalId is a secret

ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"

# ==============================================================================
# PATH 1: CloudFormation (default, recommended)
# ==============================================================================
deploy_cfn() {
  if ! command -v jq &>/dev/null; then
    echo "ERROR: jq is required for CloudFormation mode." >&2
    echo "Install it: sudo apt install jq  OR  brew install jq" >&2
    echo "Or re-run with --mode cli to skip jq." >&2
    exit 1
  fi

  [[ -f "$TEMPLATE" ]] || { echo "ERROR: Template not found: ${TEMPLATE}" >&2; exit 1; }

  # ---- Clean up any terminal stack state that blocks re-deploy ---------------
  STACK_STATUS=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" --profile "$PROFILE" \
    --query 'Stacks[0].StackStatus' --output text 2>/dev/null || echo "DOES_NOT_EXIST")

  case "$STACK_STATUS" in
    ROLLBACK_COMPLETE|DELETE_FAILED|CREATE_FAILED)
      echo "[0/3] Stack is in terminal state '${STACK_STATUS}' — deleting it first..."

      # Show what caused the failure before deleting
      echo "      Failure reason:"
      aws cloudformation describe-stack-events \
        --stack-name "$STACK_NAME" \
        --region "$REGION" --profile "$PROFILE" \
        --query 'StackEvents[?contains(`["CREATE_FAILED","ROLLBACK_FAILED"]`, ResourceStatus)].{Resource:LogicalResourceId,Reason:ResourceStatusReason}' \
        --output table 2>/dev/null || true

      aws cloudformation delete-stack \
        --stack-name "$STACK_NAME" \
        --region "$REGION" --profile "$PROFILE"
      echo "      Waiting for deletion..."
      aws cloudformation wait stack-delete-complete \
        --stack-name "$STACK_NAME" \
        --region "$REGION" --profile "$PROFILE"
      echo "      Deleted."
      echo ""
      ;;
    UPDATE_ROLLBACK_COMPLETE)
      echo "[note] Stack exists in UPDATE_ROLLBACK_COMPLETE — will attempt re-deploy."
      ;;
    DOES_NOT_EXIST|"")
      ;;
    *)
      ;;
  esac

  echo "[1/3] Validating CloudFormation template..."
  aws cloudformation validate-template \
    --template-body "file://${TEMPLATE}" \
    --region "$REGION" --profile "$PROFILE" --output text > /dev/null
  echo "      Template valid."

  echo ""
  echo "[2/3] Deploying stack '${STACK_NAME}'..."
  echo "      (This may take 1-2 minutes)"
  aws cloudformation deploy \
    --template-file "$TEMPLATE" \
    --stack-name "$STACK_NAME" \
    --parameter-overrides \
        "CentralAccountId=${ACCOUNT_ID}" \
        "ExternalId=${EXTERNAL_ID}" \
        "RoleName=${ROLE_NAME}" \
        "Environment=${ENV}" \
        "EnableCURAccess=true" \
    --capabilities CAPABILITY_NAMED_IAM \
    --region "$REGION" --profile "$PROFILE" \
    --tags ManagedBy=FinOpsPlatform Pillar=A Environment="${ENV}" SelfAudit=true || {
      echo ""
      echo "ERROR: CloudFormation deploy failed."
      echo ""
      echo "Most likely cause: the 'finops' IAM user lacks cloudformation:* or iam:* permissions."
      echo ""
      echo "Quickest fix — re-run with --mode cli (uses direct IAM API, no CloudFormation):"
      echo "  bash infra/scripts/self-audit-setup.sh --mode cli"
      echo ""
      echo "Or check the exact error:"
      echo "  aws cloudformation describe-stack-events --stack-name ${STACK_NAME} \\"
      echo "    --query 'StackEvents[?contains(\`[\"CREATE_FAILED\",\"ROLLBACK_FAILED\"]\`,ResourceStatus)]' \\"
      echo "    --output table"
      exit 1
    }

  echo ""
  echo "[3/3] Stack deployed. Outputs:"
  aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" --profile "$PROFILE" \
    --query 'Stacks[0].Outputs[?OutputKey==`RoleArn`].OutputValue' \
    --output text
}

# ==============================================================================
# PATH 2: Direct AWS CLI (no jq needed)
# ==============================================================================
deploy_cli() {
  TRUST_POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "AllowSelfAudit",
    "Effect": "Allow",
    "Principal": { "AWS": "arn:aws:iam::${ACCOUNT_ID}:root" },
    "Action": "sts:AssumeRole",
    "Condition": { "StringEquals": { "sts:ExternalId": "${EXTERNAL_ID}" } }
  }]
}
EOF
)

  # Create or update role
  if aws iam get-role --role-name "$ROLE_NAME" --profile "$PROFILE" &>/dev/null 2>&1; then
    echo "[1/4] Role already exists — updating trust policy..."
    aws iam update-assume-role-policy \
      --role-name "$ROLE_NAME" \
      --policy-document "$TRUST_POLICY" \
      --profile "$PROFILE"
  else
    echo "[1/4] Creating IAM role: ${ROLE_NAME}..."
    aws iam create-role \
      --role-name "$ROLE_NAME" \
      --assume-role-policy-document "$TRUST_POLICY" \
      --description "Read-only self-audit role for FinOps platform" \
      --profile "$PROFILE" \
      --tags Key=ManagedBy,Value=FinOpsPlatform Key=Pillar,Value=A Key=SelfAudit,Value=true \
      > /dev/null
  fi

  # ---- Primary: try attaching AWS managed policies ---------------------------
  # Requires iam:AttachRolePolicy. If the caller lacks it, fall through to the
  # comprehensive inline fallback automatically — no manual re-run needed.
  echo "[2/3] Attaching policies..."
  USING_MANAGED=0
  if aws iam attach-role-policy \
       --role-name "$ROLE_NAME" \
       --policy-arn "arn:aws:iam::aws:policy/ViewOnlyAccess" \
       --profile "$PROFILE" 2>/dev/null; then
    aws iam attach-role-policy \
      --role-name "$ROLE_NAME" \
      --policy-arn "arn:aws:iam::aws:policy/AWSBillingReadOnlyAccess" \
      --profile "$PROFILE" 2>/dev/null && USING_MANAGED=1 || {
        aws iam detach-role-policy \
          --role-name "$ROLE_NAME" \
          --policy-arn "arn:aws:iam::aws:policy/ViewOnlyAccess" \
          --profile "$PROFILE" 2>/dev/null || true
      }
  fi

  if [[ "$USING_MANAGED" -eq 1 ]]; then
    echo "      Attached: ViewOnlyAccess + AWSBillingReadOnlyAccess (AWS managed)"
    echo "      Adding gap inline policy (CE, pricing, savings plans, compute-optimizer)..."
    GAP_POLICY=$(cat <<'POLICY'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CostExplorerRead",
      "Effect": "Allow",
      "Action": [
        "ce:GetCostAndUsage", "ce:GetCostAndUsageWithResources",
        "ce:GetCostForecast", "ce:GetReservationCoverage",
        "ce:GetReservationPurchaseRecommendation", "ce:GetReservationUtilization",
        "ce:GetRightsizingRecommendation", "ce:GetSavingsPlansCoverage",
        "ce:GetSavingsPlansUtilization", "ce:GetSavingsPlansUtilizationDetails",
        "ce:GetDimensionValues", "ce:GetTags", "ce:GetUsageForecast",
        "ce:ListCostAllocationTags", "ce:ListCostCategoryDefinitions"
      ],
      "Resource": "*"
    },
    {
      "Sid": "PricingAndSavingsPlansRead",
      "Effect": "Allow",
      "Action": [
        "pricing:DescribeServices", "pricing:GetAttributeValues", "pricing:GetProducts",
        "savingsplans:DescribeSavingsPlans", "savingsplans:DescribeSavingsPlansOfferings",
        "savingsplans:DescribeSavingsPlanRates", "savingsplans:ListTagsForResource"
      ],
      "Resource": "*"
    },
    {
      "Sid": "ComputeOptimizerRead",
      "Effect": "Allow",
      "Action": [
        "compute-optimizer:GetEC2InstanceRecommendations",
        "compute-optimizer:GetEC2RecommendationProjectedMetrics",
        "compute-optimizer:GetAutoScalingGroupRecommendations",
        "compute-optimizer:GetEBSVolumeRecommendations",
        "compute-optimizer:GetLambdaFunctionRecommendations",
        "compute-optimizer:GetEnrollmentStatus",
        "compute-optimizer:DescribeRecommendationExportJobs"
      ],
      "Resource": "*"
    }
  ]
}
POLICY
)
    aws iam put-role-policy \
      --role-name "$ROLE_NAME" \
      --policy-name "FinOps-AuditGaps" \
      --policy-document "$GAP_POLICY" \
      --profile "$PROFILE"
    echo "      Added: FinOps-AuditGaps (inline)"

  else
    echo "      iam:AttachRolePolicy not permitted — using comprehensive inline policies instead."
    COST_POLICY=$(cat <<'POLICY'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CostExplorerRead",
      "Effect": "Allow",
      "Action": [
        "ce:GetCostAndUsage", "ce:GetCostAndUsageWithResources",
        "ce:GetCostForecast", "ce:GetReservationCoverage",
        "ce:GetReservationPurchaseRecommendation", "ce:GetReservationUtilization",
        "ce:GetRightsizingRecommendation", "ce:GetSavingsPlansCoverage",
        "ce:GetSavingsPlansUtilization", "ce:GetSavingsPlansUtilizationDetails",
        "ce:GetDimensionValues", "ce:GetTags", "ce:GetUsageForecast",
        "ce:ListCostAllocationTags", "ce:ListCostCategoryDefinitions"
      ],
      "Resource": "*"
    },
    {
      "Sid": "BillingRead",
      "Effect": "Allow",
      "Action": [
        "billing:GetBillingData", "billing:GetBillDetails",
        "billing:GetPreferences", "billing:ListBillingViews",
        "budgets:DescribeBudgets", "budgets:ViewBudget",
        "freetier:GetFreeTierAlertThreshold", "freetier:GetFreeTierUsage",
        "cur:DescribeReportDefinitions",
        "pricing:DescribeServices", "pricing:GetAttributeValues", "pricing:GetProducts",
        "savingsplans:DescribeSavingsPlans", "savingsplans:DescribeSavingsPlansOfferings",
        "savingsplans:DescribeSavingsPlanRates", "savingsplans:ListTagsForResource",
        "organizations:DescribeAccount", "organizations:DescribeOrganization",
        "organizations:ListAccounts", "organizations:ListTagsForResource",
        "support:DescribeTrustedAdvisorChecks", "support:DescribeTrustedAdvisorCheckResult"
      ],
      "Resource": "*"
    }
  ]
}
POLICY
)
    RESOURCE_POLICY=$(cat <<'POLICY'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ResourceDiscovery",
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeInstances", "ec2:DescribeInstanceTypes",
        "ec2:DescribeInstanceStatus", "ec2:DescribeReservedInstances",
        "ec2:DescribeImages", "ec2:DescribeVolumes", "ec2:DescribeSnapshots",
        "ec2:DescribeAddresses", "ec2:DescribeNatGateways",
        "ec2:DescribeVpcs", "ec2:DescribeSubnets", "ec2:DescribeRegions",
        "rds:DescribeDBInstances", "rds:DescribeDBClusters",
        "rds:DescribeReservedDBInstances", "rds:ListTagsForResource",
        "lambda:ListFunctions", "lambda:GetFunctionConfiguration", "lambda:ListTags",
        "ecs:ListClusters", "ecs:DescribeClusters",
        "ecs:ListServices", "ecs:DescribeServices",
        "eks:ListClusters", "eks:DescribeCluster",
        "elasticloadbalancing:DescribeLoadBalancers",
        "elasticloadbalancing:DescribeTargetGroups",
        "elasticloadbalancing:DescribeTargetHealth",
        "autoscaling:DescribeAutoScalingGroups",
        "s3:ListAllMyBuckets", "s3:GetBucketLocation",
        "s3:GetBucketTagging", "s3:GetBucketVersioning",
        "cloudwatch:GetMetricData", "cloudwatch:GetMetricStatistics",
        "cloudwatch:ListMetrics",
        "cloudtrail:LookupEvents",
        "tag:GetResources", "tag:GetTagKeys", "tag:GetTagValues",
        "compute-optimizer:GetEC2InstanceRecommendations",
        "compute-optimizer:GetEC2RecommendationProjectedMetrics",
        "compute-optimizer:GetAutoScalingGroupRecommendations",
        "compute-optimizer:GetEBSVolumeRecommendations",
        "compute-optimizer:GetLambdaFunctionRecommendations",
        "compute-optimizer:GetEnrollmentStatus",
        "compute-optimizer:DescribeRecommendationExportJobs"
      ],
      "Resource": "*"
    }
  ]
}
POLICY
)
    aws iam put-role-policy \
      --role-name "$ROLE_NAME" \
      --policy-name "FinOps-CostRead" \
      --policy-document "$COST_POLICY" \
      --profile "$PROFILE"
    aws iam put-role-policy \
      --role-name "$ROLE_NAME" \
      --policy-name "FinOps-ResourceDiscovery" \
      --policy-document "$RESOURCE_POLICY" \
      --profile "$PROFILE"
    echo "      Added: FinOps-CostRead + FinOps-ResourceDiscovery (inline)"
  fi

  echo "[3/3] Done."
}


# ---- Deploy ------------------------------------------------------------------
if [[ "$MODE" == "cfn" ]]; then
  deploy_cfn
else
  deploy_cli
fi

# ---- Print the run command ---------------------------------------------------
cat <<EOF


================================================================
  SETUP COMPLETE
================================================================

Your read-only audit role is ready. To run a live audit of your
own account, execute the following from the repo root:

  cd ${REPO_ROOT}

  python src/engine/main.py \\
    --account-id ${ACCOUNT_ID} \\
    --account-name "My AWS Account" \\
    --role-arn ${ROLE_ARN} \\
    --external-id ${EXTERNAL_ID} \\
    --region ${REGION} \\
    --output-dir ./reports

Then copy the report to the dashboard:

  mkdir -p dashboard/data
  cp reports/dashboard_${ACCOUNT_ID}_*.json dashboard/data/

And open: http://localhost:8000

To REMOVE the role when you are done:
  bash ${SCRIPT_DIR}/self-audit-teardown.sh

================================================================
EOF
