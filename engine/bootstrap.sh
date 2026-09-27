#!/usr/bin/env bash
# ==============================================================================
# FinOps Platform — Bootstrap Script
#
# Sets up the full platform on a new machine (personal or company laptop).
# Safe to re-run — skips steps that are already done.
#
# Usage:
#   git clone <repo-url>
#   cd finops-platform
#   bash bootstrap.sh
# ==============================================================================
set -euo pipefail

RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'; BOLD='\033[1m'; NC='\033[0m'

ok()   { echo -e "  ${GREEN}✓${NC}  $*"; }
warn() { echo -e "  ${YELLOW}!${NC}  $*"; }
fail() { echo -e "  ${RED}✗${NC}  $*"; }
step() { echo -e "\n${BOLD}── $* ${NC}"; }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo -e "${BOLD}FinOps Platform — Bootstrap${NC}"
echo "=================================================="
echo " Repo root: ${REPO_ROOT}"
echo " OS:        $(uname -s)"
echo "=================================================="

# ==============================================================================
# 1. System dependencies
# ==============================================================================
step "Checking system dependencies"

# Python 3.11+
if command -v python3 &>/dev/null; then
  PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
  PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
  PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
  if [[ "$PY_MAJOR" -ge 3 && "$PY_MINOR" -ge 11 ]]; then
    ok "Python ${PY_VERSION}"
  else
    fail "Python ${PY_VERSION} found — need 3.11 or newer"
    echo "     Install: https://www.python.org/downloads/"
    exit 1
  fi
else
  fail "Python 3 not found"
  echo "     Install: https://www.python.org/downloads/"
  exit 1
fi

# AWS CLI
if command -v aws &>/dev/null; then
  ok "AWS CLI $(aws --version 2>&1 | awk '{print $1}')"
else
  warn "AWS CLI not found"
  echo "     Install: https://aws.amazon.com/cli/"
  echo "     macOS:   brew install awscli"
  echo "     Linux:   curl 'https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip' -o awscliv2.zip && unzip awscliv2.zip && sudo ./aws/install"
fi

# jq (optional but needed for multi-account setup)
if command -v jq &>/dev/null; then
  ok "jq $(jq --version)"
else
  warn "jq not found (needed for multi-account setup)"
  echo "     macOS: brew install jq"
  echo "     Linux: sudo apt install jq  OR  sudo yum install jq"
fi

# ==============================================================================
# 2. Python virtual environment
# ==============================================================================
step "Python virtual environment"

VENV_DIR="${REPO_ROOT}/.venv"
if [[ -d "$VENV_DIR" ]]; then
  ok "Virtual env already exists at .venv"
else
  python3 -m venv "$VENV_DIR"
  ok "Created .venv"
fi

# Activate
# shellcheck source=/dev/null
source "${VENV_DIR}/bin/activate"

pip install --upgrade pip --quiet

step "Installing Python dependencies"

pip install -r "${REPO_ROOT}/pillar-b/requirements.txt" --quiet
ok "pillar-b (audit engine)"

pip install -r "${REPO_ROOT}/pillar-d/requirements.txt" --quiet
ok "pillar-d (dashboard)"

pip install -r "${REPO_ROOT}/pillar-c/requirements.txt" --quiet 2>/dev/null && ok "pillar-c (lead pipeline)" || warn "pillar-c/requirements.txt not found — skipping"

# ==============================================================================
# 3. Environment file
# ==============================================================================
step "Environment configuration"

ENV_FILE="${REPO_ROOT}/.env"
if [[ -f "$ENV_FILE" ]]; then
  ok ".env already exists"
else
  cp "${REPO_ROOT}/.env.example" "$ENV_FILE"
  warn ".env created from template — open it and fill in your API keys:"
  echo ""
  echo "     ${ENV_FILE}"
  echo ""
  echo "     Required keys:"
  echo "       ANTHROPIC_API_KEY     — console.anthropic.com/account/keys"
  echo "       GMAIL_CREDENTIALS_JSON — see INSTRUCTIONS.md § Gmail OAuth"
fi

# ==============================================================================
# 4. Accounts config
# ==============================================================================
step "Accounts configuration (accounts.json)"

ACCOUNTS_FILE="${REPO_ROOT}/pillar-a/accounts.json"
if [[ -f "$ACCOUNTS_FILE" ]]; then
  ok "accounts.json already exists"
else
  cp "${REPO_ROOT}/pillar-a/accounts.example.json" "$ACCOUNTS_FILE"
  chmod 600 "$ACCOUNTS_FILE"
  warn "accounts.json created from template — fill in your role ARNs and external IDs:"
  echo ""
  echo "     ${ACCOUNTS_FILE}"
  echo ""
  echo "     For each account, set:"
  echo "       role_arn:    arn:aws:iam::ACCOUNT_ID:role/ExistingRoleName"
  echo "       external_id: the ExternalId configured in that role's trust policy"
fi

# ==============================================================================
# 5. Data directory for dashboard
# ==============================================================================
step "Dashboard data directory"
mkdir -p "${REPO_ROOT}/pillar-d/data"
ok "pillar-d/data/ ready"

# ==============================================================================
# 6. Smoke test
# ==============================================================================
step "Smoke test (mock audit)"

cd "${REPO_ROOT}"
python pillar-b/engine/main.py --mock --account-id bootstrap-test --output json --output-dir /tmp/finops-bootstrap 2>&1 | grep -E 'findings|savings|Done|ERROR' || true

if ls /tmp/finops-bootstrap/dashboard_bootstrap-test_*.json &>/dev/null 2>&1; then
  cp /tmp/finops-bootstrap/dashboard_bootstrap-test_*.json "${REPO_ROOT}/pillar-d/data/"
  ok "Mock audit succeeded — report in pillar-d/data/"
else
  warn "Smoke test did not produce output — check errors above"
fi

# ==============================================================================
# Summary
# ==============================================================================
echo ""
echo "=================================================="
echo -e "${BOLD} Bootstrap complete${NC}"
echo "=================================================="
echo ""
echo " Activate the venv in new terminal sessions:"
echo "   source .venv/bin/activate"
echo ""
echo " Start the dashboard:"
echo "   cd pillar-d"
echo "   DATA_DIR=data python -m uvicorn app.main:app --port 8000"
echo ""
echo " Run audit against your accounts:"
echo "   # Fill in pillar-a/accounts.json first"
echo "   python pillar-b/run_all_accounts.py --dry-run"
echo "   python pillar-b/run_all_accounts.py --env prod --workers 4"
echo ""
echo " Read the full guide:"
echo "   cat INSTRUCTIONS.md"
echo ""
