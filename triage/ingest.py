"""Data loading layer for S3 cost reports and DynamoDB metadata."""

import json
from decimal import Decimal
from typing import Optional

from triage import config
from triage.models import CostRecord, ResourceMetadata


def fetch_s3_costs(bucket_name: str, object_key: str, s3_client=None) -> list[CostRecord]:
    """Read daily cost records from an S3 JSON file.
    
    Parses floats as Decimal to ensure monetary precision.
    """
    client = s3_client if s3_client is not None else config.s3_client()
    response = client.get_object(Bucket=bucket_name, Key=object_key)
    body_text = response["Body"].read().decode("utf-8")

    # parse_float=Decimal avoids IEEE-754 binary floating point issues
    data = json.loads(body_text, parse_float=Decimal)
    report_date = data.get("report_date", "")

    cost_records: list[CostRecord] = []
    for item in data.get("records", []):
        resource_id = item.get("resource_id")
        if not resource_id:
            continue

        raw_cost = item.get("daily_cost_usd")
        daily_cost = Decimal(raw_cost) if raw_cost is not None else Decimal("0.00")

        cost_records.append(
            CostRecord(
                resource_id=resource_id,
                daily_cost=daily_cost,
                date=report_date,
            )
        )

    return cost_records


def fetch_dynamo_metadata(table_name: str, dynamodb_resource=None) -> dict[str, ResourceMetadata]:
    """Scan DynamoDB resource metadata and map into typed ResourceMetadata objects."""
    dynamo = dynamodb_resource if dynamodb_resource is not None else config.dynamodb_resource()
    table = dynamo.Table(table_name)

    metadata_by_id: dict[str, ResourceMetadata] = {}

    # Scan all records, handling pagination if the table has more than 1MB of data
    paginator_args = {}
    while True:
        response = table.scan(**paginator_args)
        items = response.get("Items", [])

        for item in items:
            resource_id = item.get("resource_id")
            if not resource_id:
                continue

            # Extract inbound network rules defensively
            open_ports: list[int] = []
            allowed_cidrs: list[str] = []
            for rule in item.get("inbound_rules", []):
                if "port" in rule:
                    open_ports.append(int(rule["port"]))
                if "cidr" in rule:
                    allowed_cidrs.append(str(rule["cidr"]))

            # Convert attachment state into clean boolean flag
            attachment_state = item.get("attachment_state")
            is_attached = (attachment_state == "attached")

            # Extract baseline 7-day average if present
            raw_baseline = item.get("avg_daily_cost_7d_usd")
            baseline = Decimal(str(raw_baseline)) if raw_baseline is not None else None

            metadata_by_id[resource_id] = ResourceMetadata(
                resource_id=resource_id,
                resource_type=item.get("resource_type", ""),
                is_attached=is_attached,
                unattached_since=item.get("unattached_since"),
                is_needed=item.get("retention_required"),
                open_ports=open_ports,
                allowed_cidrs=allowed_cidrs,
                baseline_avg_cost_7d=baseline,
            )

        if "LastEvaluatedKey" in response:
            paginator_args["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        else:
            break

    return metadata_by_id


# Compatibility functions for existing project harness
def load_usage_report(s3, bucket: str, key: str) -> dict:
    """Download and parse raw usage document from S3 with Decimal precision."""
    response = s3.get_object(Bucket=bucket, Key=key)
    body_text = response["Body"].read().decode("utf-8")
    return json.loads(body_text, parse_float=Decimal)


def load_metadata(table, resource_ids: list[str]) -> dict[str, dict]:
    """Fetch raw metadata items keyed by resource_id."""
    result: dict[str, dict] = {}
    for resource_id in set(resource_ids):
        res = table.get_item(Key={"resource_id": resource_id})
        item = res.get("Item")
        if item is not None:
            result[resource_id] = item
    return result
