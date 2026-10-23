"""Concise unit tests for CostObserver using moto to mock AWS."""

import json
from decimal import Decimal
import boto3
import pytest
from moto import mock_aws

from triage.models import (
    CostRecord,
    ResourceMetadata,
    UNATTACHED_VOLUME,
    PUBLIC_DATABASE,
    EXPOSED_DATABASE_COST_SPIKE,
)
from triage import rules, store
from triage.main import deduplicate_findings


@pytest.fixture
def mock_cloud_environment():
    """Set up an in-memory mock S3 bucket and DynamoDB table using moto."""
    with mock_aws():
        # Setup S3
        s3 = boto3.client("s3", region_name="us-east-1")
        bucket_name = "test-cost-bucket"
        s3.create_bucket(Bucket=bucket_name)

        # Setup DynamoDB
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        findings_table = dynamodb.create_table(
            TableName="PrioritizedFindings",
            KeySchema=[{"AttributeName": "finding_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "finding_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        findings_table.wait_until_exists()

        yield s3, findings_table, bucket_name


# Test 1: Forgotten storage is flagged correctly and monthly savings (daily_cost * 30) are calculated
def test_forgotten_storage_flagged_with_savings():
    cost = CostRecord(resource_id="vol-100", daily_cost=Decimal("2.00"), date="2026-10-20")
    meta = ResourceMetadata(
        resource_id="vol-100",
        resource_type="ebs_volume",
        is_attached=False,
        unattached_since="2026-10-10",  # 10 days unattached (>= 7)
        is_needed=False,
    )

    finding = rules.check_forgotten_storage(meta, cost)

    assert finding is not None
    assert finding.rule_id == UNATTACHED_VOLUME
    assert finding.severity == "MEDIUM"
    assert finding.estimated_monthly_savings == Decimal("60.00")  # 2.00 * 30


# Test 2: Database open to 0.0.0.0/0 is flagged
def test_public_database_flagged():
    meta = ResourceMetadata(
        resource_id="db-orders",
        resource_type="rds_database",
        is_attached=True,
        open_ports=[5432],
        allowed_cidrs=["0.0.0.0/0"],
    )

    finding = rules.check_open_db(meta)

    assert finding is not None
    assert finding.rule_id == PUBLIC_DATABASE
    assert finding.severity == "HIGH"
    assert finding.estimated_monthly_savings == Decimal("0.00")


# Test 3: Open database with >2x baseline cost triggers anomaly rule and suppresses open DB rule
def test_cost_spike_suppresses_open_db_rule():
    cost = CostRecord(resource_id="db-orders", daily_cost=Decimal("50.00"), date="2026-10-20")
    meta = ResourceMetadata(
        resource_id="db-orders",
        resource_type="rds_database",
        is_attached=True,
        open_ports=[5432],
        allowed_cidrs=["0.0.0.0/0"],
        baseline_avg_cost_7d=Decimal("20.00"),  # 50.00 > 2 * 20.00
    )

    findings = rules.analyze_resources([cost], {"db-orders": meta})

    # Exactly one finding returned because Rule 3 suppresses Rule 2
    assert len(findings) == 1
    assert findings[0].rule_id == EXPOSED_DATABASE_COST_SPIKE
    assert findings[0].severity == "CRITICAL"


# Test 4: Re-running the function twice on the same dataset does not yield duplicate findings
def test_rerun_does_not_create_duplicates(mock_cloud_environment):
    _, table, _ = mock_cloud_environment

    cost = CostRecord(resource_id="vol-100", daily_cost=Decimal("2.00"), date="2026-10-20")
    meta = ResourceMetadata(
        resource_id="vol-100",
        resource_type="ebs_volume",
        is_attached=False,
        unattached_since="2026-10-10",
        is_needed=False,
    )

    # 1. First run: finding is generated and persisted
    findings = rules.analyze_resources([cost], {"vol-100": meta})
    assert len(findings) == 1
    store.save_findings(table, findings)

    # Check DynamoDB has 1 item
    items_first = table.scan()["Items"]
    assert len(items_first) == 1

    # 2. Second run: saving the same findings again updates in-place via deterministic finding_id
    store.save_findings(table, findings)
    items_second = table.scan()["Items"]
    assert len(items_second) == 1  # No duplicate rows created in DynamoDB

    # Also verify local state deduplication filter
    processed_hashes = set()
    new_findings, updated_hashes = deduplicate_findings(findings, processed_hashes)
    assert len(new_findings) == 1

    # Re-run against updated hashes: duplicates are skipped
    repeat_findings, _ = deduplicate_findings(findings, updated_hashes)
    assert len(repeat_findings) == 0
