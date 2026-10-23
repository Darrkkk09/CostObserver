# My solution

## How to run

1. **Environment Setup**:
   ```bash
   python -m venv .venv
   source .venv/bin/activate       # On Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Run Tests**:
   ```bash
   pytest
   ```
   All 7 unit and integration tests run using Moto's in-memory mock AWS environment (no external servers or Docker required).

3. **Run the Triage CLI**:
   * Option A (In-memory mock / Test harness):
     ```bash
     python -c "import sys; sys.path.insert(0, 'scripts'); import setup_data; from triage import main, config; from moto import mock_aws; m = mock_aws(); m.start(); s3 = config.s3_client(None); dynamo = config.dynamodb_resource(None); setup_data.seed_environment(s3, dynamo); main.run('2026-10-20', s3, dynamo); m.stop()"
     ```
   * Option B (Local Moto server):
     In terminal 1:
     ```bash
     moto_server -p 4566
     ```
     In terminal 2:
     ```bash
     python scripts/setup_data.py
     python -m triage.main --date 2026-10-20
     ```

---

## Key decisions

1. **`Decimal` for Financial Precision and DynamoDB Compatibility**:
   Used `json.loads(text, parse_float=Decimal)` across ingestion. Floating-point types in standard Python introduce rounding artifacts (e.g., `0.1 + 0.2 != 0.3`) and are rejected by Boto3 when persisting to DynamoDB. All cost math uses `Decimal.quantize(Decimal("0.01"))`.

2. **Deterministic Partition Key for Idempotency**:
   Formulated the DynamoDB finding partition key as:
   `finding_id = f"{analysis_date}#{resource_id}#{rule_id}"`
   Re-running the workflow on the same date overwrites/updates findings in place rather than creating duplicate records. Additionally, a local state check (`processed_runs.json`) records SHA-256 hashes of processed items to ensure repeated CLI runs remain clean.

3. **Strict ISO Date Math**:
   Parsed dates (`report_date` and `unattached_since`) into `datetime.date` objects using `datetime.date.fromisoformat()` rather than comparing raw strings. This guarantees exact calendar day subtraction (`(report_date - unattached_since).days >= 7`).

4. **Alert Suppression (Rule 3 suppresses Rule 2)**:
   When an internet-exposed database triggers **Rule 3** (`EXPOSED_DATABASE_COST_SPIKE`), it automatically suppresses **Rule 2** (`PUBLIC_DATABASE`). This avoids duplicate alerts and notification fatigue for the same underlying asset.

5. **Defensive Missing Data Handling without Guessing**:
   If a field is missing (such as `retention_required` on an unattached volume, missing 7-day average baseline, or a resource without a DynamoDB metadata record), the engine does not guess or assume safe defaults. Instead, it emits structured `DataIssue` records displayed under `Could not fully check` in the report.

---

## Assumptions

* **Standard Month**: Projected monthly savings for unattached volumes are calculated using a 30-day baseline (`daily_cost_usd * 30`), as specified in the brief.
* **Security Findings Savings**: Security risks without direct reclaimable waste (Rules B and C) carry zero/null projected savings to prevent inflating cost recovery estimates.
* **Unmonitored Resource Types**: Types like `ec2_instance` and `s3_bucket` without rules in this exercise are counted toward total analyzed resources, but are not flagged as data issues.

---

## What I would improve with more time

1. **Parallel / Async Ingestion**:
   Replace sequential lookups with parallel `BatchGetItem` (in chunks of 100) or concurrent worker pools (`asyncio` / `ThreadPoolExecutor`) to support millions of resources efficiently.
2. **Dynamic Policy Rules Engine**:
   Externalize rules into configurable YAML/JSON definitions (e.g., custom detachment day thresholds, configurable spike multipliers per environment).
3. **Automated Remediation Webhooks**:
   Add direct integrations for Slack/Teams alerts or AWS EventBridge events that prompt resource owners to approve volume deletion or security group restriction with a single click.

---

## Running this on real AWS

In production, this triage engine would run as an automated, event-driven pipeline:
1. **Trigger**: An S3 `ObjectCreated` notification on the usage bucket emits an event to Amazon EventBridge whenever the daily billing report lands.
2. **Compute**: EventBridge triggers an AWS Lambda function (or an ECS Fargate task if cost reports exceed Lambda's 15-minute runtime limit).
3. **Permissions**: The execution role is governed by least privilege IAM policies (`s3:GetObject` on `usage/*`, `dynamodb:BatchGetItem` on `ResourceMetadata`, and `dynamodb:PutItem` on `PrioritizedFindings`).
4. **Monitoring & Alerts**:
   * Failures are routed to an Amazon SQS Dead-Letter Queue (DLQ).
   * High-severity / critical findings trigger Amazon SNS topics routing to PagerDuty or Slack.
   * Execution metrics (duration, findings count, total savings) are published to CloudWatch custom metrics.

---

## Use of AI tools

AI was used as an assistive pair-programming companion for initial scaffolding, generating repetitive fixture templates, and formatting docstrings. All business logic, suppression rules, data models, edge boundary verifications, and architectural decisions were explicitly directed, reviewed, and verified.

---

## Time spent

Approximately **2.5 to 3 hours** in total (setup, data ingestion, rule engine, idempotency persistence, test coverage, and documentation).
