"""Small MySQL connection helper and database health endpoint."""

from contextlib import contextmanager

import mysql.connector
from flask import Blueprint, current_app, jsonify


class DatabaseNotConfiguredError(RuntimeError):
    """Raised when required MySQL settings are missing."""


def is_database_configured(config) -> bool:
    return all(
        config.get(key)
        for key in ("MYSQL_HOST", "MYSQL_DATABASE", "MYSQL_USER", "MYSQL_PASSWORD")
    )


@contextmanager
def database_connection(config=None):
    """Open a configured connection and always close it after use."""
    settings = config if config is not None else current_app.config
    if not is_database_configured(settings):
        raise DatabaseNotConfiguredError("MySQL is not configured.")

    connection = mysql.connector.connect(
        host=settings["MYSQL_HOST"],
        port=int(settings["MYSQL_PORT"]),
        database=settings["MYSQL_DATABASE"],
        user=settings["MYSQL_USER"],
        password=settings["MYSQL_PASSWORD"],
        connection_timeout=int(settings["MYSQL_CONNECT_TIMEOUT"]),
    )
    try:
        cursor = connection.cursor()
        try:
            cursor.execute("SET time_zone = '+00:00'")
        finally:
            cursor.close()
        yield connection
    finally:
        connection.close()


database_blueprint = Blueprint("database", __name__)


@database_blueprint.get("/health/database")
def database_health():
    if not is_database_configured(current_app.config):
        return jsonify(status="not_configured", service="vyapro-database"), 503

    try:
        with database_connection() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            finally:
                cursor.close()
    except Exception:
        # Keep connection details and credentials out of public health responses.
        return jsonify(status="unavailable", service="vyapro-database"), 503

    return jsonify(status="ok", service="vyapro-database"), 200
