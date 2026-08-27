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


LEGACY_SCHEMA_WITH_ADDRESS = """
CREATE TABLE contacts (
    id INTEGER PRIMARY KEY,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    email VARCHAR(320) NOT NULL,
    address VARCHAR(300),
    city VARCHAR(120),
    state VARCHAR(120),
    postal_code VARCHAR(20),
    country VARCHAR(120)
)
"""


def test_init_db_moves_flat_addresses_into_address_rows(tmp_path, monkeypatch):
    # A contacts table as written when the address was five flat columns.
    db_file = tmp_path / "legacy.db"
    with sqlite3.connect(db_file) as connection:
        connection.execute(LEGACY_SCHEMA_WITH_ADDRESS)
        connection.execute(
            "INSERT INTO contacts (first_name, last_name, email, city, state, country)"
            " VALUES ('Ada', 'Lovelace', 'ada@example.com', 'San Francisco', 'CA', 'USA')"
        )
        connection.execute(
            "INSERT INTO contacts (first_name, last_name, email) VALUES ('Grace', 'Hopper', 'grace@example.com')"
        )

    legacy_engine = create_engine(f"sqlite+pysqlite:///{db_file}")
    monkeypatch.setattr(database, "engine", legacy_engine)

    database.init_db()

    contact_columns = {c["name"] for c in inspect(legacy_engine).get_columns("contacts")}
    assert contact_columns.isdisjoint({"address", "city", "state", "postal_code", "country"})

    with sqlite3.connect(db_file) as connection:
        rows = connection.execute(
            "SELECT contact_id, type, city, state, country FROM addresses"
        ).fetchall()
    assert rows == [(1, "home", "San Francisco", "CA", "USA")]


def test_migrate_flat_addresses_is_idempotent(tmp_path, monkeypatch):
    db_file = tmp_path / "legacy.db"
    with sqlite3.connect(db_file) as connection:
        connection.execute(LEGACY_SCHEMA_WITH_ADDRESS)
        connection.execute(
            "INSERT INTO contacts (first_name, last_name, email, city) VALUES ('Ada', 'Lovelace', 'ada@example.com', 'SF')"
        )

    legacy_engine = create_engine(f"sqlite+pysqlite:///{db_file}")
    monkeypatch.setattr(database, "engine", legacy_engine)

    database.init_db()
    database.init_db()

    with sqlite3.connect(db_file) as connection:
        count = connection.execute("SELECT COUNT(*) FROM addresses").fetchone()[0]
    assert count == 1
