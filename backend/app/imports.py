"""Preview-first, idempotent shop-data import endpoints."""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import PurePath
import uuid

import mysql.connector
from flask import Blueprint, current_app, jsonify, request
from werkzeug.exceptions import HTTPException

from app.data_import import ImportFormatError, MAX_IMPORT_BYTES, build_import_plan, normalize_datasets, parse_import_file
from app.database import DatabaseNotConfiguredError, database_connection
from app.order_service import WorkflowError


imports_blueprint = Blueprint("imports", __name__)


@imports_blueprint.before_request
def require_local_development():
    if current_app.config.get("APP_ENV") != "development":
        return _error("AUTHORIZATION_NOT_CONFIGURED", "Shop-data imports are disabled outside local development until authentication is configured.", 503)


@imports_blueprint.errorhandler(HTTPException)
def handle_http_error(error):
    return _error("HTTP_ERROR", error.description, error.code or 500)


def _error(code, message, status, details=None):
    return jsonify(error={"code": code, "message": message, "details": details or []}), status


def _json(value):
    return json.loads(value) if isinstance(value, (str, bytes, bytearray)) else value


def _summary(batch):
    staged = _json(batch["staged_data"])
    return {
        "importId": batch["id"],
        "source": {"filename": batch["source_filename"], "format": batch["source_format"], "sha256": batch["content_sha256"]},
        "status": batch["status"],
        "allowUpdates": bool(batch["allow_updates"]),
        "summary": _json(batch["summary"]),
        "preview": {"rows": [row for rows in staged.get("plan", {}).values() for row in rows], "errors": staged.get("errors", [])},
    }


@imports_blueprint.post("/imports/preview")
def preview_import():
    upload = request.files.get("file")
    if not upload or not upload.filename:
        return _error("FILE_REQUIRED", "Upload a CSV, XLSX, or PDF file in the file field.", 400)
    update_existing = request.form.get("updateExisting", "false").strip().casefold()
    if update_existing not in {"true", "false"}:
        return _error("INVALID_REQUEST", "updateExisting must be true or false.", 400)
    dataset_type = request.form.get("datasetType") or None
    if dataset_type and dataset_type not in {"customers", "products", "inventory", "prices", "previous_orders"}:
        return _error("INVALID_DATASET_TYPE", "datasetType must be customers, products, inventory, prices, or previous_orders.", 400)
    file_bytes = upload.read(MAX_IMPORT_BYTES + 1)
    if len(file_bytes) > MAX_IMPORT_BYTES:
        return _error("FILE_SIZE_INVALID", f"Import files are limited to {MAX_IMPORT_BYTES // (1024 * 1024)} MB.", 413)
    source_filename = PurePath(upload.filename.replace("\\", "/")).name[:255] or "uploaded-data"
    content_sha = hashlib.sha256(file_bytes).hexdigest()
    allow_updates = update_existing == "true"
    # The same bytes can be intentionally interpreted as different datasets when
    # datasetType is supplied, so include that choice in the idempotency key.
    fingerprint = hashlib.sha256(f"{content_sha}:{dataset_type or 'auto'}:{int(allow_updates)}".encode("ascii")).hexdigest()
    try:
        with database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute("SELECT * FROM data_import_batches WHERE fingerprint = %s", (fingerprint,))
                previous = cursor.fetchone()
                if previous:
                    return jsonify(_summary(previous)), 200
                parsed = parse_import_file(source_filename, file_bytes, dataset_type)
                normalized, row_errors = normalize_datasets(parsed)
                plan = build_import_plan(cursor, normalized, allow_updates, row_errors)
                summary = {
                    **plan["summary"],
                    "source": {"filename": source_filename, "format": parsed["format"], "sha256": content_sha, "extraction": parsed["extraction"]},
                }
                stage = {"datasets": normalized, "plan": plan["plans"], "errors": plan["errors"]}
                batch_id = str(uuid.uuid4())
                status = "previewed" if not plan["errors"] else "needs_correction"
                cursor.execute(
                    """INSERT INTO data_import_batches
                       (id, fingerprint, content_sha256, source_filename, source_format, allow_updates, status, staged_data, summary)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (batch_id, fingerprint, content_sha, source_filename, parsed["format"], allow_updates, status, json.dumps(stage), json.dumps(summary)),
                )
                connection.commit()
                return jsonify({
                    "importId": batch_id,
                    "source": summary["source"],
                    "status": status,
                    "allowUpdates": allow_updates,
                    "summary": summary,
                    "preview": {"rows": [row for rows in plan["plans"].values() for row in rows], "errors": plan["errors"]},
                }), 200
            except ImportFormatError as exc:
                connection.rollback()
                return _error(exc.code, str(exc), 400)
            except mysql.connector.IntegrityError:
                connection.rollback()
                cursor.execute("SELECT * FROM data_import_batches WHERE fingerprint = %s", (fingerprint,))
                previous = cursor.fetchone()
                if previous:
                    return jsonify(_summary(previous)), 200
                raise
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()
    except DatabaseNotConfiguredError:
        return _error("DATABASE_NOT_CONFIGURED", "Import preview requires configured MySQL staging tables.", 503)
    except mysql.connector.Error:
        return _error("DATABASE_UNAVAILABLE", "The import could not be staged. No business data was changed.", 503)


def _same_preview(before_plans, fresh_plans):
    for kind, old_rows in before_plans.items():
        new_rows = fresh_plans.get(kind, [])
        old_map = {(row["sheet"], row["row"]): row for row in old_rows}
        new_map = {(row["sheet"], row["row"]): row for row in new_rows}
        if old_map.keys() != new_map.keys():
            return False
        for ref, old in old_map.items():
            fresh = new_map[ref]
            if old["action"] != fresh["action"] or old.get("before") != fresh.get("before"):
                return False
    return True


def _apply_plan(cursor, import_id, plan):
    for row in plan["customers"]:
        value = row["values"]
        if row["action"] == "insert":
            cursor.execute("""INSERT INTO customers (id, name, credit_limit_minor, credit_used_minor, credit_currency)
                              VALUES (%s, %s, %s, %s, %s)""", (value["id"], value["name"], value["credit_limit_minor"], value["credit_used_minor"], value["credit_currency"]))
        elif row["action"] == "update":
            cursor.execute("""UPDATE customers SET name=%s, credit_limit_minor=%s, credit_used_minor=%s, credit_currency=%s WHERE id=%s""",
                           (value["name"], value["credit_limit_minor"], value["credit_used_minor"], value["credit_currency"], value["id"]))
    for row in plan["products"]:
        value = row["values"]
        if row["action"] == "insert":
            cursor.execute("""INSERT INTO products (id, sku, name, quantity_on_hand, unit, unit_price_minor, price_currency, pack_size, pack_unit)
                              VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                           (value["id"], value["sku"], value["name"], value["quantity_on_hand"], value["unit"], value["unit_price_minor"], value["price_currency"], value["pack_size"], value["pack_unit"]))
        elif row["action"] == "update":
            cursor.execute("""UPDATE products SET name=%s, quantity_on_hand=%s, unit=%s, unit_price_minor=%s,
                              price_currency=%s, pack_size=%s, pack_unit=%s WHERE id=%s""",
                           (value["name"], value["quantity_on_hand"], value["unit"], value["unit_price_minor"], value["price_currency"], value["pack_size"], value["pack_unit"], value["id"]))
    for row in plan["aliases"]:
        if row["action"] == "insert":
            cursor.execute("INSERT INTO product_aliases (product_id, alias) VALUES (%s, %s)", (row["values"]["product_id"], row["values"]["alias"]))
    for row in plan["inventory"]:
        cursor.execute("UPDATE products SET quantity_on_hand=%s WHERE id=%s", (row["values"]["quantity_on_hand"], row["values"]["product_id"]))
    for row in plan["prices"]:
        value = row["values"]
        if "customer_id" in value:
            if row["action"] == "insert":
                cursor.execute("INSERT INTO customer_product_prices (customer_id, product_id, unit_price_minor, currency) VALUES (%s, %s, %s, %s)", (value["customer_id"], value["product_id"], value["unit_price_minor"], value["currency"]))
            elif row["action"] == "update":
                cursor.execute("UPDATE customer_product_prices SET unit_price_minor=%s, currency=%s WHERE customer_id=%s AND product_id=%s", (value["unit_price_minor"], value["currency"], value["customer_id"], value["product_id"]))
        else:
            cursor.execute("UPDATE products SET unit_price_minor=%s, price_currency=%s WHERE id=%s", (value["unit_price_minor"], value["currency"], value["product_id"]))
    imported_orders = 0
    for row in plan["previous_orders"]:
        value = row["values"]
        history_id = str(uuid.uuid4())
        order_date = datetime.fromisoformat(value["order_date"])
        cursor.execute("""INSERT INTO imported_order_history
                          (id, external_order_id, customer_id, order_date, status, total_minor, currency, source_import_id)
                          VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                       (history_id, value["external_order_id"], value["customer_id"], order_date, value["status"], value["total_minor"], value["currency"], import_id))
        for item in value["lines"]:
            cursor.execute("""INSERT INTO imported_order_history_items
                              (imported_order_id, product_id, quantity, unit, unit_price_minor, line_total_minor, currency)
                              VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                           (history_id, item["product_id"], item["quantity"], item["unit"], item["unit_price_minor"], item["line_total_minor"], item["currency"]))
        imported_orders += 1
    return imported_orders


@imports_blueprint.post("/imports/<import_id>/confirm")
def confirm_import(import_id):
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or body.get("confirm") is not True:
        return _error("EXPLICIT_CONFIRMATION_REQUIRED", "Send {\"confirm\": true} after reviewing the preview.", 400)
    key = request.headers.get("Idempotency-Key", "").strip()
    if not key or len(key) > 128:
        return _error("IDEMPOTENCY_KEY_REQUIRED", "Provide an Idempotency-Key of at most 128 characters.", 400)
    try:
        with database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                connection.start_transaction()
                cursor.execute("SELECT * FROM data_import_batches WHERE confirmation_key = %s FOR UPDATE", (key,))
                keyed = cursor.fetchone()
                if keyed:
                    if keyed["id"] != import_id:
                        connection.rollback()
                        return _error("IDEMPOTENCY_CONFLICT", "This key was already used for another import.", 409)
                    connection.commit()
                    return jsonify(_summary(keyed)), 200
                cursor.execute("SELECT * FROM data_import_batches WHERE id = %s FOR UPDATE", (import_id,))
                batch = cursor.fetchone()
                if not batch:
                    connection.rollback()
                    return _error("IMPORT_NOT_FOUND", "Import preview was not found.", 404)
                if batch["status"] == "imported":
                    connection.commit()
                    return jsonify(_summary(batch)), 200
                stage = _json(batch["staged_data"])
                if batch["status"] != "previewed" or stage["errors"]:
                    connection.rollback()
                    return _error("IMPORT_HAS_ERRORS", "Correct all row errors and create a new preview before importing.", 422, stage["errors"])
                fresh = build_import_plan(cursor, stage["datasets"], bool(batch["allow_updates"]))
                if fresh["errors"] or not _same_preview(stage["plan"], fresh["plans"]):
                    connection.rollback()
                    return _error("DATA_CHANGED_SINCE_PREVIEW", "Shop data changed after preview. Create a fresh preview and review it again.", 409, fresh["errors"])
                imported_history = _apply_plan(cursor, import_id, stage["plan"])
                summary = _json(batch["summary"])
                summary["importedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
                summary["historicalOrdersImported"] = imported_history
                cursor.execute("""UPDATE data_import_batches SET status='imported', confirmation_key=%s,
                                  summary=%s, completed_at=CURRENT_TIMESTAMP WHERE id=%s""",
                               (key, json.dumps(summary), import_id))
                connection.commit()
                batch.update(status="imported", confirmation_key=key, summary=json.dumps(summary))
                return jsonify(_summary(batch)), 200
            except mysql.connector.IntegrityError:
                connection.rollback()
                return _error("IMPORT_CONFLICT", "The import conflicted with data written after preview. No business records were imported.", 409)
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()
    except DatabaseNotConfiguredError:
        return _error("DATABASE_NOT_CONFIGURED", "Import confirmation requires configured MySQL.", 503)
    except mysql.connector.Error:
        return _error("DATABASE_UNAVAILABLE", "The import could not be confirmed. No partial import was committed.", 503)
