from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def _engine_kwargs(database_url: str) -> dict:
    if not database_url.startswith("sqlite"):
        return {}

    kwargs: dict = {"connect_args": {"check_same_thread": False}}
    if ":memory:" in database_url or "mode=memory" in database_url:
        # A plain in-memory SQLite database lives and dies with its connection.
        # StaticPool keeps a single connection alive so every request — and every
        # thread FastAPI hands work to — sees the same data for the process's lifetime.
        kwargs["poolclass"] = StaticPool
    return kwargs


settings = get_settings()

engine = create_engine(
    settings.database_url,
    echo=settings.sql_echo,
    **_engine_kwargs(settings.database_url),
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    if engine.dialect.name != "sqlite":
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def ensure_column(table: str, column: str, definition: str) -> None:
    """Add `column` to `table` when an older database predates it.

    create_all() creates missing tables but never alters existing ones, so a
    persistent database written by an older version gets additive columns here.
    `definition` must be nullable; existing rows read as NULL.
    """
    columns = {c["name"] for c in inspect(engine).get_columns(table)}
    if column in columns:
        return
    with engine.begin() as connection:
        connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))


LEGACY_ADDRESS_COLUMNS = ("address", "city", "state", "postal_code", "country")


def migrate_flat_addresses() -> None:
    """Move pre-relationship address columns on `contacts` into `addresses` rows.

    Databases written before addresses became their own table stored one flat
    address on the contact. Copy any non-empty set into a `home` address, then
    drop the legacy columns. Safe to call repeatedly: once the columns are gone
    there is nothing to do. The column check runs inside the transaction so a
    concurrent startup that already migrated is seen before we act.
    """
    with engine.begin() as connection:
        columns = {c["name"] for c in inspect(connection).get_columns("contacts")}
        present = [c for c in LEGACY_ADDRESS_COLUMNS if c in columns]
        if not present:
            return
        select_cols = ", ".join(present)
        rows = connection.execute(
            text(
                f"SELECT id, {select_cols} FROM contacts WHERE "
                + " OR ".join(f"{c} IS NOT NULL AND {c} != ''" for c in present)
            )
        ).mappings()
        for row in rows:
            values = {c: row[c] for c in present}
            connection.execute(
                text(
                    "INSERT INTO addresses (contact_id, type, street, city, state, postal_code, country) "
                    "VALUES (:contact_id, 'home', :street, :city, :state, :postal_code, :country)"
                ),
                {
                    "contact_id": row["id"],
                    "street": values.get("address"),
                    "city": values.get("city"),
                    "state": values.get("state"),
                    "postal_code": values.get("postal_code"),
                    "country": values.get("country"),
                },
            )
        for column in present:
            connection.execute(text(f"ALTER TABLE contacts DROP COLUMN {column}"))


def init_db() -> None:
    """Create tables and upgrade older schemas. Safe to call repeatedly."""
    from app import models  # noqa: F401  (register models on Base.metadata)

    Base.metadata.create_all(bind=engine)
    ensure_column("contacts", "photo", "TEXT")
    migrate_flat_addresses()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a session that is always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
