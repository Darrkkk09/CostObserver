"""Checks that the provided setup works. These should pass before you write any code."""

import json

from triage import config


def test_usage_file_is_in_s3(aws):
    s3, _ = aws
    body = s3.get_object(Bucket=config.USAGE_BUCKET, Key=config.usage_key("2026-10-20"))["Body"].read()
    report = json.loads(body)
    assert report["report_date"] == "2026-10-20"
    assert len(report["records"]) == 16


def test_metadata_table_is_loaded(aws):
    _, dynamodb = aws
    item = dynamodb.Table(config.METADATA_TABLE).get_item(Key={"resource_id": "db-orders-prod"})["Item"]
    assert item["database_port"] == 5432


def test_findings_table_starts_empty(aws):
    _, dynamodb = aws
    assert dynamodb.Table(config.FINDINGS_TABLE).scan()["Items"] == []
