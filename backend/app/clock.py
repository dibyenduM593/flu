"""Platform clock. In dev mode ops can move simulated time forward so 72-hour approval windows,
6-hourly polling and settlement cycles can be exercised in minutes. All business code reads now()."""
from datetime import datetime, timedelta, timezone
from threading import Lock

_offset = timedelta(0)
_lock = Lock()


def now() -> datetime:
    return datetime.now(timezone.utc) + _offset


def offset_hours() -> float:
    return _offset.total_seconds() / 3600


def set_offset(hours: float) -> None:
    global _offset
    with _lock:
        _offset = timedelta(hours=hours)


def load(db) -> None:
    from .models import SimState
    row = db.get(SimState, "clock")
    set_offset(float(row.value.get("offset_hours", 0)) if row else 0)


def persist(db) -> None:
    from .models import SimState
    row = db.get(SimState, "clock")
    if row is None:
        db.add(SimState(key="clock", value={"offset_hours": offset_hours()}))
    else:
        row.value = {"offset_hours": offset_hours()}
