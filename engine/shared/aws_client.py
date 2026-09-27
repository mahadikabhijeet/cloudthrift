"""
shared/aws_client.py — boto3 session factory.

Supports two auth paths:
  1. Profile-based (company SSO): pass profile=, no role_arn needed.
     boto3 uses the named AWS CLI profile directly — no STS call.
  2. Role assumption (client/cross-account): pass role_arn=.
     ExternalId is included only when external_id is non-empty.
     Optionally pass profile= to select which base credentials do the assuming.
"""
from __future__ import annotations

import re

import boto3
from botocore.exceptions import ClientError


def get_session(
    role_arn: str = "",
    external_id: str = "",
    region: str = "us-east-1",
    profile: str = "",
    session_name: str = "finops-platform-audit",
) -> boto3.Session:
    """Return an authenticated boto3 Session for the target account.

    Auth is resolved in this order:
      - profile + no role_arn → direct profile session (company SSO workflow)
      - role_arn              → STS AssumeRole (client workflow)
        - external_id present → included in AssumeRole call
        - profile present     → use that profile's credentials to call STS

    Raises ValueError if neither profile nor role_arn is provided.
    """
    if not role_arn:
        if not profile:
            raise ValueError("Either profile or role_arn must be provided")
        return boto3.Session(profile_name=profile, region_name=region)

    # Role assumption path
    base = boto3.Session(profile_name=profile) if profile else boto3.Session()
    sts = base.client("sts")

    assume_kwargs: dict = {
        "RoleArn": role_arn,
        "RoleSessionName": session_name,
        "DurationSeconds": 3600,
    }
    if external_id:
        assume_kwargs["ExternalId"] = external_id

    try:
        creds = sts.assume_role(**assume_kwargs)["Credentials"]
    except ClientError as exc:
        raise _translate_auth_error(exc, profile=profile) from exc

    return boto3.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
        region_name=region,
    )


def validate_session(session: boto3.Session, profile: str = "") -> str:
    """
    Make a cheap STS GetCallerIdentity call to verify credentials and clock sync
    before running a full audit. Returns the caller ARN on success.

    Raises RuntimeError with a human-readable fix if authentication fails.
    This catches two distinct problems before wasting time on 18-region API scans:
      - Clock skew  → system clock is drifted; fix is NTP sync, not re-login
      - Expired SSO → token has expired; fix is aws sso login
    """
    try:
        identity = session.client("sts", region_name="us-east-1").get_caller_identity()
        return identity.get("Arn", "unknown")
    except ClientError as exc:
        raise _translate_auth_error(exc, profile=profile) from exc


def get_all_regions(session: boto3.Session) -> list[str]:
    """Return all enabled EC2 regions for the session's account."""
    ec2 = session.client("ec2", region_name="us-east-1")
    return [
        r["RegionName"]
        for r in ec2.describe_regions(
            Filters=[{"Name": "opt-in-status", "Values": ["opt-in-not-required", "opted-in"]}]
        )["Regions"]
    ]


def scope_ce_filter(filter_expr: dict | None, account_id: str) -> dict | None:
    """AND a LINKED_ACCOUNT filter onto a Cost Explorer Filter expression.

    Used when CE / recommendation APIs are queried through a *payer* session
    (which sees the whole org) but the audit targets a single member account:
    without this scoping, org-wide costs would be mis-attributed to the target.

    No-op when account_id is empty (single-account / member-session runs), so
    the caller's original filter is returned unchanged.
    """
    if not account_id:
        return filter_expr
    linked = {"Dimensions": {"Key": "LINKED_ACCOUNT", "Values": [account_id]}}
    if filter_expr is None:
        return linked
    return {"And": [filter_expr, linked]}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _translate_auth_error(exc: ClientError, profile: str = "") -> RuntimeError:
    """
    Convert a botocore ClientError into a RuntimeError with a clear, actionable
    message. Distinguishes clock skew from token expiry from other auth failures.
    """
    code = exc.response.get("Error", {}).get("Code", "")
    msg  = exc.response.get("Error", {}).get("Message", "")

    # --- Clock skew (SignatureDoesNotMatch + "Signature expired") ---------------
    # Cause: local system clock is more than 5 minutes behind AWS server time.
    # Fix:   sync system clock — NOT aws sso login (the token is fine).
    if code == "SignatureDoesNotMatch" and "Signature expired" in msg:
        skew_seconds = _parse_clock_skew_seconds(msg)
        skew_note = f" (local clock is ~{skew_seconds // 60}m {skew_seconds % 60}s behind)" if skew_seconds else ""
        return RuntimeError(
            f"\n"
            f"  ✗  AWS clock skew error{skew_note}\n"
            f"\n"
            f"  Your system clock is out of sync with AWS (tolerance: ±5 minutes).\n"
            f"  This is NOT a token expiry — re-running 'aws sso login' will NOT fix it.\n"
            f"\n"
            f"  Fix: sync your system clock, then re-run the audit.\n"
            f"\n"
            f"    Linux / WSL:\n"
            f"      sudo timedatectl set-ntp true\n"
            f"      sudo systemctl restart systemd-timesyncd\n"
            f"      # or: sudo ntpdate -u pool.ntp.org\n"
            f"    macOS:\n"
            f"      sudo sntp -sS time.apple.com\n"
            f"    Windows:\n"
            f"      w32tm /resync /force\n"
            f"    Docker / WSL (if host clock drifted after sleep):\n"
            f"      sudo hwclock --hctosys\n"
            f"\n"
            f"  Original error: {msg}\n"
        )

    # --- Expired SSO / temporary credentials -----------------------------------
    # Cause: the SSO session or assumed-role token has expired.
    # Fix:   re-authenticate with aws sso login.
    if code in ("ExpiredTokenException", "ExpiredToken", "TokenRefreshRequired",
                "RequestExpired"):
        login_cmd = f"aws sso login --profile {profile}" if profile else "aws sso login"
        return RuntimeError(
            f"\n"
            f"  ✗  AWS SSO token has expired\n"
            f"\n"
            f"  Re-authenticate, then re-run the audit:\n"
            f"    {login_cmd}\n"
            f"\n"
            f"  Original error: {code} — {msg}\n"
        )

    # --- Other auth failures ---------------------------------------------------
    if code in ("InvalidClientTokenId", "AuthFailure", "NotAuthorized",
                "AccessDenied", "UnauthorizedAccess"):
        hint = f" (profile: {profile})" if profile else ""
        return RuntimeError(
            f"\n"
            f"  ✗  AWS authentication failed{hint}: {code}\n"
            f"  {msg}\n"
        )

    # Fallback — re-raise the original
    return RuntimeError(f"AWS error ({code}): {msg}")


def _parse_clock_skew_seconds(error_message: str) -> int:
    """
    Extract the approximate clock skew in seconds from a SignatureDoesNotMatch message.

    Example message:
      "Signature expired: 20260502T044741Z is now earlier than 20260502T051208Z ..."
    """
    try:
        from datetime import datetime, timezone
        timestamps = re.findall(r"(\d{8}T\d{6}Z)", error_message)
        if len(timestamps) >= 2:
            fmt = "%Y%m%dT%H%M%SZ"
            sig_time = datetime.strptime(timestamps[0], fmt).replace(tzinfo=timezone.utc)
            aws_time = datetime.strptime(timestamps[1], fmt).replace(tzinfo=timezone.utc)
            return max(0, int((aws_time - sig_time).total_seconds()))
    except Exception:
        pass
    return 0
