#!/usr/bin/env bash
# ==============================================================================
# Self-Audit Teardown — removes the IAM role created by self-audit-setup.sh
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_FILE="${SCRIPT_DIR}/.self-audit-state"

if [[ ! -f "$STATE_FILE" ]]; then
  echo "ERROR: State file not found: ${STATE_FILE}"
  echo "Nothing to tear down, or setup was never run."
  exit 1
fi

# shellcheck source=/dev/null
source "$STATE_FILE"

echo "=================================================="
echo " FinOps Platform — Self-Audit Teardown"
echo "=================================================="
echo " Account ID  : ${ACCOUNT_ID}"
echo " Role Name   : ${ROLE_NAME}"
echo " Mode        : ${MODE}"
echo " Region      : ${REGION}"
echo " Profile     : ${PROFILE}"
echo "=================================================="
echo ""
read -r -p "Remove the self-audit IAM role? [y/N] " CONFIRM
[[ "${CONFIRM,,}" == "y" ]] || { echo "Aborted."; exit 0; }

if [[ "$MODE" == "cfn" ]]; then
  echo "Deleting CloudFormation stack '${STACK_NAME}'..."
  aws cloudformation delete-stack \
    --stack-name "$STACK_NAME" \
    --region "$REGION" --profile "$PROFILE"
  echo "Waiting for deletion to complete..."
  aws cloudformation wait stack-delete-complete \
    --stack-name "$STACK_NAME" \
    --region "$REGION" --profile "$PROFILE"
  echo "Stack deleted."
else
  echo "Detaching managed policies from role '${ROLE_NAME}'..."
  ATTACHED=$(aws iam list-attached-role-policies \
    --role-name "$ROLE_NAME" --profile "$PROFILE" \
    --query 'AttachedPolicies[].PolicyArn' --output text 2>/dev/null || true)
  for ARN in $ATTACHED; do
    aws iam detach-role-policy \
      --role-name "$ROLE_NAME" --policy-arn "$ARN" --profile "$PROFILE"
    echo "  Detached: ${ARN}"
  done

  echo "Removing inline policies..."
  INLINE=$(aws iam list-role-policies \
    --role-name "$ROLE_NAME" --profile "$PROFILE" \
    --query 'PolicyNames[]' --output text 2>/dev/null || true)
  for NAME in $INLINE; do
    aws iam delete-role-policy \
      --role-name "$ROLE_NAME" --policy-name "$NAME" --profile "$PROFILE"
    echo "  Deleted inline policy: ${NAME}"
  done

  echo "Deleting role '${ROLE_NAME}'..."
  aws iam delete-role --role-name "$ROLE_NAME" --profile "$PROFILE"
fi

rm -f "$STATE_FILE"
echo ""
echo "Done. Role removed and state file deleted."
