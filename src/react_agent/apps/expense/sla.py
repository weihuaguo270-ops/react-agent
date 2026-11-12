"""H2 wall-clock deadlines; no scheduler, notification delivery or Claim writes."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .handoff import SLAPolicy
from .store import ExpenseStoreError


def utc(value: datetime) -> datetime:
    """SQLite returns naive stored UTC datetimes; normalize both SQL dialects."""
    return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(timezone.utc)


def deadlines(created_at: datetime, policy: SLAPolicy | None) -> tuple[datetime | None, datetime | None]:
    if policy is None:
        return None, None
    try:
        start = utc(created_at)
        return (start + timedelta(seconds=policy.response_sla_seconds),
                start + timedelta(seconds=policy.resolution_sla_seconds))
    except (OverflowError, ValueError) as exc:
        raise ExpenseStoreError("sla_policy_unavailable", "SLA deadlines are outside supported dates") from exc
