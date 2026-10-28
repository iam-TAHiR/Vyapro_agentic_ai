"""Apply simple, versioned SQL migrations without changing existing data."""

from pathlib import Path

from app.database import database_connection


MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


def apply_migrations():
    """Create the migration ledger and apply unapplied SQL files in order.

    Each migration file must contain exactly one SQL statement. This keeps the
    runner small and avoids pretending MySQL DDL can be rolled back safely.
    """
    with database_connection() as connection:
        cursor = connection.cursor()
        try:
            cursor.execute(
                """CREATE TABLE IF NOT EXISTS vyapro_schema_migrations (
                    version VARCHAR(255) NOT NULL PRIMARY KEY,
                    applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB"""
            )
            connection.commit()

            cursor.execute("SELECT version FROM vyapro_schema_migrations")
            applied = {row[0] for row in cursor.fetchall()}

            for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
                if path.name in applied:
                    continue
                statement = path.read_text(encoding="utf-8").strip()
                if not statement or statement.startswith("--"):
                    raise ValueError(f"Migration {path.name} is empty or is not executable SQL.")
                cursor.execute(statement)
                cursor.execute(
                    "INSERT INTO vyapro_schema_migrations (version) VALUES (%s)",
                    (path.name,),
                )
                connection.commit()
        finally:
            cursor.close()
