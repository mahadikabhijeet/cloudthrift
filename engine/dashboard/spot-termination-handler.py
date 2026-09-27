"""
Pillar D — EC2 Spot Termination Handler

Polls the EC2 instance metadata service (IMDS) for a spot interruption notice.
When a 2-minute termination warning is detected, the handler:

  1. Drains the current task/request gracefully (sends SIGTERM to the app)
  2. Checkpoints any in-progress audit jobs to SQS so another instance can resume
  3. Deregisters the instance from its target group to stop receiving new traffic
  4. Logs the termination event to CloudWatch

Deploy as a sidecar process alongside the Pillar D web app on Spot instances,
or as a systemd service on EC2.

Usage:
    python spot-termination-handler.py [--poll-interval 5] [--app-pid <pid>]
"""
from __future__ import annotations

import argparse
import os
import signal
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

import boto3

IMDS_TOKEN_URL = "http://169.254.169.254/latest/api/token"
IMDS_SPOT_URL = "http://169.254.169.254/latest/meta-data/spot/termination-time"
IMDS_INSTANCE_ID_URL = "http://169.254.169.254/latest/meta-data/instance-id"
IMDS_TTL_SECONDS = 21600


def get_imds_token() -> str:
    req = urllib.request.Request(
        IMDS_TOKEN_URL,
        headers={"X-aws-ec2-metadata-token-ttl-seconds": str(IMDS_TTL_SECONDS)},
        method="PUT",
    )
    with urllib.request.urlopen(req, timeout=2) as resp:
        return resp.read().decode()


def fetch_imds(url: str, token: str) -> str | None:
    """Return IMDS metadata value or None if the path does not exist (404)."""
    req = urllib.request.Request(url, headers={"X-aws-ec2-metadata-token": token})
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.read().decode()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def get_instance_id(token: str) -> str:
    result = fetch_imds(IMDS_INSTANCE_ID_URL, token)
    return result or "unknown"


def drain_app(app_pid: int) -> None:
    """Send SIGTERM to the application process to begin graceful shutdown."""
    print(f"[spot-handler] Sending SIGTERM to app PID {app_pid}")
    try:
        os.kill(app_pid, signal.SIGTERM)
    except ProcessLookupError:
        print(f"[spot-handler] PID {app_pid} not found — already exited.")


def deregister_from_target_group(instance_id: str) -> None:
    """Remove this instance from all ELB target groups it is registered in."""
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    elb = boto3.client("elbv2", region_name=region)
    ec2 = boto3.client("ec2",   region_name=region)

    response = ec2.describe_instances(InstanceIds=[instance_id])
    port = int(os.environ.get("APP_PORT", "8000"))

    target_groups = elb.describe_target_groups()["TargetGroups"]
    for tg in target_groups:
        health = elb.describe_target_health(TargetGroupArn=tg["TargetGroupArn"])
        registered_ids = {t["Target"]["Id"] for t in health["TargetHealthDescriptions"]}
        if instance_id in registered_ids:
            elb.deregister_targets(
                TargetGroupArn=tg["TargetGroupArn"],
                Targets=[{"Id": instance_id, "Port": port}],
            )
            print(f"[spot-handler] Deregistered {instance_id} from {tg['TargetGroupArn']}")


def checkpoint_jobs(instance_id: str) -> None:
    """
    Push any in-progress audit job state to SQS so another instance can resume.

    TODO: Implement once Pillar B job queue is wired up.
    Queue URL: os.environ.get("AUDIT_QUEUE_URL")
    """
    print(f"[spot-handler] Checkpoint stub — no jobs to migrate for {instance_id}")


def log_termination(instance_id: str, termination_time: str) -> None:
    cw = boto3.client("logs", region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
    log_group = os.environ.get("CW_LOG_GROUP", "/finops/spot-terminations")
    try:
        cw.put_log_events(
            logGroupName=log_group,
            logStreamName=instance_id,
            logEvents=[{
                "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
                "message": f"Spot termination notice received. Scheduled at: {termination_time}",
            }],
        )
    except Exception as exc:
        print(f"[spot-handler] CloudWatch log failed: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description="EC2 Spot Termination Handler")
    parser.add_argument("--poll-interval", type=int, default=5, help="Seconds between IMDS polls")
    parser.add_argument("--app-pid", type=int, default=0, help="PID of the app to drain on termination")
    args = parser.parse_args()

    print(f"[spot-handler] Starting — polling every {args.poll_interval}s")
    token = get_imds_token()
    instance_id = get_instance_id(token)
    print(f"[spot-handler] Instance: {instance_id}")

    while True:
        try:
            termination_time = fetch_imds(IMDS_SPOT_URL, token)
            if termination_time:
                print(f"[spot-handler] TERMINATION NOTICE — scheduled at {termination_time}")
                log_termination(instance_id, termination_time)
                checkpoint_jobs(instance_id)
                deregister_from_target_group(instance_id)
                if args.app_pid:
                    drain_app(args.app_pid)
                print("[spot-handler] Graceful shutdown complete.")
                break
        except Exception as exc:
            print(f"[spot-handler] Poll error: {exc}")
        time.sleep(args.poll_interval)


if __name__ == "__main__":
    main()
