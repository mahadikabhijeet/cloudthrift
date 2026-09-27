#!/usr/bin/env bash
# ==============================================================================
# Pillar A: Deploy the FinOps cross-account IAM role into a client account.
#
# TWO deployment paths — choose the one that fits your situation:
#
#   PATH 1 (Default): CloudFormation — recommended for repeatability and auditing.
#     Produces a versioned stack that is easy to update and tear down cleanly.
#
#   PATH 2: Direct AWS CLI — simpler single-command alternative with no CFN dependency.
#     Useful when clients want to inspect and run the setup themselves.
#     Pass --mode cli to use this path.
#
# Usage:
#   ./infra/scripts/setup-client-role.sh [--mode cfn|cli] --env <dev|prod> --profile <aws-profile>
#
# Required environment variables:
#   FINOPS_CENTRAL_ACCOUNT_ID   12-digit account ID of the central FinOps account
#   FINOPS_EXTERNAL_ID          Unique secret per client (min 8 chars) — NEVER commit this
#
# Optional environment variables:
#   FINOPS_CUR_BUCKET           Name of the client's CUR S3 bucket (enables S3 read access)
#
# Example:
#   export FINOPS_CENTRAL_ACCOUNT_ID=123456789012
#   export FINOPS_EXTERNAL_ID=$(openssl rand -hex 16)
#   ./infra/scripts/setup-client-role.sh --env prod --profile client-admin
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TEMPLATE="${REPO_ROOT}/infra/cloudformation/client-iam-role.yaml"
STATE_FILE="${SCRIPT_DIR}/.finops_audit_state"

# Defaults
MODE="cfn"
ENV="prod"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"
PROFILE="${AWS_PROFILE:-default}"
STACK_NAME="finops-infra-client-iam-role"
ROLE_NAME="FinOps-Audit-ReadOnly-Role"
CUSTOM_POLICY_NAME="FinOps-Custom-Audit-Policy"

usage() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Options:
  --mode      Deployment mode: cfn (CloudFormation, default) or cli (direct AWS CLI)
  --env       Environment (dev|staging|prod), default: prod
  --profile   AWS CLI profile for the TARGET client account, default: default
  --region    AWS region, default: us-east-1
  --stack     CloudFormation stack name (cfn mode), default: finops-infra-client-iam-role
  --role      IAM role name (cli mode), default: FinOps-Audit-ReadOnly-Role
  -h, --help  Show this help

Required environment variables:
  FINOPS_CENTRAL_ACCOUNT_ID   Central account ID
  FINOPS_EXTERNAL_ID          Per-client secret External ID

Optional environment variables:
  FINOPS_CUR_BUCKET           CUR S3 bucket name (grants read access to that bucket)
EOF
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)    MODE="$2";        shift 2 ;;
    --env)     ENV="$2";         shift 2 ;;
    --profile) PROFILE="$2";     shift 2 ;;
    --region)  REGION="$2";      shift 2 ;;
    --stack)   STACK_NAME="$2";  shift 2 ;;
    --role)    ROLE_NAME="$2";   shift 2 ;;
    -h|--help) usage ;;
    *)         echo "Unknown option: $1"; usage ;;
  esac
done

# --- Validate inputs -----------------------------------------------------------
[[ "$ENV"  =~ ^(dev|staging|prod)$  ]] || { echo "ERROR: --env must be dev, staging, or prod" >&2; exit 1; }
[[ "$MODE" =~ ^(cfn|cli)$           ]] || { echo "ERROR: --mode must be cfn or cli" >&2; exit 1; }
[[ -n "${FINOPS_CENTRAL_ACCOUNT_ID:-}" ]] || { echo "ERROR: FINOPS_CENTRAL_ACCOUNT_ID is not set" >&2; exit 1; }
[[ -n "${FINOPS_EXTERNAL_ID:-}"        ]] || { echo "ERROR: FINOPS_EXTERNAL_ID is not set" >&2; exit 1; }
[[ ${#FINOPS_EXTERNAL_ID} -ge 8        ]] || { echo "ERROR: FINOPS_EXTERNAL_ID must be at least 8 characters" >&2; exit 1; }

CUR_BUCKET="${FINOPS_CUR_BUCKET:-}"

echo "=================================================="
echo " FinOps Platform — Pillar A: Setup Client Role"
echo "=================================================="
echo " Mode        : ${MODE}"
echo " Environment : ${ENV}"
echo " Region      : ${REGION}"
echo " Profile     : ${PROFILE}"
echo " Central Acct: ${FINOPS_CENTRAL_ACCOUNT_ID}"
echo " External ID : ****${FINOPS_EXTERNAL_ID: -4}"
[[ -n "$CUR_BUCKET" ]] && echo " CUR Bucket  : ${CUR_BUCKET}"
echo "=================================================="
echo ""


# ==============================================================================
# PATH 1: CloudFormation (default)
# ==============================================================================
deploy_cfn() {
  local PARAMS_FILE="${REPO_ROOT}/infra/cloudformation/parameters/${ENV}.json"
  [[ -f "$PARAMS_FILE" ]] || { echo "ERROR: Parameter file not found: ${PARAMS_FILE}" >&2; exit 1; }

  local PARAMETERS
  PARAMETERS=$(jq \
    --arg central  "$FINOPS_CENTRAL_ACCOUNT_ID" \
    --arg extid    "$FINOPS_EXTERNAL_ID" \
    --arg cur      "$CUR_BUCKET" \
    'map(
      if .ParameterKey == "CentralAccountId" then .ParameterValue = $central
      elif .ParameterKey == "ExternalId"     then .ParameterValue = $extid
      elif .ParameterKey == "EnableCURAccess" and ($cur != "") then .ParameterValue = "true"
      else .
      end
    )' "$PARAMS_FILE")

  echo "[1/3] Validating CloudFormation template..."
  aws cloudformation validate-template \
    --template-body "file://${TEMPLATE}" \
    --region "$REGION" --profile "$PROFILE" --output text > /dev/null
  echo "      Template valid."

  echo ""
  echo "[2/3] Deploying stack '${STACK_NAME}'..."
  aws cloudformation deploy \
    --template-file "$TEMPLATE" \
    --stack-name "$STACK_NAME" \
    --parameter-overrides "$(echo "$PARAMETERS" | jq -r '.[] | "\(.ParameterKey)=\(.ParameterValue)"')" \
    --capabilities CAPABILITY_NAMED_IAM \
    --region "$REGION" --profile "$PROFILE" \
    --tags ManagedBy=FinOpsPlatform Pillar=A Environment="$ENV" || {
      echo ""
      echo "ERROR: CloudFormation deploy failed."
      echo ""
      echo "If the error is 'not authorized to perform: iam:AttachRolePolicy', use the"
      echo "inline-only fallback template which requires no managed policy attachment:"
      echo ""
      echo "  TEMPLATE=${REPO_ROOT}/infra/cloudformation/client-iam-role-inline-only.yaml"
      echo "  # then re-run this script"
      echo ""
      echo "Or switch to CLI mode (auto-detects and falls back):"
      echo "  ./infra/scripts/setup-client-role.sh --mode cli ..."
      echo ""
      echo "Check the exact CloudFormation error:"
      echo "  aws cloudformation describe-stack-events --stack-name ${STACK_NAME} \\"
      echo "    --query 'StackEvents[?ResourceStatus==\`CREATE_FAILED\`].ResourceStatusReason' \\"
      echo "    --output text"
      exit 1
    }

  echo ""
  echo "[3/3] Stack outputs:"
  aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" --profile "$PROFILE" \
    --query 'Stacks[0].Outputs' --output table

  echo ""
  echo "Done. Share the RoleArn with the FinOps platform team."
}


# ==============================================================================
# PATH 2: Direct AWS CLI (client-simple alternative)
# Mirrors the transparency and auditability of main-branch setup_finops_access.sh
# but with parameterised ExternalId (never hard-coded).
# ==============================================================================
deploy_cli() {
  echo "[1/5] Creating trust policy..."
  local TRUST_POLICY
  TRUST_POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "AWS": "arn:aws:iam::${FINOPS_CENTRAL_ACCOUNT_ID}:root" },
    "Action": "sts:AssumeRole",
    "Condition": { "StringEquals": { "sts:ExternalId": "${FINOPS_EXTERNAL_ID}" } }
  }]
}
EOF
)

  echo "[2/5] Creating IAM role: ${ROLE_NAME}..."
  aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document "$TRUST_POLICY" \
    --description "Read-only role for FinOps billing and architecture audit" \
    --profile "$PROFILE" --region "$REGION" \
    --tags Key=ManagedBy,Value=FinOpsPlatform Key=Pillar,Value=A Key=Environment,Value="$ENV" \
    > /dev/null

  echo "ROLE_NAME=${ROLE_NAME}"         > "$STATE_FILE"
  echo "CUSTOM_POLICY_NAME=${CUSTOM_POLICY_NAME}" >> "$STATE_FILE"
  echo "PROFILE=${PROFILE}"             >> "$STATE_FILE"
  echo "REGION=${REGION}"               >> "$STATE_FILE"

  # ---- Primary: try attaching AWS managed policies ---------------------------
  # Most client admin roles have iam:AttachRolePolicy. If not, the script falls
  # back to equivalent comprehensive inline policies automatically.
  echo "[3/5] Attaching policies..."
  local USING_MANAGED=0
  if aws iam attach-role-policy \
       --role-name "$ROLE_NAME" \
       --policy-arn "arn:aws:iam::aws:policy/ViewOnlyAccess" \
       --profile "$PROFILE" --region "$REGION" 2>/dev/null; then
    aws iam attach-role-policy \
      --role-name "$ROLE_NAME" \
      --policy-arn "arn:aws:iam::aws:policy/AWSBillingReadOnlyAccess" \
      --profile "$PROFILE" --region "$REGION" 2>/dev/null && USING_MANAGED=1 || {
        aws iam detach-role-policy \
          --role-name "$ROLE_NAME" \
          --policy-arn "arn:aws:iam::aws:policy/ViewOnlyAccess" \
          --profile "$PROFILE" --region "$REGION" 2>/dev/null || true
      }
  fi

  if [[ "$USING_MANAGED" -eq 1 ]]; then
    echo "      Attached: ViewOnlyAccess + AWSBillingReadOnlyAccess (AWS managed)"
    echo "[4/5] Adding gap inline policy (CE, pricing, savings plans, compute-optimizer, support)..."
    local CUR_STMT=""
    if [[ -n "$CUR_BUCKET" ]]; then
      CUR_STMT=',{"Sid":"CURBucketRead","Effect":"Allow","Action":["s3:ListBucket","s3:GetObject","s3:GetBucketLocation"],"Resource":["arn:aws:s3:::'"${CUR_BUCKET}"'","arn:aws:s3:::'"${CUR_BUCKET}"'/*"]}'
      echo "      CUR bucket access: ${CUR_BUCKET}"
    fi
    local GAP_POLICY
    GAP_POLICY=$(cat <<POLICY
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
      "Sid": "ComputeOptimizerAndSupportRead",
      "Effect": "Allow",
      "Action": [
        "compute-optimizer:GetEC2InstanceRecommendations",
        "compute-optimizer:GetEC2RecommendationProjectedMetrics",
        "compute-optimizer:GetAutoScalingGroupRecommendations",
        "compute-optimizer:GetEBSVolumeRecommendations",
        "compute-optimizer:GetLambdaFunctionRecommendations",
        "compute-optimizer:GetEnrollmentStatus",
        "compute-optimizer:DescribeRecommendationExportJobs",
        "support:DescribeTrustedAdvisorChecks",
        "support:DescribeTrustedAdvisorCheckResult"
      ],
      "Resource": "*"
    }${CUR_STMT}
  ]
}
POLICY
)
    aws iam put-role-policy \
      --role-name "$ROLE_NAME" \
      --policy-name "$CUSTOM_POLICY_NAME" \
      --policy-document "$GAP_POLICY" \
      --profile "$PROFILE" --region "$REGION"
    echo "      Added: ${CUSTOM_POLICY_NAME} (inline gap policy)"

  else
    echo "      iam:AttachRolePolicy not permitted — using comprehensive inline policies instead."
    echo "      (equivalent to primary path — all actions are read-only)"
    [[ -n "$CUR_BUCKET" ]] && echo "      CUR bucket access: ${CUR_BUCKET}"
    local CUR_STMT=""
    if [[ -n "$CUR_BUCKET" ]]; then
      CUR_STMT=',{"Sid":"CURBucketRead","Effect":"Allow","Action":["s3:ListBucket","s3:GetObject","s3:GetBucketLocation"],"Resource":["arn:aws:s3:::'"${CUR_BUCKET}"'","arn:aws:s3:::'"${CUR_BUCKET}"'/*"]}'
    fi
    local RESOURCE_POLICY
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
    local COST_POLICY
    COST_POLICY=$(cat <<POLICY
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
      "Sid": "BillingAndSupportRead",
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
    }${CUR_STMT}
  ]
}
POLICY
)
    aws iam put-role-policy \
      --role-name "$ROLE_NAME" \
      --policy-name "FinOps-ResourceDiscovery" \
      --policy-document "$RESOURCE_POLICY" \
      --profile "$PROFILE" --region "$REGION"
    aws iam put-role-policy \
      --role-name "$ROLE_NAME" \
      --policy-name "FinOps-BillingAndCost" \
      --policy-document "$COST_POLICY" \
      --profile "$PROFILE" --region "$REGION"
    echo "      Added: FinOps-ResourceDiscovery + FinOps-BillingAndCost (inline)"
  fi

  echo "[5/5] Done."
  local ACCOUNT_ID
  ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text --profile "$PROFILE")
  echo ""
  echo "================================================================="
  echo " SUCCESS — Share this Role ARN with the FinOps platform team:"
  echo " arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
  echo "================================================================="
}


# Dispatch
if [[ "$MODE" == "cfn" ]]; then
  deploy_cfn
else
  deploy_cli
fi
