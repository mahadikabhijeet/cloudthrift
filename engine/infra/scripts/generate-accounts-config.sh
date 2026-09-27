#!/usr/bin/env bash
# ==============================================================================
# Generate accounts.json from AWS Organizations.
#
# Queries your payer/management account and writes a ready-to-use accounts.json.
# Run this once, then edit the file to disable accounts you don't want to audit.
#
# Usage:
#   bash infra/scripts/generate-accounts-config.sh [--profile <profile>] [--region <region>]
#
# Writes: infra/accounts.json  (gitignored — contains account IDs)
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
OUTPUT="${REPO_ROOT}/infra/accounts.json"

PROFILE="${AWS_PROFILE:-default}"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile) PROFILE="$2"; shift 2 ;;
    --region)  REGION="$2";  shift 2 ;;
    -h|--help) echo "Usage: $(basename "$0") [--profile <profile>] [--region <region>]"; exit 0 ;;
    *)         echo "Unknown option: $1"; exit 1 ;;
  esac
done

command -v jq &>/dev/null || { echo "ERROR: jq is required. Install: brew install jq / apt install jq" >&2; exit 1; }

echo "Querying AWS Organizations for member accounts..."
echo "(Using profile: ${PROFILE}, region: ${REGION})"
echo ""

PAYER_ID=$(aws sts get-caller-identity \
  --profile "$PROFILE" --region "$REGION" \
  --query Account --output text)

# List all active accounts in the organization
ACCOUNTS_RAW=$(aws organizations list-accounts \
  --profile "$PROFILE" --region "$REGION" \
  --query 'Accounts[?Status==`ACTIVE`]' \
  --output json 2>&1) || {
  echo ""
  echo "ERROR: Could not list Organizations accounts."
  echo ""
  echo "Possible causes:"
  echo "  1. Your credentials are not from the management/payer account"
  echo "  2. AWS Organizations is not enabled for this account"
  echo "  3. Your IAM role lacks organizations:ListAccounts permission"
  echo ""
  echo "If you don't use Organizations, create accounts.json manually"
  echo "using infra/accounts.example.json as a template."
  exit 1
}

COUNT=$(echo "$ACCOUNTS_RAW" | jq 'length')
echo "Found ${COUNT} active accounts."

# Generate a random ExternalId
if command -v openssl &>/dev/null; then
  EXT_ID=$(openssl rand -hex 16)
else
  EXT_ID="finops-$(date +%s)-${RANDOM}"
fi

# Build accounts array — infer env from account name (customize this logic as needed)
ACCOUNTS_JSON=$(echo "$ACCOUNTS_RAW" | jq -c --arg payer "$PAYER_ID" '[
  .[] |
  . as $acct |
  # Skip the payer/management account itself
  select(.Id != $payer) |
  {
    id:      .Id,
    name:    .Name,
    email:   .Email,
    # Infer environment from common suffixes in account name
    env: (
      if (.Name | test("prod|prd|production"; "i")) then "prod"
      elif (.Name | test("stg|staging|stage"; "i")) then "staging"
      elif (.Name | test("dev|development"; "i")) then "dev"
      elif (.Name | test("sandbox|sbx"; "i")) then "sandbox"
      elif (.Name | test("test|tst|qa"; "i")) then "test"
      else "unknown"
      end
    ),
    region:  "us-east-1",
    enabled: true
  }
]')

# Write the config file
cat > "$OUTPUT" <<EOF
{
  "payer_account_id": "${PAYER_ID}",
  "external_id": "${EXT_ID}",
  "role_name": "FinOps-Audit-ReadOnly-Role",
  "default_region": "${REGION}",
  "accounts": $(echo "$ACCOUNTS_JSON" | jq '.')
}
EOF

chmod 600 "$OUTPUT"  # Contains account IDs and ExternalId

echo ""
echo "=================================================="
echo " accounts.json written to: ${OUTPUT}"
echo " Accounts found  : ${COUNT}"
echo " Payer account   : ${PAYER_ID} (excluded from audit list)"
echo " External ID     : ****${EXT_ID: -4}  (auto-generated)"
echo "=================================================="
echo ""
echo "Next steps:"
echo "  1. Review ${OUTPUT} — disable any accounts you don't want to audit"
echo "     by setting \"enabled\": false"
echo "  2. Deploy the audit role to all accounts:"
echo "     bash infra/scripts/multi-account-setup.sh --env prod  (prod only)"
echo "     bash infra/scripts/multi-account-setup.sh              (all accounts)"
echo "  3. Run the audit:"
echo "     python src/run_all_accounts.py --config infra/accounts.json"
echo ""
echo "IMPORTANT: accounts.json is gitignored. Do not commit it."
