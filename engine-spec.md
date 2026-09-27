# CloudThrift FinOps Engine — Open Source Specification

## The Vision
CloudThrift is an automated, read-only AWS audit engine. It scans cloud environments across 5 key pillars to identify cost leaks, idle resources, and over-provisioned infrastructure.

By open-sourcing the core engine, we allow the community to continuously add new AWS/GCP checks, while we monetize through enterprise deployment consulting, premium hosted dashboards, and bespoke FinOps audits.

## Core Architecture
*   **Language:** Python 3.11+
*   **Cloud SDK:** Boto3 (AWS)
*   **Execution:** CLI tool (runs locally or in CI/CD)
*   **Security:** Strictly Read-Only IAM cross-account role (`arn:aws:iam::aws:policy/SecurityAudit` + `arn:aws:iam::aws:policy/ViewOnlyAccess`).
*   **Output:** JSON report mapped to specific resource ARNs with estimated monthly savings.

## Modularity (The Contributor Model)
The engine is built around isolated "Check Modules" so open-source contributors can easily add new rules without touching the core framework.

### Phase 1 Modules (MVP)
1.  **Orphaned EBS Volumes:** Detect unattached (`available`) EBS volumes.
2.  **Idle EC2 Instances:** Detect instances with <5% CPU utilization over 7 days.
3.  **Unassociated Elastic IPs:** Detect EIPs not attached to running instances.
4.  **Legacy RDS Instances:** Detect previous-generation instance types (e.g., `db.t2`).
5.  **S3 Lifecycle Missing:** Detect large buckets without transition rules to Infrequent Access.
