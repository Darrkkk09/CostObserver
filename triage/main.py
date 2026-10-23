"""Command-line entry point for CostObserver triage.

Usage:
    python -m triage.main --date 2026-10-20
"""

import argparse
import hashlib
import json
from decimal import Decimal
from pathlib import Path
import sys

from botocore.exceptions import EndpointConnectionError

from triage import config, ingest, rules, store
from triage.models import DataIssue, Finding

STATE_FILE = Path("processed_runs.json")


def _get_finding_hash(finding: Finding) -> str:
    """Create a stable hash identifier: hash(resource_id + situation + date)."""
    identity = f"{finding.resource_id}#{finding.rule_id}#{finding.analysis_date}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def load_processed_hashes(path: Path = STATE_FILE) -> set[str]:
    """Read previously recorded finding hashes from the local JSON state file."""
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return set(data) if isinstance(data, list) else set()
    except (json.JSONDecodeError, OSError):
        return set()


def save_processed_hashes(hashes: set[str], path: Path = STATE_FILE) -> None:
    """Persist finding hashes to the local JSON state file."""
    path.write_text(json.dumps(sorted(list(hashes)), indent=2), encoding="utf-8")


def deduplicate_findings(findings: list[Finding], processed_hashes: set[str]) -> tuple[list[Finding], set[str]]:
    """Filter out findings that have already been recorded in a prior run."""
    new_findings: list[Finding] = []
    updated_hashes = set(processed_hashes)

    for f in findings:
        f_hash = _get_finding_hash(f)
        if f_hash not in updated_hashes:
            new_findings.append(f)
            updated_hashes.add(f_hash)

    return new_findings, updated_hashes


def print_summary(
    usage_records: list[dict],
    findings: list[Finding],
    issues: list[DataIssue],
    date: str = "",
) -> None:
    """Print a short, readable summary to the console."""
    total_analyzed = len(usage_records)
    affected_resources = {f.resource_id for f in findings}

    # Severity ordering
    severity_rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    sorted_findings = sorted(
        findings,
        key=lambda x: (severity_rank.get(x.severity, 99), x.resource_id),
    )

    # Tally counts by severity
    critical_count = sum(1 for f in findings if f.severity == "CRITICAL")
    high_count = sum(1 for f in findings if f.severity == "HIGH")
    medium_count = sum(1 for f in findings if f.severity == "MEDIUM")

    # Deduplicate savings per resource
    savings_by_resource: dict[str, Decimal] = {}
    for f in findings:
        savings = f.projected_monthly_savings_usd or f.estimated_monthly_savings
        if savings and savings > Decimal("0.00"):
            # If multiple findings apply to one resource, take the max to avoid double counting
            savings_by_resource[f.resource_id] = max(
                savings_by_resource.get(f.resource_id, Decimal("0.00")),
                savings,
            )
    total_savings = sum(savings_by_resource.values(), Decimal("0.00"))

    print(f"\nCostObserver triage report for {date or 'today'}\n")
    print(f"Resources analyzed : {total_analyzed}")
    print(f"Resources affected : {len(affected_resources)}")
    print(f"Findings           : CRITICAL {critical_count} | HIGH {high_count} | MEDIUM {medium_count}")
    print(f"Projected monthly avoidable cost: ${total_savings:.2f}")
    print("  (estimate, assuming current daily rates continue and owners approve the change)\n")

    if sorted_findings:
        print("Needs attention first")
        for f in sorted_findings:
            print(f"  [{f.severity:<8}] {f.resource_id:<14} {f.rule_id}")
            desc = f.description or f.recommended_action
            if desc:
                print(f"             {desc}")
            savings = f.projected_monthly_savings_usd or f.estimated_monthly_savings
            if savings and savings > Decimal("0.00"):
                print(f"             Projected saving: ${savings:.2f}/month")
        print()

    if issues:
        print("Could not fully check")
        for issue in issues:
            print(f"  {issue.resource_id:<12} {issue.issue_type:<20} {issue.message}")
        print()


def run(report_date: str, s3, dynamodb) -> None:
    """Execute the end-to-end triage pipeline."""
    # 1. Ingest S3 usage and DynamoDB metadata
    report = ingest.load_usage_report(s3, config.USAGE_BUCKET, config.usage_key(report_date))
    records = report.get("records", [])

    resource_ids = [record["resource_id"] for record in records if "resource_id" in record]
    metadata = ingest.load_metadata(dynamodb.Table(config.METADATA_TABLE), resource_ids)

    # 2. Evaluate rules
    raw_findings, issues = rules.evaluate(records, metadata, report_date)

    # 3. Check local JSON state file to ensure idempotency across repeat runs
    processed_hashes = load_processed_hashes(STATE_FILE)
    new_findings, updated_hashes = deduplicate_findings(raw_findings, processed_hashes)
    save_processed_hashes(updated_hashes, STATE_FILE)

    # 4. Persist to DynamoDB findings table
    store.save_findings(dynamodb.Table(config.FINDINGS_TABLE), raw_findings)

    # 5. Output summary
    print_summary(records, raw_findings, issues, date=report_date)


def main() -> int:
    parser = argparse.ArgumentParser(description="Correlate cloud cost with resource configuration.")
    parser.add_argument("--date", required=True, help="report date, for example 2026-10-20")
    args = parser.parse_args()

    try:
        run(args.date, config.s3_client(), config.dynamodb_resource())
    except EndpointConnectionError:
        print(f"Could not reach the local emulator at {config.ENDPOINT_URL}. Is moto_server running?", file=sys.stderr)
        return 1
    except NotImplementedError as exc:
        print(f"Not implemented yet: {exc}. This is where your work starts.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
