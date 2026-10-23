"""Create the local S3 bucket and DynamoDB tables, then load the sample data.

Usage (with the local emulator running):
    python scripts/setup_data.py          # create anything missing and load data
    python scripts/setup_data.py --reset  # start from a clean state
"""

import argparse
import json
import sys
from pathlib import Path

from botocore.exceptions import ClientError, EndpointConnectionError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from triage import config  # noqa: E402

DATA_DIR = ROOT / "data"


def _table_exists(dynamodb, name: str) -> bool:
    return name in [table.name for table in dynamodb.tables.all()]


def _create_table(dynamodb, name: str, key: str) -> None:
    table = dynamodb.create_table(
        TableName=name,
        KeySchema=[{"AttributeName": key, "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": key, "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    table.wait_until_exists()


def _delete_bucket(s3, bucket: str) -> None:
    try:
        objects = s3.list_objects_v2(Bucket=bucket).get("Contents", [])
    except ClientError:
        return
    for obj in objects:
        s3.delete_object(Bucket=bucket, Key=obj["Key"])
    s3.delete_bucket(Bucket=bucket)


def seed_environment(s3, dynamodb, reset: bool = False) -> dict:
    """Create resources and load sample data. Safe to run more than once."""
    if reset:
        _delete_bucket(s3, config.USAGE_BUCKET)
        for name in (config.METADATA_TABLE, config.FINDINGS_TABLE):
            if _table_exists(dynamodb, name):
                dynamodb.Table(name).delete()

    existing_buckets = [b["Name"] for b in s3.list_buckets().get("Buckets", [])]
    if config.USAGE_BUCKET not in existing_buckets:
        s3.create_bucket(Bucket=config.USAGE_BUCKET)

    if not _table_exists(dynamodb, config.METADATA_TABLE):
        _create_table(dynamodb, config.METADATA_TABLE, "resource_id")
    if not _table_exists(dynamodb, config.FINDINGS_TABLE):
        _create_table(dynamodb, config.FINDINGS_TABLE, "finding_id")

    usage_text = (DATA_DIR / "daily-usage.json").read_text(encoding="utf-8")
    report_date = json.loads(usage_text)["report_date"]
    key = config.usage_key(report_date)
    s3.put_object(
        Bucket=config.USAGE_BUCKET,
        Key=key,
        Body=usage_text.encode("utf-8"),
        ContentType="application/json",
    )

    metadata = json.loads((DATA_DIR / "resource-metadata.json").read_text(encoding="utf-8"))
    with dynamodb.Table(config.METADATA_TABLE).batch_writer() as batch:
        for item in metadata:
            batch.put_item(Item=item)

    return {"report_date": report_date, "usage_key": key, "metadata_items": len(metadata)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reset", action="store_true", help="delete and recreate everything")
    args = parser.parse_args()

    try:
        result = seed_environment(config.s3_client(), config.dynamodb_resource(), reset=args.reset)
    except EndpointConnectionError:
        print(
            f"Could not reach the local emulator at {config.ENDPOINT_URL}.\n"
            "Start it first in another terminal:  moto_server -p 4566",
            file=sys.stderr,
        )
        return 1

    print("Local environment is ready.")
    print(f"  S3 usage file : s3://{config.USAGE_BUCKET}/{result['usage_key']}")
    print(f"  Metadata table: {config.METADATA_TABLE} ({result['metadata_items']} items)")
    print(f"  Findings table: {config.FINDINGS_TABLE}")
    print(f"\nNext: python -m triage.main --date {result['report_date']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
