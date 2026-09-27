#!/bin/bash

# ==============================================================================
# FinOps Audit - Secure IAM Role Cleanup Script
# Description: This script reads the local state file and removes all policies 
#              and the IAM role created during the FinOps audit setup.
# ==============================================================================

# Exit immediately if a command exits with a non-zero status.
set -e

STATE_FILE=".finops_audit_state"

echo "Starting FinOps IAM Role Cleanup..."

# Step 1: Verify the state file exists
if [ ! -f "${STATE_FILE}" ]; then
    echo "Error: State file '${STATE_FILE}' not found."
    echo "Could not determine which resources to delete. If you manually deleted the role, you can ignore this."
    exit 1
fi

# Step 2: Load the variables from the state file
source "${STATE_FILE}"

# Ensure ROLE_NAME was successfully loaded
if [ -z "${ROLE_NAME}" ]; then
    echo "Error: ROLE_NAME not found in state file."
    exit 1
fi

echo "Found Role to delete: ${ROLE_NAME}"

# Step 3: Detach Managed Policies
# We must detach all policies before AWS allows us to delete the role itself.
echo "Detaching AWS Managed Policies..."

# We use '|| true' to prevent the script from failing if the policy was already manually detached
aws iam detach-role-policy --role-name "${ROLE_NAME}" --policy-arn "arn:aws:iam::aws:policy/ViewOnlyAccess" || true
aws iam detach-role-policy --role-name "${ROLE_NAME}" --policy-arn "arn:aws:iam::aws:policy/AWSBillingReadOnlyAccess" || true
aws iam detach-role-policy --role-name "${ROLE_NAME}" --policy-arn "arn:aws:iam::aws:policy/AWSComputeOptimizerReadOnlyAccess" || true

# Step 4: Delete the Custom Inline Policy
if [ -n "${CUSTOM_POLICY_NAME}" ]; then
    echo "Deleting custom inline policy: ${CUSTOM_POLICY_NAME}..."
    aws iam delete-role-policy --role-name "${ROLE_NAME}" --policy-name "${CUSTOM_POLICY_NAME}" || true
fi

# Step 5: Delete the IAM Role
echo "Deleting IAM Role: ${ROLE_NAME}..."
aws iam delete-role --role-name "${ROLE_NAME}" || true

# Step 6: Remove the state file
echo "Removing local state file..."
rm "${STATE_FILE}"

echo "====================================================================="
echo "✅ SUCCESS! All FinOps audit resources have been completely removed."
echo "====================================================================="