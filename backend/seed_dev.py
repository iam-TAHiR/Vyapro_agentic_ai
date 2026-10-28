"""Safely seed fictional wholesale records into an isolated *_dev MySQL database."""

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import sys

import mysql.connector
from dotenv import load_dotenv

from app import create_app
from app.database import DatabaseNotConfiguredError, database_connection, is_database_configured
from app.dev_seed_data import CUSTOMERS, CUSTOMER_PRICES, HISTORICAL_ORDERS, PRODUCTS, SUBSTITUTIONS


def validate_seed_target(config):
    """Refuse any environment or database that is not explicitly development-only."""
    if config.get("APP_ENV") != "development":
        raise ValueError("Development seeding requires VYAPRO_ENV=development.")
    if not is_database_configured(config):
        raise DatabaseNotConfiguredError("Configure the local MySQL settings in backend/.env first.")
    database_name = str(config.get("MYSQL_DATABASE", "")).casefold()
    if not (database_name.endswith("_dev") or database_name.endswith("_development")):
        raise ValueError("Refusing to seed: MYSQL_DATABASE must end with _dev or _development.")


def _customer(cursor, record):
    identifier, name, credit_limit, credit_used = record
    cursor.execute(
        """SELECT id, name, credit_limit_minor, credit_used_minor, credit_currency
           FROM customers WHERE id=%s OR LOWER(TRIM(name))=LOWER(TRIM(%s))""",
        (identifier, name),
    )
    matches = cursor.fetchall()
    if matches:
        exact = any(
            row["id"] == identifier
            and row["name"] == name
            and int(row["credit_limit_minor"]) == credit_limit
            and int(row["credit_used_minor"]) == credit_used
            and row["credit_currency"] == "INR"
            for row in matches
        )
        return exact, False
    cursor.execute(
        "INSERT INTO customers (id, name, credit_limit_minor, credit_used_minor, credit_currency) VALUES (%s,%s,%s,%s,'INR')",
        (identifier, name, credit_limit, credit_used),
    )
    return True, True


def _product(cursor, record):
    identifier, sku, name, stock, unit, price, pack_size, pack_unit, _aliases = record
    cursor.execute("SELECT id, sku, name, quantity_on_hand, unit, unit_price_minor, price_currency, pack_size, pack_unit FROM products WHERE id=%s OR sku=%s OR LOWER(TRIM(name))=LOWER(TRIM(%s))", (identifier, sku, name))
    matches = cursor.fetchall()
    if matches:
        stock_value = Decimal(stock)
        pack_value = Decimal(pack_size)
        exact = any(
            row["id"] == identifier and row["sku"] == sku and row["name"] == name
            and Decimal(str(row["quantity_on_hand"])) == stock_value and row["unit"] == unit
            and int(row["unit_price_minor"]) == price and row["price_currency"] == "INR"
            and row["pack_size"] is not None and Decimal(str(row["pack_size"])) == pack_value
            and row["pack_unit"] == pack_unit
            for row in matches
        )
        return exact, False
    cursor.execute(
        """INSERT INTO products
           (id, sku, name, quantity_on_hand, unit, unit_price_minor, price_currency, pack_size, pack_unit)
           VALUES (%s,%s,%s,%s,%s,%s,'INR',%s,%s)""",
        (identifier, sku, name, stock, unit, price, pack_size, pack_unit),
    )
    return True, True


def _insert_if_missing(cursor, query, exists_query, params, exists_params=None):
    cursor.execute(exists_query, params if exists_params is None else exists_params)
    if cursor.fetchone():
        return False
    cursor.execute(query, params)
    return True


def _historical_order(cursor, number, record, safe_customers, safe_products):
    customer_id, date_text, status, lines = record
    order_id = f"DEV-ORDER-{number:03d}"
    proposal_id = f"DEV-PROP-{number:03d}"
    key = f"vyapro-dev-seed-v1-{number:03d}"
    if customer_id not in safe_customers or any(line[0] not in safe_products for line in lines):
        return False
    cursor.execute(
        "SELECT id FROM orders WHERE id=%s OR proposal_id=%s OR idempotency_key=%s",
        (order_id, proposal_id, key),
    )
    if cursor.fetchone():
        return False

    customer = next(item for item in CUSTOMERS if item[0] == customer_id)
    line_payloads = []
    total_minor = 0
    for product_id, quantity_text, unit_price in lines:
        product = next(item for item in PRODUCTS if item[0] == product_id)
        quantity = Decimal(quantity_text)
        line_total = int((quantity * Decimal(unit_price)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        total_minor += line_total
        line_payloads.append({
            "productText": product[2], "quantity": quantity_text, "unitText": product[4],
            "productId": product_id, "unitPriceMinor": unit_price, "lineTotalMinor": line_total,
        })
    date_value = datetime.strptime(date_text, "%Y-%m-%d")
    original_text = "Imported historical wholesale purchase: " + "; ".join(
        f"{line['quantity']} {line['unitText']} {line['productText']}" for line in line_payloads
    )
    interpretation = {
        "customerText": customer[1],
        "items": [{"productText": line["productText"], "quantity": line["quantity"], "unitText": line["unitText"]} for line in line_payloads],
        "deliveryPreference": None,
    }
    request_hash = hashlib.sha256(json.dumps({"orderId": order_id, "interpretation": interpretation}, sort_keys=True).encode("utf-8")).hexdigest()
    cursor.execute(
        """INSERT INTO order_proposals
           (id,idempotency_key,request_hash,source_channel,external_reference,original_text,interpretation,status,version,customer_id,total_minor,currency,validation,created_at,updated_at)
           VALUES (%s,%s,%s,'web',NULL,%s,%s,'committed',2,%s,%s,'INR',%s,%s,%s)""",
        (proposal_id, key, request_hash, original_text, json.dumps(interpretation), customer_id, total_minor,
         json.dumps({"warnings": [], "historicalRecord": True}), date_value, date_value),
    )
    cursor.execute(
        """INSERT INTO orders (id,proposal_id,idempotency_key,customer_id,source_channel,external_reference,status,total_minor,currency,created_at)
           VALUES (%s,%s,%s,%s,'web',NULL,%s,%s,'INR',%s)""",
        (order_id, proposal_id, key, customer_id, status, total_minor, date_value),
    )
    for line, (product_id, quantity_text, unit_price) in zip(line_payloads, lines):
        product = next(item for item in PRODUCTS if item[0] == product_id)
        cursor.execute(
            """INSERT INTO order_proposal_items
               (proposal_id,requested_product_text,requested_quantity,requested_unit,product_id,substitute_product_id,substitution_reason,unit_price_minor,line_total_minor,currency,line_status)
               VALUES (%s,%s,%s,%s,%s,NULL,NULL,%s,%s,'INR','available')""",
            (proposal_id, line["productText"], quantity_text, product[4], product_id, unit_price, line["lineTotalMinor"]),
        )
        cursor.execute(
            """INSERT INTO order_items (order_id,product_id,quantity,unit,unit_price_minor,line_total_minor,currency)
               VALUES (%s,%s,%s,%s,%s,%s,'INR')""",
            (order_id, product_id, quantity_text, product[4], unit_price, line["lineTotalMinor"]),
        )
    cursor.execute(
        """INSERT INTO audit_events (proposal_id,order_id,event_type,actor,source_channel,details,created_at)
           VALUES (%s,%s,'order_imported','shop-data-import','web',%s,%s)""",
        (proposal_id, order_id, json.dumps({"historicalRecord": True, "source": "development business history"}), date_value),
    )
    return True


def _verified_counts(cursor):
    verified_customers = 0
    for identifier, name, limit_minor, used_minor in CUSTOMERS:
        cursor.execute("SELECT id,name,credit_limit_minor,credit_used_minor,credit_currency FROM customers WHERE id=%s", (identifier,))
        row = cursor.fetchone()
        if row and (row["id"], row["name"], int(row["credit_limit_minor"]), int(row["credit_used_minor"]), row["credit_currency"]) == (identifier, name, limit_minor, used_minor, "INR"):
            verified_customers += 1
    verified_products = 0
    for identifier, sku, name, stock, unit, price, pack_size, pack_unit, _aliases in PRODUCTS:
        cursor.execute("SELECT id,sku,name,quantity_on_hand,unit,unit_price_minor,price_currency,pack_size,pack_unit FROM products WHERE id=%s", (identifier,))
        row = cursor.fetchone()
        if row and row["sku"] == sku and row["name"] == name and Decimal(str(row["quantity_on_hand"])) == Decimal(stock) and row["unit"] == unit and int(row["unit_price_minor"]) == price and row["price_currency"] == "INR" and row["pack_size"] is not None and Decimal(str(row["pack_size"])) == Decimal(pack_size) and row["pack_unit"] == pack_unit:
            verified_products += 1
    order_ids = [f"DEV-ORDER-{number:03d}" for number in range(1, len(HISTORICAL_ORDERS) + 1)]
    placeholders = ",".join(["%s"] * len(order_ids))
    cursor.execute(f"SELECT id FROM orders WHERE id IN ({placeholders})", tuple(order_ids))
    verified_orders = len({row["id"] for row in cursor.fetchall()})
    cursor.execute(
        f"SELECT DISTINCT order_id FROM audit_events WHERE event_type='order_imported' AND order_id IN ({placeholders})",
        tuple(order_ids),
    )
    verified_order_events = len({row["order_id"] for row in cursor.fetchall()})
    return {"customers": verified_customers, "products": verified_products, "previousOrders": verified_orders, "orderActivityEvents": verified_order_events}


def seed_development_database(config=None):
    settings = config if config is not None else create_app().config
    validate_seed_target(settings)
    inserted = {"customers": 0, "products": 0, "aliases": 0, "substitutions": 0, "customerPrices": 0, "historicalOrders": 0}
    skipped = {key: 0 for key in inserted}
    with database_connection(settings) as connection:
        cursor = connection.cursor(dictionary=True)
        try:
            connection.start_transaction()
            safe_customers = set()
            for record in CUSTOMERS:
                safe, created = _customer(cursor, record)
                if safe:
                    safe_customers.add(record[0])
                inserted["customers"] += int(created)
                skipped["customers"] += int(not created)
            safe_products = set()
            for record in PRODUCTS:
                safe, created = _product(cursor, record)
                if safe:
                    safe_products.add(record[0])
                inserted["products"] += int(created)
                skipped["products"] += int(not created)
            for product_id, _sku, _name, _stock, _unit, _price, _pack_size, _pack_unit, aliases in PRODUCTS:
                if product_id not in safe_products:
                    skipped["aliases"] += len(aliases)
                    continue
                for alias in aliases:
                    created = _insert_if_missing(
                        cursor,
                        "INSERT INTO product_aliases (product_id,alias) VALUES (%s,%s)",
                        "SELECT id FROM product_aliases WHERE LOWER(alias)=LOWER(%s) LIMIT 1",
                        (product_id, alias),
                        (alias,),
                    )
                    inserted["aliases"] += int(created)
                    skipped["aliases"] += int(not created)
            for product_id, substitute_id, reason in SUBSTITUTIONS:
                if product_id not in safe_products or substitute_id not in safe_products:
                    skipped["substitutions"] += 1
                    continue
                created = _insert_if_missing(
                    cursor,
                    "INSERT INTO product_substitutions (product_id,substitute_product_id,reason) VALUES (%s,%s,%s)",
                    "SELECT product_id FROM product_substitutions WHERE product_id=%s AND substitute_product_id=%s",
                    (product_id, substitute_id, reason),
                    (product_id, substitute_id),
                )
                inserted["substitutions"] += int(created)
                skipped["substitutions"] += int(not created)
            for customer_id, product_id, unit_price, currency in CUSTOMER_PRICES:
                if customer_id not in safe_customers or product_id not in safe_products:
                    skipped["customerPrices"] += 1
                    continue
                created = _insert_if_missing(
                    cursor,
                    "INSERT INTO customer_product_prices (customer_id,product_id,unit_price_minor,currency) VALUES (%s,%s,%s,%s)",
                    "SELECT customer_id FROM customer_product_prices WHERE customer_id=%s AND product_id=%s",
                    (customer_id, product_id, unit_price, currency),
                    (customer_id, product_id),
                )
                inserted["customerPrices"] += int(created)
                skipped["customerPrices"] += int(not created)
            for number, order in enumerate(HISTORICAL_ORDERS, start=1):
                created = _historical_order(cursor, number, order, safe_customers, safe_products)
                inserted["historicalOrders"] += int(created)
                skipped["historicalOrders"] += int(not created)
            connection.commit()
            verified = _verified_counts(cursor)
            return {"environment": "development", "database": settings["MYSQL_DATABASE"], "inserted": inserted, "skippedExistingOrConflicting": skipped, "verified": verified}
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()


def main():
    load_dotenv()
    try:
        result = seed_development_database(create_app().config)
    except (ValueError, DatabaseNotConfiguredError, mysql.connector.Error) as error:
        print(f"Development seed failed safely: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
