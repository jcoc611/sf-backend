import sqlite3

from sqlalchemy import create_engine, inspect

from app import database

LEGACY_SCHEMA = """
CREATE TABLE contacts (
    id INTEGER PRIMARY KEY,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    email VARCHAR(320) NOT NULL
)
"""


def test_init_db_adds_photo_to_legacy_database(tmp_path, monkeypatch):
    # A contacts table as written before the photo column existed.
    db_file = tmp_path / "legacy.db"
    with sqlite3.connect(db_file) as connection:
        connection.execute(LEGACY_SCHEMA)
        connection.execute(
            "INSERT INTO contacts (first_name, last_name, email) VALUES ('Ada', 'Lovelace', 'ada@example.com')"
        )

    legacy_engine = create_engine(f"sqlite+pysqlite:///{db_file}")
    monkeypatch.setattr(database, "engine", legacy_engine)

    database.init_db()

    columns = {c["name"] for c in inspect(legacy_engine).get_columns("contacts")}
    assert "photo" in columns

    # Existing rows survive the upgrade and read as no-photo.
    with sqlite3.connect(db_file) as connection:
        row = connection.execute("SELECT first_name, photo FROM contacts").fetchone()
    assert row == ("Ada", None)
