"""Read-only customer and inventory endpoints backed by MySQL."""

from decimal import Decimal
import uuid

import mysql.connector
from flask import Blueprint, current_app, jsonify

from app.database import DatabaseNotConfiguredError, database_connection


catalog_blueprint = Blueprint("catalog", __name__)


@catalog_blueprint.before_request
def require_local_development():
    if current_app.config.get("APP_ENV") != "development":
        return _database_error("AUTHORIZATION_NOT_CONFIGURED", "Customer and inventory APIs are disabled outside local development until authentication is configured.", 503)


def _fetch_rows(query):
    with database_connection() as connection:
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(query)
            return cursor.fetchall()
        finally:
            cursor.close()


def _database_error(code, message, status=503):
    return jsonify(
        error={
            "code": code,
            "message": message,
            "requestId": str(uuid.uuid4()),
            "details": [],
        }
    ), status


@catalog_blueprint.get("/customers")
def list_customers():
    try:
        rows = _fetch_rows(
            """SELECT id, name, credit_limit_minor, credit_used_minor, credit_currency
               FROM customers ORDER BY name, id"""
        )
    except DatabaseNotConfiguredError:
        return _database_error("DATABASE_NOT_CONFIGURED", "Customer data is not configured.")
    except mysql.connector.Error:
        return _database_error("DATABASE_UNAVAILABLE", "Customer data is temporarily unavailable.")

    customers = [
        {
            "id": row["id"],
            "name": row["name"],
            "creditLimit": {
                "amountMinor": int(row["credit_limit_minor"]),
                "currency": row["credit_currency"],
            },
            "creditUsed": {
                "amountMinor": int(row["credit_used_minor"]),
                "currency": row["credit_currency"],
            },
        }
        for row in rows
    ]
    return jsonify(customers=customers), 200


@catalog_blueprint.get("/inventory")
def list_inventory():
    try:
        rows = _fetch_rows(
            """SELECT id, sku, name, quantity_on_hand, unit,
                      unit_price_minor, price_currency
               FROM products ORDER BY name, sku"""
        )
    except DatabaseNotConfiguredError:
        return _database_error("DATABASE_NOT_CONFIGURED", "Inventory data is not configured.")
    except mysql.connector.Error:
        return _database_error("DATABASE_UNAVAILABLE", "Inventory data is temporarily unavailable.")

    products = [
        {
            "id": row["id"],
            "sku": row["sku"],
            "name": row["name"],
            "quantityAvailable": format(Decimal(row["quantity_on_hand"]), "f"),
            "unit": row["unit"],
            "unitPrice": {
                "amountMinor": int(row["unit_price_minor"]),
                "currency": row["price_currency"],
            },
        }
        for row in rows
    ]
    return jsonify(products=products), 200
