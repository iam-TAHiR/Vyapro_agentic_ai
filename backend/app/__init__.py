"""Flask application factory for the Vyapro API."""

import os
from pathlib import Path

from flask import Flask
from dotenv import load_dotenv

from app.database import database_blueprint
from app.catalog import catalog_blueprint
from app.health import health_blueprint

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def create_app(test_config: dict | None = None) -> Flask:
    """Create the app and load safe settings from the environment."""
    app = Flask(__name__)
    app.config.from_mapping(
        APP_ENV=os.getenv("VYAPRO_ENV", "development"),
        DEBUG=_env_bool("VYAPRO_DEBUG"),
        MYSQL_HOST=os.getenv("MYSQL_HOST", ""),
        MYSQL_PORT=os.getenv("MYSQL_PORT", "3306"),
        MYSQL_DATABASE=os.getenv("MYSQL_DATABASE", ""),
        MYSQL_USER=os.getenv("MYSQL_USER", ""),
        MYSQL_PASSWORD=os.getenv("MYSQL_PASSWORD", ""),
        MYSQL_CONNECT_TIMEOUT=int(os.getenv("MYSQL_CONNECT_TIMEOUT", "3")),
        LLM_API_KEY=os.getenv("VYAPRO_LLM_API_KEY", ""),
        LLM_BASE_URL=os.getenv("VYAPRO_LLM_BASE_URL", "").rstrip("/"),
        LLM_MODEL=os.getenv("VYAPRO_LLM_MODEL", ""),
        LLM_TIMEOUT=int(os.getenv("VYAPRO_LLM_TIMEOUT", "20")),
        TRANSCRIPTION_MODEL=os.getenv("VYAPRO_TRANSCRIPTION_MODEL", ""),
        AGENT_MAX_ITERATIONS=int(os.getenv("VYAPRO_AGENT_MAX_ITERATIONS", "5")),
        AGENT_MAX_SECONDS=int(os.getenv("VYAPRO_AGENT_MAX_SECONDS", "45")),
        AGENT_AUTONOMOUS_ROUTINE_ORDERS=_env_bool("VYAPRO_AGENT_AUTONOMOUS_ROUTINE_ORDERS"),
        AGENT_AUTONOMOUS_MAX_MINOR=int(os.getenv("VYAPRO_AGENT_AUTONOMOUS_MAX_MINOR", "0")),
        MAX_CONTENT_LENGTH=20 * 1024 * 1024,
    )

    if test_config:
        app.config.update(test_config)

    app.register_blueprint(health_blueprint, url_prefix="/api/v1")
    app.register_blueprint(database_blueprint, url_prefix="/api/v1")
    app.register_blueprint(catalog_blueprint, url_prefix="/api/v1")
    from app.orders import orders_blueprint
    from app.imports import imports_blueprint

    app.register_blueprint(orders_blueprint, url_prefix="/api/v1")
    app.register_blueprint(imports_blueprint, url_prefix="/api/v1")
    return app
