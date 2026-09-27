# CloudThrift FinOps Engine — Open Source Specification

## The Vision
CloudThrift is an automated, read-only AWS audit engine. It scans cloud environments to identify cost leaks, idle resources, and over-provisioned infrastructure. 
**GTM Strategy:** We give away the detection engine for free (bypassing CTO security friction). We monetize through "Remediation-as-a-Service"—charging to actually execute the architectural fixes.

## Core Architecture
*   **Language:** Python 3.11+ (CLI tool)
*   **Cloud SDK:** Boto3 (AWS)
*   **Execution:** Runs locally via `~/.aws/credentials` (Zero-friction onboarding).
*   **Security:** Strictly Read-Only IAM (`SecurityAudit` + `ViewOnlyAccess`). 
*   **AI Integration (MCP):** The system integrates with AI via the official Python MCP SDK. The engine/MCP is 100% read-only. AI agents are strictly limited to generating Infrastructure-as-Code (Terraform/CLI scripts) from the read-only JSON reports.
*   **Output:** JSON report mapped to specific resource ARNs with estimated monthly savings. *Must include a call-to-action link to book Remediation-as-a-Service.*

## ⚠️ Enterprise Constraints (Architect Mandates)
Before writing any modular scanners, the core framework must implement:
1.  **Iterative Data Fetcher (Prevent OOM):** Do not load enterprise fleets into memory. Use Python generators or a lightweight local SQLite database to handle state and prevent Out-Of-Memory crashes.
2.  **Concurrency & Throttle Limits:** Use `ThreadPoolExecutors` for synchronous CLI performance. Configure explicit exponential backoff (`botocore.config.Config(retries={'max_attempts': 10})`) to prevent `ThrottlingException` on large fleets.
3.  **Explicit Account/Region Loops:** The engine must dynamically query `ec2:DescribeRegions` and loop over them.

## Modularity (The Contributor Model)
Once the core fetcher is built, implement the following rule modules:
1.  **Orphaned EBS Volumes:** Detect unattached (`available`) EBS volumes.
2.  **Idle EC2 Instances:** Detect instances with <5% CPU utilization AND <5% Network I/O over 7 days (to prevent false-positives on memory/network bound workloads).
3.  **S3 Lifecycle Missing:** Use `s3:GetBucketLifecycleConfiguration` to find buckets missing transition rules, and correlate with CloudWatch `BucketSizeBytes` for potential savings estimation.
