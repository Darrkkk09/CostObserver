"""Persist findings to DynamoDB."""

from triage.models import Finding


def save_findings(table, findings: list[Finding]) -> int:
    """Write findings to the PrioritizedFindings table and return how many were written.

    Uses Finding.finding_id as the partition key so that re-running the same report
    updates items in-place without creating duplicates.
    """
    count = 0
    with table.batch_writer() as batch:
        for f in findings:
            item = {
                "finding_id": f.finding_id,
                "resource_id": f.resource_id,
                "rule_id": f.rule_id,
                "severity": f.severity,
                "analysis_date": f.analysis_date,
                "recommended_action": f.recommended_action or f.description,
                "evidence": f.evidence,
            }
            # Only include savings if non-null
            savings = f.projected_monthly_savings_usd or f.estimated_monthly_savings
            if savings is not None and savings > 0:
                item["projected_monthly_savings_usd"] = savings

            batch.put_item(Item=item)
            count += 1

    return count
