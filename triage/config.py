"""Shared settings for the local AWS environment.

Everything points at a local emulator. No real AWS account is used.
"""

import os

import boto3

ENDPOINT_URL = os.environ.get("AWS_ENDPOINT_URL", "http://localhost:4566")
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

USAGE_BUCKET = "costobserver-usage"
METADATA_TABLE = "ResourceMetadata"
FINDINGS_TABLE = "PrioritizedFindings"


def usage_key(report_date: str) -> str:
    """S3 key of the daily usage file, for example usage/2026-10-20/daily-usage.json."""
    return f"usage/{report_date}/daily-usage.json"


def _session() -> boto3.session.Session:
    # The local emulator accepts any credentials. These placeholders are not real keys.
    return boto3.session.Session(
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "local"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "local"),
        region_name=REGION,
    )


def s3_client(endpoint_url: str | None = ENDPOINT_URL):
    return _session().client("s3", endpoint_url=endpoint_url)


def dynamodb_resource(endpoint_url: str | None = ENDPOINT_URL):
    return _session().resource("dynamodb", endpoint_url=endpoint_url)
