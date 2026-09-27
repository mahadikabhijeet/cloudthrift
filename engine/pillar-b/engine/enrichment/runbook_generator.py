"""
Attach actionable CLI runbook steps to findings for PDF and dashboard delivery.
"""
from __future__ import annotations

from shared.findings_schema import Finding


def attach_runbooks(findings: list[Finding]) -> list[Finding]:
    return [f.model_copy(update={"metadata": {**f.metadata, **(_runbook_for(f) or {})}}) for f in findings]


def _runbook_for(finding: Finding) -> dict | None:
    fid = finding.id
    region = finding.region
    resource = finding.resource_id
    steps: list[str] = []

    if fid.startswith("HYGIENE-EBS-") or "unattached" in finding.title.lower():
        steps = [
            f"aws ec2 create-snapshot --volume-id {resource} --description 'Pre-delete backup' --region {region}",
            f"aws ec2 delete-volume --volume-id {resource} --region {region}",
        ]
    elif fid.startswith("HYGIENE-GP2-"):
        steps = [
            f"aws ec2 modify-volume --volume-type gp3 --volume-id {resource} --region {region}",
            "# Zero-downtime while attached; monitor modify-volume progress in console",
        ]
    elif fid.startswith("HYGIENE-EIP-"):
        steps = [
            f"aws ec2 release-address --allocation-id {resource} --region {region}",
        ]
    elif fid.startswith("HYGIENE-ELB-"):
        steps = [
            f"aws elbv2 describe-target-health --target-group-arn <tg-arn> --region {region}",
            f"aws elbv2 delete-load-balancer --load-balancer-arn {resource} --region {region}",
        ]
    elif fid.startswith("HYGIENE-ECR-"):
        repo = resource
        steps = [
            f"aws ecr put-lifecycle-policy --repository-name {repo} --region {region} "
            "--lifecycle-policy-text file://ecr-lifecycle.json",
        ]
    elif fid.startswith("HYGIENE-SNAP-"):
        steps = [
            f"aws ec2 delete-snapshot --snapshot-id {resource} --region {region}",
        ]
    elif fid.startswith("NETWORK-NAT-IDLE-"):
        steps = [
            f"aws ec2 describe-route-tables --filters Name=route.nat-gateway-id,Values={resource} --region {region}",
            f"aws ec2 delete-nat-gateway --nat-gateway-id {resource} --region {region}",
        ]
    elif fid.startswith("NETWORK-VPCE-IDLE-"):
        steps = [
            f"aws ec2 delete-vpc-endpoints --vpc-endpoint-ids {resource} --region {region}",
        ]
    elif fid.startswith("STORAGE-S3-MULTIPART-"):
        bucket = resource
        steps = [
            f"aws s3api put-bucket-lifecycle-configuration --bucket {bucket} "
            "--lifecycle-configuration file://abort-multipart.json",
            "# abort-multipart.json: AbortIncompleteMultipartUpload DaysAfterInitiation=7",
        ]
    elif fid.startswith("STORAGE-S3-TIERING-") or fid.startswith("STORAGE-S3-VERSIONING-"):
        bucket = resource
        steps = [
            f"aws s3api put-bucket-lifecycle-configuration --bucket {bucket} "
            "--lifecycle-configuration file://lifecycle.json",
            "aws s3api put-bucket-intelligent-tiering-configuration --bucket {bucket} ...".format(bucket=bucket),
        ]
    elif fid.startswith("OBS-LOGS-"):
        log_group = resource
        steps = [
            f"aws logs put-retention-policy --log-group-name '{log_group}' "
            f"--retention-in-days 30 --region {region}",
        ]
    elif fid.startswith("SP-RI-EXPIRE-"):
        steps = [
            "aws ec2 describe-reserved-instances --filters Name=state,Values=active",
            "# Renew via Console → Reserved Instances → Purchase, or migrate to Compute Savings Plan",
        ]
    elif fid.startswith("CO-EC2-") or fid.startswith("SP-RIGHTSIZE-"):
        steps = [
            f"aws cloudwatch get-metric-statistics --namespace AWS/EC2 --metric-name CPUUtilization "
            f"--dimensions Name=InstanceId,Value={resource} --period 86400 --statistics Average "
            f"--start-time $(date -u -d '14 days ago' +%Y-%m-%dT%H:%M:%S) "
            f"--end-time $(date -u +%Y-%m-%dT%H:%M:%S) --region {region}",
            "# Validate 14-day CPU < 20% before rightsizing or terminating",
        ]
    elif fid.startswith("CO-RDS-") or "rds" in finding.service.lower():
        steps = [
            f"aws rds describe-db-instances --db-instance-identifier {resource} --region {region}",
            "# Apply rightsizing during a maintenance window after validating connections/CPU",
        ]
    elif fid.startswith("CO-LAMBDA-"):
        steps = [
            f"aws lambda get-function-configuration --function-name {resource} --region {region}",
            "# Test at recommended memory in staging before updating production alias",
        ]
    elif finding.metadata.get("source") == "trusted_advisor":
        steps = [
            f"# Trusted Advisor check: {finding.metadata.get('ta_check_name', 'cost optimization')}",
            finding.recommendation,
        ]

    if not steps:
        steps = [finding.recommendation]

    return {
        "runbook": steps,
        "runbook_summary": steps[0][:120],
    }
