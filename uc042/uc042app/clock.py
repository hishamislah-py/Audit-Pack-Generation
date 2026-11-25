"""UTC timestamps (ISO 8601, seconds) for every stored record."""
from datetime import datetime, timezone


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
