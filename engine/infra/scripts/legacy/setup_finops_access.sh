#!/bin/bash

# ==============================================================================
# FinOps Audit - Secure IAM Role Setup Script
# Description: This script creates a strictly read-only cross-account IAM role 
#              to allow our FinOps team to analyze your AWS environment's 
#              metadata and billing dashboards safely.
# ==============================================================================

# Exit immediately if a command exits with a non-zero status.
set -e

# ------------------------------------------------------------------------------
# CONFIGURATION VARIABLES
# Client: Please review and update the variables below before running.
# ------------------------------------------------------------------------------

# The AWS Account ID of the FinOps Consulting Team (Our Account)
FINOPS_ACCOUNT_ID="123456789012" 

# The name of the IAM role that will be created in your account
ROLE_NAME="FinOps-Audit-ReadOnly-Role"

# The name of the S3 bucket where your Cost & Usage Reports (CUR) are stored
# Leave blank ("") if you do not have CUR enabled
CUR_S3_BUCKET_NAME="your-cur-billing-bucket-name"

# The name of the custom inline policy we will attach to the role
CUSTOM_POLICY_NAME="FinOps-Custom-Audit-Policy"

# State file to track resources for easy cleanup
STATE_FILE=".finops_audit_state"

# ------------------------------------------------------------------------------
# SCRIPT EXECUTION
# ------------------------------------------------------------------------------

echo "Starting FinOps IAM Role Setup..."

# Step 1: Create the Trust Relationship Policy Document
# This JSON file dictates WHO can assume this role. In this case, only the 
# specific FinOps team's AWS account is allowed.
echo "Creating trust policy document..."
cat <<EOF > trust-policy.json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::${FINOPS_ACCOUNT_ID}:root"
      },
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": {
          "sts:ExternalId": "FinOpsAudit-Secure-ExtID-2026"
        }
      }
    }
  ]
}
EOF

# Step 2: Create the IAM Role
# We use the AWS CLI to create the role using the trust policy generated above.
echo "Creating IAM Role: ${ROLE_NAME}..."
aws iam create-role \
    --role-name "${ROLE_NAME}" \
    --assume-role-policy-document file://trust-policy.json \
    --description "Read-only role for FinOps billing and architecture audit"

# Save the role name to our state file for future cleanup
echo "ROLE_NAME=${ROLE_NAME}" > "${STATE_FILE}"

# Step 3: Attach AWS Managed Read-Only Policies
# These are AWS-maintained policies that ensure strict read-only access.
echo "Attaching AWS Managed Policies..."

# ViewOnlyAccess: Allows viewing of resource metadata (does NOT allow reading data inside S3/RDS)
aws iam attach-role-policy \
    --role-name "${ROLE_NAME}" \
    --policy-arn "arn:aws:iam::aws:policy/ViewOnlyAccess"

# AWSBillingReadOnlyAccess: Allows viewing of Cost Explorer, Budgets, and Billing consoles
aws iam attach-role-policy \
    --role-name "${ROLE_NAME}" \
    --policy-arn "arn:aws:iam::aws:policy/AWSBillingReadOnlyAccess"

# AWSComputeOptimizerReadOnlyAccess: Allows viewing of machine-learning powered sizing recommendations
aws iam attach-role-policy \
    --role-name "${ROLE_NAME}" \
    --policy-arn "arn:aws:iam::aws:policy/AWSComputeOptimizerReadOnlyAccess"

# Step 4: Create and Attach Custom Inline Policy (Trusted Advisor & CUR S3 Bucket)
# AWS Managed policies don't cover Trusted Advisor checks or the specific S3 bucket holding CUR data.
echo "Creating custom inline policy for Trusted Advisor and CUR bucket..."
cat <<EOF > custom-policy.json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "TrustedAdvisorReadOnly",
            "Effect": "Allow",
            "Action": [
                "support:DescribeTrustedAdvisorChecks",
                "support:DescribeTrustedAdvisorCheckResult"
            ],
            "Resource": "*"
        }
EOF

# If the client provided a CUR bucket name, append S3 read permissions specifically for that bucket
if [ -n "${CUR_S3_BUCKET_NAME}" ] && [ "${CUR_S3_BUCKET_NAME}" != "your-cur-billing-bucket-name" ]; then
    echo "Adding S3 permissions for CUR bucket: ${CUR_S3_BUCKET_NAME}"
    cat <<EOF >> custom-policy.json
        ,{
            "Sid": "CURBucketReadOnly",
            "Effect": "Allow",
            "Action": [
                "s3:ListBucket",
                "s3:GetObject"
            ],
            "Resource": [
                "arn:aws:s3:::${CUR_S3_BUCKET_NAME}",
                "arn:aws:s3:::${CUR_S3_BUCKET_NAME}/*"
            ]
        }
EOF
fi

# Close the JSON structure
cat <<EOF >> custom-policy.json
    ]
}
EOF

# Attach the inline policy to the role
echo "Attaching custom inline policy to role..."
aws iam put-role-policy \
    --role-name "${ROLE_NAME}" \
    --policy-name "${CUSTOM_POLICY_NAME}" \
    --policy-document file://custom-policy.json

# Save the custom policy name to the state file
echo "CUSTOM_POLICY_NAME=${CUSTOM_POLICY_NAME}" >> "${STATE_FILE}"

# Step 5: Clean up local temporary JSON files
echo "Cleaning up local temporary files..."
rm trust-policy.json custom-policy.json

echo "====================================================================="
echo "✅ SUCCESS! The FinOps Audit Role has been securely created."
echo "Please provide the following Role ARN to your FinOps team:"
echo "arn:aws:iam::$(aws sts get-caller-identity --query Account --output text):role/${ROLE_NAME}"
echo "====================================================================="