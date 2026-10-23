"""Shared data models for CostObserver triage."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional

# Standard rule constants and severities
UNATTACHED_VOLUME = "UNATTACHED_VOLUME"
PUBLIC_DATABASE = "PUBLIC_DATABASE"
EXPOSED_DATABASE_COST_SPIKE = "EXPOSED_DATABASE_COST_SPIKE"

SEVERITY_BY_RULE = {
    UNATTACHED_VOLUME: "MEDIUM",
    PUBLIC_DATABASE: "HIGH",
    EXPOSED_DATABASE_COST_SPIKE: "CRITICAL",
}


@dataclass
class CostRecord:
    """Represents a single daily cost entry for a cloud resource."""
    resource_id: str
    daily_cost: Decimal
    date: str


@dataclass
class ResourceMetadata:
    """Operational and network metadata for a resource."""
    resource_id: str
    resource_type: str
    is_attached: bool
    unattached_since: Optional[str] = None
    is_needed: Optional[bool] = None
    open_ports: list[int] = field(default_factory=list)
    allowed_cidrs: list[str] = field(default_factory=list)
    baseline_avg_cost_7d: Optional[Decimal] = None


@dataclass
class Finding:
    """Represents a flagged cost or security issue."""
    resource_id: str
    rule_id: str
    severity: str
    description: str
    estimated_monthly_savings: Optional[Decimal] = None
    analysis_date: str = ""
    recommended_action: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    projected_monthly_savings_usd: Optional[Decimal] = None

    def __post_init__(self) -> None:
        # Keep convenience fields aligned
        if not self.recommended_action and self.description:
            self.recommended_action = self.description
        if not self.description and self.recommended_action:
            self.description = self.recommended_action
        if self.estimated_monthly_savings is not None and self.projected_monthly_savings_usd is None:
            self.projected_monthly_savings_usd = self.estimated_monthly_savings
        elif self.projected_monthly_savings_usd is not None and self.estimated_monthly_savings is None:
            self.estimated_monthly_savings = self.projected_monthly_savings_usd

    @property
    def finding_id(self) -> str:
        """Deterministic key to ensure idempotency on repeated runs."""
        return f"{self.analysis_date}#{self.resource_id}#{self.rule_id}"


@dataclass
class DataIssue:
    """Tracks records that cannot be evaluated due to missing information."""
    resource_id: str
    issue_type: str
    message: str

    # Compatibility properties for starter test runners
    @property
    def issue(self) -> str:
        return self.issue_type

    @property
    def detail(self) -> str:
        return self.message
