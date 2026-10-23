"""Detection rules for forgotten storage and exposed databases."""

import datetime
from decimal import Decimal
from typing import Optional

from triage.models import (
    DataIssue,
    Finding,
    UNATTACHED_VOLUME,
    PUBLIC_DATABASE,
    EXPOSED_DATABASE_COST_SPIKE,
    CostRecord,
    ResourceMetadata,
)

# Standard ports for popular relational and NoSQL databases
COMMON_DB_PORTS = {3306, 5432, 1433, 1521, 27017}


def check_forgotten_storage(metadata: ResourceMetadata, cost: CostRecord) -> Optional[Finding]:
    """Rule 1: Unattached volume not needed and still costing money."""
    # Must be unattached, explicitly not needed, and incurring cost
    if metadata.is_attached:
        return None
    if metadata.is_needed is not False:
        return None
    if cost.daily_cost <= Decimal("0.00"):
        return None

    # Calculate days unattached using ISO date parsing
    days_unattached = 0
    if metadata.unattached_since and cost.date:
        try:
            report_d = datetime.date.fromisoformat(cost.date)
            detached_d = datetime.date.fromisoformat(metadata.unattached_since)
            days_unattached = (report_d - detached_d).days
        except ValueError:
            days_unattached = 0

    if days_unattached < 7:
        return None

    monthly_savings = (cost.daily_cost * Decimal("30")).quantize(Decimal("0.01"))

    return Finding(
        resource_id=cost.resource_id,
        rule_id=UNATTACHED_VOLUME,
        severity="MEDIUM",
        description="This disk looks unused. Please confirm with the owner before deleting it.",
        estimated_monthly_savings=monthly_savings,
        analysis_date=cost.date,
        evidence={
            "daily_cost_usd": cost.daily_cost,
            "days_unattached": days_unattached,
            "retention_required": metadata.is_needed,
        },
    )


def check_open_db(metadata: ResourceMetadata) -> Optional[Finding]:
    """Rule 2: Database port open to the public internet (0.0.0.0/0)."""
    has_public_cidr = "0.0.0.0/0" in metadata.allowed_cidrs
    has_db_port = any(port in COMMON_DB_PORTS for port in metadata.open_ports)

    if not (has_public_cidr and has_db_port):
        return None

    return Finding(
        resource_id=metadata.resource_id,
        rule_id=PUBLIC_DATABASE,
        severity="HIGH",
        description="Database port is open to the public internet (0.0.0.0/0).",
        estimated_monthly_savings=Decimal("0.00"),
        evidence={
            "open_ports": metadata.open_ports,
            "allowed_cidrs": metadata.allowed_cidrs,
        },
    )


def check_anomalous_open_db(metadata: ResourceMetadata, cost: CostRecord) -> Optional[Finding]:
    """Rule 3: Internet-exposed database with a bill more than 2x its 7-day average."""
    # Must first be open to the public internet
    if check_open_db(metadata) is None:
        return None

    baseline = metadata.baseline_avg_cost_7d
    if baseline is None or baseline <= Decimal("0.00"):
        return None

    # Strictly greater than 2x the baseline (2x exactly does not trigger)
    if cost.daily_cost <= (Decimal("2") * baseline):
        return None

    return Finding(
        resource_id=cost.resource_id,
        rule_id=EXPOSED_DATABASE_COST_SPIKE,
        severity="CRITICAL",
        description="Flagged for investigation: high bill anomaly detected on internet-exposed database.",
        estimated_monthly_savings=Decimal("0.00"),
        analysis_date=cost.date,
        evidence={
            "daily_cost_usd": cost.daily_cost,
            "baseline_avg_cost_7d": baseline,
        },
    )


def analyze_resources(
    cost_records: list[CostRecord],
    metadata_dict: dict[str, ResourceMetadata],
) -> list[Finding]:
    """Main runner function that evaluates all resources against detection rules.
    
    If Rule 3 (Anomalous Open DB) triggers for a database, it suppresses Rule 2
    (Open DB) to avoid duplicate alerts for the same resource.
    """
    findings: list[Finding] = []

    for cost in cost_records:
        metadata = metadata_dict.get(cost.resource_id)
        if not metadata:
            continue

        # Check Rule 1: Forgotten storage
        storage_finding = check_forgotten_storage(metadata, cost)
        if storage_finding:
            findings.append(storage_finding)

        # Check database rules:
        # If Rule 3 triggers, suppress Rule 2 to avoid duplicate findings.
        anomalous_db = check_anomalous_open_db(metadata, cost)
        if anomalous_db:
            findings.append(anomalous_db)
        else:
            open_db = check_open_db(metadata)
            if open_db:
                # Attach analysis date from the cost record
                open_db.analysis_date = cost.date
                findings.append(open_db)

    return findings


# --- Compatibility helpers for existing project starter harness ---

def check_unattached_volume(usage: dict, metadata: dict, report_date: str) -> Optional[Finding]:
    """Wrapper matching the starter harness signature."""
    raw_cost = usage.get("daily_cost_usd", Decimal("0.00"))
    cost = CostRecord(
        resource_id=usage.get("resource_id", ""),
        daily_cost=Decimal(str(raw_cost)),
        date=report_date,
    )
    is_attached = (metadata.get("attachment_state") == "attached")
    meta = ResourceMetadata(
        resource_id=metadata.get("resource_id", ""),
        resource_type=metadata.get("resource_type", "ebs_volume"),
        is_attached=is_attached,
        unattached_since=metadata.get("unattached_since"),
        is_needed=metadata.get("retention_required"),
    )
    return check_forgotten_storage(meta, cost)


def check_public_database(usage: dict, metadata: dict, report_date: str) -> Optional[Finding]:
    """Wrapper matching the starter harness signature."""
    db_port = metadata.get("database_port")
    inbound_rules = metadata.get("inbound_rules", [])
    open_ports = [r["port"] for r in inbound_rules if "port" in r]
    allowed_cidrs = [r["cidr"] for r in inbound_rules if "cidr" in r]

    # Include explicit db_port if present
    if db_port and db_port not in open_ports:
        open_ports.append(db_port)

    meta = ResourceMetadata(
        resource_id=metadata.get("resource_id", usage.get("resource_id", "")),
        resource_type="rds_database",
        is_attached=True,
        open_ports=open_ports,
        allowed_cidrs=allowed_cidrs,
    )
    finding = check_open_db(meta)
    if finding:
        finding.analysis_date = report_date
    return finding


def check_cost_spike(usage: dict, metadata: dict, report_date: str) -> Optional[Finding]:
    """Wrapper matching the starter harness signature."""
    daily_cost = Decimal(str(usage.get("daily_cost_usd", "0")))
    cost = CostRecord(
        resource_id=usage.get("resource_id", ""),
        daily_cost=daily_cost,
        date=report_date,
    )

    db_port = metadata.get("database_port")
    inbound_rules = metadata.get("inbound_rules", [])
    open_ports = [r["port"] for r in inbound_rules if "port" in r]
    allowed_cidrs = [r["cidr"] for r in inbound_rules if "cidr" in r]
    if db_port and db_port not in open_ports:
        open_ports.append(db_port)

    raw_baseline = usage.get("avg_daily_cost_7d_usd")
    baseline = Decimal(str(raw_baseline)) if raw_baseline is not None else None

    meta = ResourceMetadata(
        resource_id=metadata.get("resource_id", usage.get("resource_id", "")),
        resource_type="rds_database",
        is_attached=True,
        open_ports=open_ports,
        allowed_cidrs=allowed_cidrs,
        baseline_avg_cost_7d=baseline,
    )
    return check_anomalous_open_db(meta, cost)


def evaluate(
    usage_records: list[dict],
    metadata_by_id: dict[str, dict],
    report_date: str,
) -> tuple[list[Finding], list[DataIssue]]:
    """Evaluate raw usage records and metadata, collecting findings and data issues."""
    findings: list[Finding] = []
    issues: list[DataIssue] = []

    for record in usage_records:
        rid = record.get("resource_id", "")
        rtype = record.get("resource_type", "")

        if rid not in metadata_by_id:
            issues.append(
                DataIssue(
                    resource_id=rid,
                    issue_type="MISSING_METADATA",
                    message="No metadata found for this resource.",
                )
            )
            continue

        meta = metadata_by_id[rid]

        if rtype == "ebs_volume":
            if meta.get("attachment_state") == "unattached" and meta.get("retention_required") is None:
                issues.append(
                    DataIssue(
                        resource_id=rid,
                        issue_type="MISSING_FIELD",
                        message="Missing 'retention_required' field on unattached volume.",
                    )
                )
            else:
                f = check_unattached_volume(record, meta, report_date)
                if f:
                    findings.append(f)

        elif rtype == "rds_database":
            # Check for Rule 3 first
            f_spike = check_cost_spike(record, meta, report_date)
            if f_spike:
                findings.append(f_spike)
            else:
                f_pub = check_public_database(record, meta, report_date)
                if f_pub:
                    findings.append(f_pub)

            # Track baseline availability for public databases
            avg_cost = record.get("avg_daily_cost_7d_usd")
            if (avg_cost is None or Decimal(str(avg_cost)) <= Decimal("0.00")) and check_public_database(record, meta, report_date):
                issues.append(
                    DataIssue(
                        resource_id=rid,
                        issue_type="BASELINE_UNAVAILABLE",
                        message="7-day average daily cost is missing or zero.",
                    )
                )

    return findings, issues
