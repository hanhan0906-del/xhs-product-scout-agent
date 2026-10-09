import sqlite3

from xhs_scout import db


def test_connect_sets_explicit_busy_timeout_and_preserves_pragmas(tmp_path, monkeypatch):
    db_path = tmp_path / "busy-timeout.sqlite3"
    real_connect = sqlite3.connect
    connect_calls = []

    def recording_connect(database, *args, **kwargs):
        connect_calls.append((database, args, kwargs))
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(db.sqlite3, "connect", recording_connect)

    with db.connect(db_path) as conn:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 10_000
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1

    assert len(connect_calls) == 1
    database, args, kwargs = connect_calls[0]
    assert database == db_path
    assert args == ()
    assert kwargs["timeout"] == 10.0
