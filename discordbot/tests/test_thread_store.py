import shelve
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from discordbot import thread_store


def test_thread_store_roundtrip(tmp_path, monkeypatch):
    db_path = tmp_path / "threads.db"
    with shelve.open(str(db_path)) as db:
        monkeypatch.setattr(thread_store, "_DB", db)
        thread_store.save(123, "456")
        assert thread_store.get(123) == "456"
        assert thread_store.all_items() == {"123": "456"}
        thread_store.delete(123)
        assert thread_store.get(123) is None
