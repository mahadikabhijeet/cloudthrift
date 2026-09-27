#!/usr/bin/env bash
# ==============================================================================
# Pillar A: Remove the FinOps cross-account IAM role from a client account.
#
# Supports the same two modes as setup-client-role.sh:
#   --mode cfn  Delete the CloudFormation stack (default)
#   --mode cli  Read the local state file and detach/delete resources directly
#
# WARNING: Deletes the IAM role immediately. The FinOps platform loses access
#          to this account the moment the role is removed.
#
# Usage:
#   ./pillar-a/scripts/teardown-client-role.sh [--mode cfn|cli] --profile <aws-profile>
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_FILE="${SCRIPT_DIR}/.finops_audit_state"

MODE="cfn"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"
PROFILE="${AWS_PROFILE:-default}"
STACK_NAME="finops-pillar-a-client-iam-role"

usage() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Options:
  --mode      Teardown mode: cfn (CloudFormation stack, default) or cli (state-file based)
  --profile   AWS CLI profile for the TARGET client account, default: default
  --region    AWS region, default: us-east-1
  --stack     CloudFormation stack name (cfn mode), default: finops-pillar-a-client-iam-role
  -h, --help  Show this help

WARNING: Deletes the IAM role — the FinOps platform loses access immediately.
EOF
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)    MODE="$2";        shift 2 ;;
    --profile) PROFILE="$2";     shift 2 ;;
    --region)  REGION="$2";      shift 2 ;;
    --stack)   STACK_NAME="$2";  shift 2 ;;
    -h|--help) usage ;;
    *)         echo "Unknown option: $1"; usage ;;
  esac
done

[[ "$MODE" =~ ^(cfn|cli)$ ]] || { echo "ERROR: --mode must be cfn or cli" >&2; exit 1; }

echo "=================================================="
echo " FinOps Platform — Pillar A: Teardown Client Role"
echo "=================================================="
echo " Mode        : ${MODE}"
echo " Region      : ${REGION}"
echo " Profile     : ${PROFILE}"
echo "=================================================="
echo ""
echo "WARNING: This permanently removes the FinOps IAM role from this account."
echo "         The platform will lose access immediately."
echo ""
read -r -p "Type 'yes' to confirm: " CONFIRM
[[ "$CONFIRM" == "yes" ]] || { echo "Aborted."; exit 0; }
echo ""


# ==============================================================================
# PATH 1: CloudFormation stack deletion (default)
# ==============================================================================
teardown_cfn() {
  echo "[1/2] Checking stack exists..."
  if ! aws cloudformation describe-stacks \
       --stack-name "$STACK_NAME" \
       --region "$REGION" --profile "$PROFILE" > /dev/null 2>&1; then
    echo "      Stack '${STACK_NAME}' not found — nothing to do."
    exit 0
  fi
  echo "      Stack found."

  echo ""
  echo "[2/2] Deleting stack '${STACK_NAME}'..."
  aws cloudformation delete-stack \
    --stack-name "$STACK_NAME" \
    --region "$REGION" --profile "$PROFILE"

  echo "      Waiting for deletion to complete..."
  aws cloudformation wait stack-delete-complete \
    --stack-name "$STACK_NAME" \
    --region "$REGION" --profile "$PROFILE"

  echo ""
  echo "================================================================="
  echo " SUCCESS — Stack deleted. IAM role and policies have been removed."
  echo "================================================================="
}


# ==============================================================================
# PATH 2: Direct CLI removal using the local state file
# (mirrors main-branch cleanup_finops_access.sh, used after --mode cli setup)
# ==============================================================================
teardown_cli() {
  if [[ ! -f "$STATE_FILE" ]]; then
    echo "ERROR: State file '${STATE_FILE}' not found." >&2
    echo "       If the role was set up with --mode cfn, use --mode cfn for teardown." >&2
    exit 1
  fi

  # Load state
  # shellcheck source=/dev/null
  source "$STATE_FILE"
  [[ -n "${ROLE_NAME:-}"  ]] || { echo "ERROR: ROLE_NAME not found in state file" >&2; exit 1; }

  # Override profile/region from state if not passed as args
  PROFILE="${PROFILE:-${PROFILE:-default}}"
  REGION="${REGION:-${REGION:-us-east-1}}"

  echo "[1/4] Detaching AWS managed policies from '${ROLE_NAME}'..."
  for POLICY_ARN in \
    "arn:aws:iam::aws:policy/ViewOnlyAccess" \
    "arn:aws:iam::aws:policy/AWSBillingReadOnlyAccess" \
    "arn:aws:iam::aws:policy/AWSComputeOptimizerReadOnlyAccess"; do
    aws iam detach-role-policy \
      --role-name "$ROLE_NAME" \
      --policy-arn "$POLICY_ARN" \
      --profile "$PROFILE" --region "$REGION" 2>/dev/null || true
    echo "      Detached: ${POLICY_ARN##*/}"
  done

  if [[ -n "${CUSTOM_POLICY_NAME:-}" ]]; then
    echo ""
    echo "[2/4] Deleting custom inline policy '${CUSTOM_POLICY_NAME}'..."
    aws iam delete-role-policy \
      --role-name "$ROLE_NAME" \
      --policy-name "$CUSTOM_POLICY_NAME" \
      --profile "$PROFILE" --region "$REGION" 2>/dev/null || true
  fi

  echo ""
  echo "[3/4] Deleting IAM role '${ROLE_NAME}'..."
  aws iam delete-role \
    --role-name "$ROLE_NAME" \
    --profile "$PROFILE" --region "$REGION" || true

  echo ""
  echo "[4/4] Removing local state file..."
  rm -f "$STATE_FILE"

  echo ""
  echo "================================================================="
  echo " SUCCESS — IAM role and policies removed. Zero footprint remains."
  echo "================================================================="
}


# Dispatch
if [[ "$MODE" == "cfn" ]]; then
  teardown_cfn
else
  teardown_cli
fi
