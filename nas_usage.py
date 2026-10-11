"""Offline usage values. No DSM contract, aggregation, or enforcement implied."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Subject:
    tenant_id: str
    kind: str
    subject_id: str
    accounting_scope: str

    def __post_init__(self):
        for value in (self.tenant_id, self.subject_id, self.accounting_scope):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("subject identifiers and accounting scope must be nonempty strings")
        if self.kind not in ("account", "group"):
            raise ValueError("subject kind must be account or group")


@dataclass(frozen=True)
class UsageObservation:
    subject: Subject
    state: str = "not_configured"
    limit_kind: str = "unknown"
    assigned_bytes: int | None = None
    used_bytes: int | None = None
    remaining_bytes: int | None = None
    observed_at: datetime | None = None
    source: str | None = None

    def __post_init__(self):
        if not isinstance(self.subject, Subject):
            raise ValueError("subject must be a Subject")
        if self.state not in ("not_configured", "unknown", "observed"):
            raise ValueError("invalid collection state")
        if self.limit_kind not in ("unknown", "limited", "unlimited"):
            raise ValueError("invalid limit kind")
        values = (self.assigned_bytes, self.used_bytes, self.remaining_bytes)
        for value in values:
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("byte values must be nonnegative integers or None")
        if self.state != "observed":
            if any(value is not None for value in (*values, self.observed_at, self.source)) or self.limit_kind != "unknown":
                raise ValueError("uncollected state cannot contain observations")
            return
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("observations require a nonempty source identifier")
        if not isinstance(self.observed_at, datetime) or self.observed_at.utcoffset() is None:
            raise ValueError("observations require a timezone-aware timestamp")
        if self.limit_kind == "limited":
            if self.assigned_bytes is None:
                raise ValueError("limited quota requires assigned bytes")
        elif self.assigned_bytes is not None or self.remaining_bytes is not None:
            raise ValueError("unknown or unlimited quota cannot contain finite limits or remaining bytes")

    def freshness(self, *, now: datetime, max_age: timedelta) -> str:
        """Age equal to the supplied maximum is fresh; no default TTL policy."""
        if not isinstance(now, datetime) or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        if not isinstance(max_age, timedelta) or max_age < timedelta(0):
            raise ValueError("max_age must be a nonnegative timedelta")
        if self.state != "observed":
            return self.state
        assert self.observed_at is not None  # Validated on construction.
        observed_utc = self.observed_at.astimezone(timezone.utc)
        now_utc = now.astimezone(timezone.utc)
        if observed_utc > now_utc:
            raise ValueError("observation is in the future relative to now")
        return "stale" if now_utc - observed_utc > max_age else "fresh"

    def display(self, *, now: datetime, max_age: timedelta) -> dict[str, str]:
        """Plain-text presentation only; unlimited is not physical free space."""
        freshness = self.freshness(now=now, max_age=max_age)
        labels = {"not_configured": "설정 안 됨", "unknown": "미수집",
                  "fresh": "최신 관측", "stale": "오래된 관측"}
        result = {"status": labels[freshness]}
        for key, value in (("assigned", self.assigned_bytes), ("used", self.used_bytes),
                           ("remaining", self.remaining_bytes)):
            label = "알 수 없음" if value is None else f"{value} B"
            if self.limit_kind == "unlimited" and key != "used":
                label = "무제한" if key == "assigned" else "해당 없음 (무제한)"
            if freshness == "stale" and label != "알 수 없음":
                label += " (오래된 값)"
            result[key] = label
        return result


@runtime_checkable
class UsageReader(Protocol):
    """One explicit subject/scope per read. No write or discovery capability.

    Implementations must return the requested subject and provenance, not
    reinterpret inherited group limits as pooled capacity. This protocol does
    not establish a vendor API or an authorization boundary.
    """

    def read_usage(self, subject: Subject) -> UsageObservation: ...


class NotConfiguredReader:
    """The only bundled implementation: no I/O and no invented metrics."""

    def read_usage(self, subject: Subject) -> UsageObservation:
        return UsageObservation(subject=subject)
