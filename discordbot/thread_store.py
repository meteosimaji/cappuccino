import shelve

try:
    _DB = shelve.open("threads.db")
except Exception:
    # Fallback to an in-memory dict if the database cannot be opened
    _DB = {}


def get(channel_id: int) -> str | None:
    return _DB.get(str(channel_id))


def save(channel_id: int, thread_id: str):
    _DB[str(channel_id)] = thread_id
    if hasattr(_DB, "sync"):
        _DB.sync()


def delete(channel_id: int) -> None:
    """Remove mapping for the given channel if present."""
    key = str(channel_id)
    if key in _DB:
        del _DB[key]
        if hasattr(_DB, "sync"):
            _DB.sync()


def all_items() -> dict[str, str]:
    """Return a copy of all channel to thread mappings."""
    return dict(_DB)
