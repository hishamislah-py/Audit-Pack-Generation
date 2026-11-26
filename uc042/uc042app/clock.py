"""UTC timestamps (ISO 8601, seconds) for every stored record."""
from datetime import datetime, timezone


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def utc_iso(value):
    """The same instant as canonical UTC ISO 8601 (the now_iso() form, '+00:00'), whatever offset or database session time
    zone it was read with. Sub-second precision is kept when present. A naive value is refused (its instant would be
    ambiguous); None stays None."""
    if value is None:
        return None
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if dt.tzinfo is None:
        raise ValueError(f"timestamp without a time zone: {value!r}")
    dt = dt.astimezone(timezone.utc)
    return dt.isoformat(timespec="microseconds" if dt.microsecond else "seconds")
