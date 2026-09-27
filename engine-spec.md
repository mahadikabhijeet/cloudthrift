# CloudThrift FinOps Engine — Open Source Specification

## The Vision
CloudThrift is an automated, read-only AWS audit engine. It scans cloud environments to identify cost leaks, idle resources, and over-provisioned infrastructure. 
**GTM Strategy:** We give away the detection engine for free (bypassing CTO security friction). We monetize through "Remediation-as-a-Service"—charging to actually execute the architectural fixes.

## Core Architecture
*   **Language:** Python 3.11+ (CLI tool)
*   **Cloud SDK:** Boto3 (AWS)
*   **Execution:** Runs locally via `~/.aws/credentials` (Zero-friction onboarding).
*   **Security:** Strictly Read-Only IAM (`SecurityAudit` + `ViewOnlyAccess`). **Jules AI Constraint:** The AI agent is strictly forbidden from writing rules that modify state.
*   **Output:** JSON report mapped to specific resource ARNs with estimated monthly savings. *Must include a call-to-action link to book Remediation-as-a-Service.*

## ⚠️ Enterprise Constraints (Architect Mandates)
Before writing any modular scanners, the core framework must implement:
1.  **Central Data Fetcher (No N+1 API Abuse):** Do not let individual modules query AWS. The core engine must fetch all EC2/S3 resources once, cache them in memory, and pass them to the rules.
2.  **Concurrency & Throttle Limits:** Use `aioboto3` or ThreadPoolExecutors. Configure exponential backoff (`max_attempts: 10`) to prevent `ThrottlingException` on large fleets.
3.  **Explicit Account/Region Loops:** The engine must dynamically query `ec2:DescribeRegions` and loop over them.

## Modularity (The Contributor Model)
Once the core fetcher is built, implement the following rule modules:
1.  **Orphaned EBS Volumes:** Detect unattached (`available`) EBS volumes.
2.  **Idle EC2 Instances:** Detect instances with <5% CPU utilization over 7 days.
3.  **S3 Lifecycle Missing:** Use CloudWatch `BucketSizeBytes` metric (NOT S3 APIs) to find large buckets missing transitions.
