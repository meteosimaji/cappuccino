import shelve

_DB = shelve.open("threads.db")


def get(channel_id: int) -> str | None:
    return _DB.get(str(channel_id))


def save(channel_id: int, thread_id: str):
    _DB[str(channel_id)] = thread_id


def delete(channel_id: int) -> None:
    """Remove mapping for the given channel if present."""
    key = str(channel_id)
    if key in _DB:
        del _DB[key]


def all_items() -> dict[str, str]:
    """Return a copy of all channel to thread mappings."""
    return dict(_DB)
