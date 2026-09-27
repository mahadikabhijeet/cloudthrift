# FinOps Audit: AWS Secure Access Setup

Welcome to the FinOps Audit secure onboarding repository. 

To provide you with a comprehensive analysis of your AWS architecture and billing efficiency, we require temporary, **strictly read-only** access to your AWS environment's metadata and billing dashboards. 

We believe in complete transparency. These scripts are open-source and heavily commented so your engineering and security teams can verify exactly what permissions are being granted before execution.

---

## 🔒 Security Guarantee: What We Can and Cannot Do

This process provisions a Cross-Account IAM Role secured by a unique `ExternalId`. 

**What we CAN do:**
* View resource metadata (e.g., instance types, regions, tags).
* View AWS Cost Explorer, Budgets, and Compute Optimizer recommendations.
* Read AWS Trusted Advisor checks.
* Read the raw billing data in your Cost and Usage Report (CUR) S3 bucket.

**What we CANNOT do:**
* We **cannot** read your customer data, application code, or database contents.
* We **cannot** download objects from any S3 buckets (except the specific billing bucket you designate).
* We **cannot** start, stop, modify, or delete any of your AWS resources. 

---

## 👤 For the Client: How to Grant Access

### Prerequisites
1. You must have the AWS CLI installed and authenticated with an IAM user/role that has permissions to create IAM Roles and attach policies (typically an Administrator account).
2. Bash environment (Linux, macOS, or WSL on Windows).

### Step 1: Clone and Configure
Clone this repository to your local machine and open the `setup_finops_access.sh` script in your preferred text editor. 

Update the `CUR_S3_BUCKET_NAME` variable on **Line 19** with the name of the S3 bucket where your Cost & Usage Reports are delivered. 
*(If you do not have CUR enabled, leave the variable as `""`)*.

### Step 2: Execute the Setup Script
Run the following commands in your terminal:
```bash
chmod +x setup_finops_access.sh
./setup_finops_access.sh
```


### Step 3: Handover
Upon successful completion, the script will output an IAM Role ARN (Amazon Resource Name) that looks like this: `arn:aws:iam::123456789012:role/FinOps-Audit-ReadOnly-Role`

Please securely send this ARN to your FinOps consultant.

---

## 🛠️ For the FinOps Team: Our Audit Process
*(Documented for client transparency)*

Once the client provides the IAM Role ARN, our team executes the following internal workflow:

1. **Secure Assume Role**: Our automated ingestion engine uses AWS STS (`sts:AssumeRole`) to temporarily assume the provided role. We securely pass the hardcoded `ExternalId` to prevent confused deputy attacks.
2. **Data Extraction**: Our read-only scripts query your AWS Cost Explorer API, Compute Optimizer API, and CUR S3 bucket to extract historical utilization and billing metrics.
3. **Architecture Mapping**: We map your resource metadata (without touching the data plane) to understand your footprint.
4. **Analysis & Report Generation**: The extracted metadata is fed into our proprietary FinOps modeling tools to identify waste, RI/SP coverage gaps, and architectural inefficiencies.
5. **Notification**: We notify the client that the data pull is complete and they may safely trigger the teardown process.

---

## 🧹 Teardown: How to Revoke Access
You retain complete control over our access to your environment. Once the audit data pull is complete (or at any time you choose), you can permanently revoke our access by running the included cleanup script.

Ensure the `.finops_audit_state` file generated during setup is still in the directory, then run:

```bash
chmod +x cleanup_finops_access.sh
./cleanup_finops_access.sh
```

This script will safely detach all policies and delete the cross-account IAM role, leaving zero footprint in your AWS environment.

For support or technical questions regarding this script, please reach out to your FinOps Consulting contact.