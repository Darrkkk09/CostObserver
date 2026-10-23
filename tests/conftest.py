"""Test fixtures.

The `aws` fixture runs an in-memory AWS mock (moto), so tests do not need
moto_server to be running.
"""

import pytest
from moto import mock_aws

import setup_data
from triage import config


@pytest.fixture
def aws(monkeypatch):
    """Yield (s3_client, dynamodb_resource) with the sample data already loaded."""
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        s3 = config.s3_client(endpoint_url=None)
        dynamodb = config.dynamodb_resource(endpoint_url=None)
        setup_data.seed_environment(s3, dynamodb)
        yield s3, dynamodb
