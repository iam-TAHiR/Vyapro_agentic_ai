"""Deterministic MySQL order workflow shared by all future channel adapters."""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import uuid

import mysql.connector

from app.database import database_connection


class WorkflowError(RuntimeError):
    def __init__(self, code, message, status=409):
        super().__init__(message)
        self.code = code
        self.status = status


def _cursor(connection):
    return connection.cursor(dictionary=True)


def _json_value(value):
    return json.loads(value) if isinstance(value, (str, bytes, bytearray)) else value


def _timestamp(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return str(value)


def _money(amount, currency):
    if amount is None or currency is None:
        return None
    return {"amountMinor": int(amount), "currency": currency}


def _line_total(quantity, unit_price_minor):
    return int((quantity * Decimal(int(unit_price_minor))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def request_fingerprint(text, source_channel, external_reference):
    return hashlib.sha256(
        json.dumps({"text": text, "source": source_channel, "externalReference": external_reference}, sort_keys=True).encode("utf-8")
    ).hexdigest()


def find_idempotent_proposal(text, source_channel, external_reference, idempotency_key, request_hash_override=None):
    fingerprint = request_hash_override or request_fingerprint(text, source_channel, external_reference)
    with database_connection() as connection:
        cursor = _cursor(connection)
        try:
            cursor.execute("SELECT id, request_hash FROM order_proposals WHERE idempotency_key = %s", (idempotency_key,))
            existing = cursor.fetchone()
            if not existing:
                return None
            if existing["request_hash"] != fingerprint:
                raise WorkflowError("IDEMPOTENCY_CONFLICT", "This idempotency key was already used for a different request.", 409)
            return _get_proposal(cursor, existing["id"])
        finally:
            cursor.close()


def _audit(cursor, event_type, source_channel, details, proposal_id=None, order_id=None, actor="system"):
    cursor.execute(
        """INSERT INTO audit_events
           (proposal_id, order_id, event_type, actor, source_channel, details)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (proposal_id, order_id, event_type, actor, source_channel, json.dumps(details)),
    )


def _lookup_customer(cursor, customer_text, lock=False):
    if not customer_text:
        return []
    cursor.execute(
        """SELECT id, name, credit_limit_minor, credit_used_minor, credit_currency
           FROM customers WHERE LOWER(TRIM(name)) = LOWER(TRIM(%s)) ORDER BY id LIMIT 2"""
        + (" FOR UPDATE" if lock else ""),
        (customer_text,),
    )
    return cursor.fetchall()


def _lookup_product(cursor, text, lock=False):
    cursor.execute(
        """SELECT id, sku, name, quantity_on_hand, unit, unit_price_minor, price_currency
           FROM products WHERE LOWER(name) = LOWER(%s) OR LOWER(sku) = LOWER(%s)
           OR EXISTS (SELECT 1 FROM product_aliases a
                      WHERE a.product_id = products.id AND LOWER(a.alias) = LOWER(%s))
           ORDER BY id LIMIT 2""" + (" FOR UPDATE" if lock else ""),
        (text, text, text),
    )
    return cursor.fetchall()


def _lookup_product_by_id(cursor, product_id, lock=False):
    cursor.execute(
        """SELECT id, sku, name, quantity_on_hand, unit, unit_price_minor, price_currency
           FROM products WHERE id = %s""" + (" FOR UPDATE" if lock else ""),
        (product_id,),
    )
    product = cursor.fetchone()
    return [product] if product else []


def _product_payload(product):
    return {
        "id": product["id"],
        "sku": product["sku"],
        "name": product["name"],
        "quantityAvailable": format(Decimal(product["quantity_on_hand"]), "f"),
        "unit": product["unit"],
        "unitPrice": _money(product["unit_price_minor"], product["price_currency"]),
    }


def _effective_product_price(cursor, customer_id, product):
    if not customer_id:
        return product, False
    cursor.execute(
        """SELECT unit_price_minor, currency FROM customer_product_prices
           WHERE customer_id = %s AND product_id = %s""",
        (customer_id, product["id"]),
    )
    override = cursor.fetchone()
    if not override:
        return product, False
    return {**product, "unit_price_minor": override["unit_price_minor"], "price_currency": override["currency"]}, True


def lookup_customer_by_name(name):
    with database_connection() as connection:
        cursor = _cursor(connection)
        try:
            matches = _lookup_customer(cursor, name)
            return [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "creditLimit": _money(row["credit_limit_minor"], row["credit_currency"]),
                    "creditUsed": _money(row["credit_used_minor"], row["credit_currency"]),
                }
                for row in matches
            ]
        finally:
            cursor.close()


def get_customer_by_id(customer_id):
    """Return the minimal registered identity for a selected customer account."""
    with database_connection() as connection:
        cursor = _cursor(connection)
        try:
            cursor.execute("SELECT id, name FROM customers WHERE id = %s", (customer_id,))
            return cursor.fetchone()
        finally:
            cursor.close()


def match_products(query):
    with database_connection() as connection:
        cursor = _cursor(connection)
        try:
            return [_product_payload(row) for row in _lookup_product(cursor, query)]
        finally:
            cursor.close()


def get_product_by_id(product_id):
    with database_connection() as connection:
        cursor = _cursor(connection)
        try:
            cursor.execute(
                """SELECT id, sku, name, quantity_on_hand, unit, unit_price_minor, price_currency
                   FROM products WHERE id = %s""",
                (product_id,),
            )
            product = cursor.fetchone()
            return _product_payload(product) if product else None
        finally:
            cursor.close()


def get_customer_pricing(customer_name, product_id):
    """Return the authoritative customer-specific price or catalog fallback."""
    with database_connection() as connection:
        cursor = _cursor(connection)
        try:
            customers = _lookup_customer(cursor, customer_name)
            if len(customers) != 1:
                return {"customerMatched": False, "matches": len(customers), "product": None}
            cursor.execute(
                """SELECT id, sku, name, quantity_on_hand, unit, unit_price_minor, price_currency
                   FROM products WHERE id = %s""",
                (product_id,),
            )
            product = cursor.fetchone()
            customer_specific = False
            if product:
                product, customer_specific = _effective_product_price(cursor, customers[0]["id"], product)
            return {
                "customerMatched": True,
                "customerId": customers[0]["id"],
                "product": _product_payload(product) if product else None,
                "priceSource": "customer_specific" if customer_specific else "catalog",
                "note": "Price is read from the customer price record or the catalog fallback.",
            }
        finally:
            cursor.close()


def get_customer_order_history(customer_name, limit=10):
    with database_connection() as connection:
        cursor = _cursor(connection)
        try:
            customers = _lookup_customer(cursor, customer_name)
            if len(customers) != 1:
                return {"customerMatched": False, "matches": len(customers), "orders": []}
            customer = customers[0]
            cursor.execute(
                """SELECT o.*, c.name AS customer_name, p.interpretation,
                          COALESCE((SELECT SUM(oi.remaining_quantity) FROM order_items oi WHERE oi.order_id = o.id), 0) AS pending_quantity
                   FROM orders o
                   JOIN customers c ON c.id = o.customer_id
                   JOIN order_proposals p ON p.id = o.proposal_id
                   WHERE o.customer_id = %s ORDER BY o.created_at DESC, o.id DESC LIMIT %s""",
                (customer["id"], limit),
            )
            return {
                "customerMatched": True,
                "customer": {"id": customer["id"], "name": customer["name"]},
                "orders": [_order_summary(row) for row in cursor.fetchall()],
            }
        finally:
            cursor.close()


def get_customer_order_history_by_id(customer_id, limit=10):
    """Read only the selected customer account's orders, without name matching."""
    with database_connection() as connection:
        cursor = _cursor(connection)
        try:
            cursor.execute("SELECT id, name FROM customers WHERE id = %s", (customer_id,))
            customer = cursor.fetchone()
            if not customer:
                return {"customerMatched": False, "orders": []}
            cursor.execute(
                """SELECT o.*, c.name AS customer_name, p.interpretation,
                          COALESCE((SELECT SUM(oi.remaining_quantity) FROM order_items oi WHERE oi.order_id = o.id), 0) AS pending_quantity
                   FROM orders o
                   JOIN customers c ON c.id = o.customer_id
                   JOIN order_proposals p ON p.id = o.proposal_id
                   WHERE o.customer_id = %s ORDER BY o.created_at DESC, o.id DESC LIMIT %s""",
                (customer["id"], limit),
            )
            return {
                "customerMatched": True,
                "customer": {"id": customer["id"], "name": customer["name"]},
                "orders": [_order_summary(row) for row in cursor.fetchall()],
            }
        finally:
            cursor.close()


def get_credit_check(customer_name, items):
    """Calculate a requested total from live catalog data; never trust model-supplied prices."""
    with database_connection() as connection:
        cursor = _cursor(connection)
        try:
            customers = _lookup_customer(cursor, customer_name)
            if len(customers) != 1:
                return {"customerMatched": False, "matches": len(customers), "eligible": False}
            customer = customers[0]
            total = 0
            currency = None
            problems = []
            for item in items:
                matches = _lookup_product(cursor, item["product"])
                if len(matches) != 1:
                    problems.append("PRODUCT_UNMATCHED")
                    continue
                product = matches[0]
                product, _customer_specific = _effective_product_price(cursor, customer["id"], product)
                quantity = Decimal(str(item["quantity"]))
                if product["unit"].casefold() != item["unit"].casefold():
                    problems.append("UNIT_MISMATCH")
                if Decimal(product["quantity_on_hand"]) < quantity:
                    problems.append("INSUFFICIENT_STOCK")
                if currency and currency != product["price_currency"]:
                    problems.append("CURRENCY_MISMATCH")
                currency = product["price_currency"]
                total += _line_total(quantity, product["unit_price_minor"])
            if currency and currency != customer["credit_currency"]:
                problems.append("CURRENCY_MISMATCH")
            available = int(customer["credit_limit_minor"]) - int(customer["credit_used_minor"])
            if not problems and total > available:
                problems.append("CREDIT_LIMIT_EXCEEDED")
            return {
                "customerMatched": True,
                "eligible": not problems,
                "projectedTotal": _money(total, currency),
                "availableCredit": _money(available, customer["credit_currency"]),
                "issues": sorted(set(problems)),
            }
        finally:
            cursor.close()


def get_substitution_options(product_id, quantity):
    with database_connection() as connection:
        cursor = _cursor(connection)
        try:
            cursor.execute(
                """SELECT id, sku, name, quantity_on_hand, unit, unit_price_minor, price_currency
                   FROM products WHERE id = %s""",
                (product_id,),
            )
            product = cursor.fetchone()
            if not product:
                return {"productFound": False, "options": []}
            cursor.execute(
                """SELECT p.id, p.sku, p.name, p.quantity_on_hand, p.unit,
                          p.unit_price_minor, p.price_currency, s.reason
                   FROM product_substitutions s JOIN products p ON p.id = s.substitute_product_id
                   WHERE s.product_id = %s AND p.quantity_on_hand >= %s AND p.unit = %s
                   ORDER BY p.name, p.id""",
                (product_id, Decimal(str(quantity)), product["unit"]),
            )
            return {
                "productFound": True,
                "options": [
                    {**_product_payload(row), "reason": row["reason"], "requiresApproval": True}
                    for row in cursor.fetchall()
                ],
            }
        finally:
            cursor.close()


def _find_substitute(cursor, product, quantity):
    cursor.execute(
        """SELECT p.id, p.sku, p.name, p.quantity_on_hand, p.unit,
                  p.unit_price_minor, p.price_currency, s.reason
           FROM product_substitutions s
           JOIN products p ON p.id = s.substitute_product_id
           WHERE s.product_id = %s AND p.quantity_on_hand >= %s AND p.unit = %s
           ORDER BY p.name, p.id LIMIT 1""",
        (product["id"], quantity, product["unit"]),
    )
    return cursor.fetchone()


def _evaluate(cursor, interpretation, source_channel, external_reference):
    warnings = []
    selected_customer_id = interpretation.get("customerId")
    if selected_customer_id:
        cursor.execute(
            """SELECT id, name, credit_limit_minor, credit_used_minor, credit_currency
               FROM customers WHERE id = %s""",
            (selected_customer_id,),
        )
        selected_customer = cursor.fetchone()
        customers = [selected_customer] if selected_customer else []
    else:
        customers = _lookup_customer(cursor, interpretation.get("customerText"))
    customer = customers[0] if len(customers) == 1 else None
    if not customers:
        warnings.append({"code": "CUSTOMER_NOT_FOUND", "message": "Customer could not be matched. Enter the exact customer name.", "requiresUserAction": True})
    elif len(customers) > 1:
        warnings.append({"code": "CUSTOMER_AMBIGUOUS", "message": "More than one customer matches. Provide a more specific customer name.", "requiresUserAction": True})

    lines = []
    total = 0
    currency = None
    unresolved = False
    for requested in interpretation["items"]:
        quantity = Decimal(requested["quantity"])
        matches = (
            _lookup_product_by_id(cursor, requested["productId"])
            if requested.get("productId")
            else _lookup_product(cursor, requested["productText"])
        )
        product = matches[0] if len(matches) == 1 else None
        line = {
            "requested_product_text": requested["productText"],
            "requested_quantity": quantity,
            "requested_unit": requested["unitText"],
            "product": product,
            "substitute": None,
            "price_product": None,
            "offered_quantity": None,
            "line_status": "unresolved",
            "line_total_minor": None,
        }
        if not matches:
            warnings.append({"code": "PRODUCT_NOT_FOUND", "message": f"Product '{requested['productText']}' could not be matched.", "requiresUserAction": True})
            unresolved = True
        elif len(matches) > 1:
            warnings.append({"code": "PRODUCT_AMBIGUOUS", "message": f"Product '{requested['productText']}' has multiple matches.", "requiresUserAction": True})
            unresolved = True
        elif product["unit"].casefold() != requested["unitText"].casefold():
            warnings.append({"code": "UNIT_MISMATCH", "message": f"'{product['name']}' is stocked by {product['unit']}, not {requested['unitText']}.", "requiresUserAction": True})
            unresolved = True
        elif Decimal(product["quantity_on_hand"]) < quantity:
            alternative = _find_substitute(cursor, product, quantity)
            if alternative:
                line["substitute"] = alternative
                line["offered_quantity"] = quantity
                line["line_status"] = "substitution_suggested"
                warnings.append({"code": "SUBSTITUTION_PROPOSED", "message": f"{product['name']} has insufficient stock; {alternative['name']} is suggested: {alternative['reason']}", "requiresUserAction": True})
            elif Decimal(product["quantity_on_hand"]) > 0:
                line["offered_quantity"] = Decimal(product["quantity_on_hand"])
                line["line_status"] = "partial_available"
                remaining = quantity - line["offered_quantity"]
                warnings.append({"code": "PARTIAL_FULFILLMENT_OFFERED", "message": f"Only {format(line['offered_quantity'], 'f')} {product['unit']} of {product['name']} are available. You can accept that quantity now and leave {format(remaining, 'f')} {product['unit']} pending. No restock date is confirmed.", "requiresUserAction": True})
            else:
                line["line_status"] = "insufficient_stock"
                warnings.append({"code": "INSUFFICIENT_STOCK", "message": f"Insufficient stock for {product['name']} and no approved substitution is available.", "requiresUserAction": True})
                unresolved = True
        else:
            line["offered_quantity"] = quantity
            line["line_status"] = "available"

        priced_product = line["substitute"] or (product if line["line_status"] == "available" else None)
        if line["line_status"] == "partial_available":
            priced_product = product
        if priced_product:
            priced_product, _customer_specific = _effective_product_price(
                cursor, customer["id"] if customer else None, priced_product
            )
            line["price_product"] = priced_product
            line["line_total_minor"] = _line_total(line["offered_quantity"], priced_product["unit_price_minor"])
            total += line["line_total_minor"]
            if currency is None:
                currency = priced_product["price_currency"]
            elif currency != priced_product["price_currency"]:
                warnings.append({"code": "CURRENCY_MISMATCH", "message": "Order items use different currencies and cannot be totaled.", "requiresUserAction": True})
                unresolved = True
        lines.append(line)

    if customer and currency and customer["credit_currency"] != currency:
        warnings.append({"code": "CURRENCY_MISMATCH", "message": "Customer credit and product prices use different currencies.", "requiresUserAction": True})
        unresolved = True
    elif customer and currency and total + int(customer["credit_used_minor"]) > int(customer["credit_limit_minor"]):
        warnings.append({"code": "CREDIT_LIMIT_EXCEEDED", "message": "This order would exceed the customer's available credit.", "requiresUserAction": True})
        unresolved = True

    proposal_status = "needs_clarification" if unresolved or not customer else "needs_review"
    return {
        "customer": customer,
        "lines": lines,
        "warnings": warnings,
        "status": proposal_status,
        "total_minor": total if all(line["line_total_minor"] is not None for line in lines) and lines else None,
        "currency": currency,
        "source_channel": source_channel,
        "external_reference": external_reference,
    }


def _save_lines(cursor, proposal_id, lines):
    for line in lines:
        product = line["product"]
        substitute = line["substitute"]
        price_product = line.get("price_product") or substitute or product
        cursor.execute(
            """INSERT INTO order_proposal_items
               (proposal_id, requested_product_text, requested_quantity, offered_quantity, requested_unit,
                product_id, substitute_product_id, substitution_reason, unit_price_minor,
                line_total_minor, currency, line_status)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                proposal_id,
                line["requested_product_text"],
                line["requested_quantity"],
                line.get("offered_quantity", line["requested_quantity"] if line["line_status"] in {"available", "substitution_suggested"} else None),
                line["requested_unit"],
                product["id"] if product else None,
                substitute["id"] if substitute else None,
                substitute["reason"] if substitute else None,
                price_product["unit_price_minor"] if price_product else None,
                line["line_total_minor"],
                price_product["price_currency"] if price_product else None,
                line["line_status"],
            ),
        )


def _validation_audit_details(evaluated):
    customer = evaluated["customer"]
    return {
        "customerMatched": bool(customer),
        "creditLimitMinor": int(customer["credit_limit_minor"]) if customer else None,
        "creditUsedMinor": int(customer["credit_used_minor"]) if customer else None,
        "creditCurrency": customer["credit_currency"] if customer else None,
        "items": [
            {
                "requestedProduct": line["requested_product_text"],
                "status": line["line_status"],
                "offeredQuantity": format(Decimal(line["offered_quantity"]), "f") if line["offered_quantity"] is not None else "0",
                "remainingQuantity": format(max(Decimal(line["requested_quantity"]) - Decimal(line["offered_quantity"] or 0), Decimal("0")), "f"),
                "matchedProductId": line["product"]["id"] if line["product"] else None,
                "availableQuantity": format(Decimal(line["product"]["quantity_on_hand"]), "f") if line["product"] else None,
                "substituteProductId": line["substitute"]["id"] if line["substitute"] else None,
                "substituteAvailableQuantity": format(Decimal(line["substitute"]["quantity_on_hand"]), "f") if line["substitute"] else None,
                "lineTotalMinor": line["line_total_minor"],
            }
            for line in evaluated["lines"]
        ],
        "warningCodes": [warning["code"] for warning in evaluated["warnings"]],
    }


def _get_proposal(cursor, proposal_id):
    cursor.execute(
        """SELECT p.*, c.name AS customer_name
           FROM order_proposals p LEFT JOIN customers c ON c.id = p.customer_id
           WHERE p.id = %s""",
        (proposal_id,),
    )
    proposal = cursor.fetchone()
    if not proposal:
        return None
    cursor.execute(
        """SELECT i.*, p.id AS matched_id, p.sku AS matched_sku, p.name AS matched_name,
                  p.quantity_on_hand AS matched_quantity, p.unit AS matched_unit,
                  p.unit_price_minor AS matched_price, p.price_currency AS matched_currency,
                  s.id AS substitute_id, s.sku AS substitute_sku, s.name AS substitute_name,
                  s.quantity_on_hand AS substitute_quantity, s.unit AS substitute_unit,
                  s.unit_price_minor AS substitute_price, s.price_currency AS substitute_currency
           FROM order_proposal_items i
           LEFT JOIN products p ON p.id = i.product_id
           LEFT JOIN products s ON s.id = i.substitute_product_id
           WHERE i.proposal_id = %s ORDER BY i.id""",
        (proposal_id,),
    )
    items = []
    for row in cursor.fetchall():
        offered_quantity = row.get("offered_quantity")
        if offered_quantity is None:
            offered_quantity = row["requested_quantity"] if row["line_status"] in {"available", "substitution_suggested"} else Decimal("0")
        offered_quantity = Decimal(offered_quantity)
        requested = {
            "productText": row["requested_product_text"],
            "quantity": format(Decimal(row["requested_quantity"]), "f"),
            "unit": row["requested_unit"],
        }
        matched = None
        if row["matched_id"]:
            matched = {"id": row["matched_id"], "sku": row["matched_sku"], "name": row["matched_name"]}
        substitution = None
        if row["substitute_id"]:
            substitution = {
                "product": {"id": row["substitute_id"], "sku": row["substitute_sku"], "name": row["substitute_name"]},
                "reason": row["substitution_reason"],
                "requiresApproval": True,
            }
        selected = row["substitute_id"] and {
            "quantityAvailable": format(Decimal(row["substitute_quantity"]), "f"),
            "unit": row["substitute_unit"],
            "unitPrice": _money(row["unit_price_minor"], row["currency"]),
        } or (row["matched_id"] and {
            "quantityAvailable": format(Decimal(row["matched_quantity"]), "f"),
            "unit": row["matched_unit"],
            "unitPrice": _money(row["unit_price_minor"], row["currency"]),
        })
        items.append({
            "requested": requested,
            "matchedProduct": matched,
            "substitution": substitution,
            "availability": selected,
            "status": row["line_status"],
            "offeredQuantity": format(offered_quantity, "f"),
            "remainingQuantity": format(max(Decimal(row["requested_quantity"]) - offered_quantity, Decimal("0")), "f"),
            "lineTotal": _money(row["line_total_minor"], row["currency"]),
        })
    validation = _json_value(proposal["validation"])
    result = {
        "id": proposal["id"],
        "status": proposal["status"],
        "version": int(proposal["version"]),
        "source": {"channel": proposal["source_channel"], "externalReference": proposal["external_reference"]},
        "interpretation": _json_value(proposal["interpretation"]),
        "matchedCustomer": {"id": proposal["customer_id"], "name": proposal["customer_name"]} if proposal["customer_id"] else None,
        "items": items,
        "validation": validation,
        "total": _money(proposal["total_minor"], proposal["currency"]),
        "createdAt": _timestamp(proposal["created_at"]),
    }
    if proposal["source_channel"] == "voice":
        result["transcript"] = proposal["original_text"]
    return result


def create_proposal(text, source_channel, external_reference, idempotency_key, interpretation, request_hash_override=None):
    request_hash = request_hash_override or request_fingerprint(text, source_channel, external_reference)
    with database_connection() as connection:
        cursor = _cursor(connection)
        try:
            cursor.execute("SELECT id, request_hash FROM order_proposals WHERE idempotency_key = %s", (idempotency_key,))
            existing = cursor.fetchone()
            if existing:
                if existing["request_hash"] != request_hash:
                    raise WorkflowError("IDEMPOTENCY_CONFLICT", "This idempotency key was already used for a different request.", 409)
                return _get_proposal(cursor, existing["id"]), False

            # The idempotency lookup above has already opened MySQL's implicit
            # transaction (the connector uses autocommit=False). Continue it
            # so the lookup, validation, proposal and audit writes stay atomic.
            evaluated = _evaluate(cursor, interpretation, source_channel, external_reference)
            proposal_id = str(uuid.uuid4())
            status = evaluated["status"]
            cursor.execute(
                """INSERT INTO order_proposals
                   (id, idempotency_key, request_hash, source_channel, external_reference,
                    original_text, interpretation, status, version, customer_id, total_minor,
                    currency, validation)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1, %s, %s, %s, %s)""",
                (
                    proposal_id, idempotency_key, request_hash, source_channel, external_reference,
                    text, json.dumps(interpretation), status,
                    evaluated["customer"]["id"] if evaluated["customer"] else None,
                    evaluated["total_minor"], evaluated["currency"],
                    json.dumps({"warnings": evaluated["warnings"]}),
                ),
            )
            _save_lines(cursor, proposal_id, evaluated["lines"])
            _audit(cursor, "order_interpreted", source_channel, {"itemCount": len(interpretation["items"])}, proposal_id=proposal_id)
            _audit(cursor, "order_validation_completed", source_channel, _validation_audit_details(evaluated), proposal_id=proposal_id)
            _audit(cursor, "proposal_created", source_channel, {"status": status}, proposal_id=proposal_id)
            connection.commit()
            return _get_proposal(cursor, proposal_id), True
        except mysql.connector.IntegrityError:
            connection.rollback()
            cursor.execute("SELECT id, request_hash FROM order_proposals WHERE idempotency_key = %s", (idempotency_key,))
            existing = cursor.fetchone()
            if existing and existing["request_hash"] == request_hash:
                return _get_proposal(cursor, existing["id"]), False
            if existing:
                raise WorkflowError("IDEMPOTENCY_CONFLICT", "This idempotency key was already used for a different request.", 409)
            raise
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()


def get_proposal(proposal_id):
    with database_connection() as connection:
        cursor = _cursor(connection)
        try:
            return _get_proposal(cursor, proposal_id)
        finally:
            cursor.close()


def get_clarification_context(proposal_id):
    with database_connection() as connection:
        cursor = _cursor(connection)
        try:
            cursor.execute("SELECT original_text, status, version FROM order_proposals WHERE id = %s", (proposal_id,))
            proposal = cursor.fetchone()
            if not proposal:
                raise WorkflowError("NOT_FOUND", "Order proposal was not found.", 404)
            if proposal["status"] != "needs_clarification":
                raise WorkflowError("INVALID_PROPOSAL_STATE", "This proposal does not need clarification.", 409)
            return proposal
        finally:
            cursor.close()


def find_clarification(proposal_id, answer, idempotency_key):
    fingerprint = hashlib.sha256(answer.strip().encode("utf-8")).hexdigest()
    with database_connection() as connection:
        cursor = _cursor(connection)
        try:
            cursor.execute(
                "SELECT request_hash, proposal_id FROM proposal_clarifications WHERE idempotency_key = %s",
                (idempotency_key,),
            )
            existing = cursor.fetchone()
            if not existing:
                return None
            if existing["proposal_id"] != proposal_id or existing["request_hash"] != fingerprint:
                raise WorkflowError("IDEMPOTENCY_CONFLICT", "This idempotency key was already used for a different clarification.", 409)
            return get_proposal(proposal_id)
        finally:
            cursor.close()


def clarify_proposal(proposal_id, answer, idempotency_key, expected_version, interpretation):
    fingerprint = hashlib.sha256(answer.strip().encode("utf-8")).hexdigest()
    with database_connection() as connection:
        cursor = _cursor(connection)
        try:
            connection.start_transaction()
            cursor.execute("SELECT * FROM order_proposals WHERE id = %s FOR UPDATE", (proposal_id,))
            proposal = cursor.fetchone()
            if not proposal:
                raise WorkflowError("NOT_FOUND", "Order proposal was not found.", 404)
            cursor.execute(
                "SELECT request_hash, proposal_id FROM proposal_clarifications WHERE idempotency_key = %s",
                (idempotency_key,),
            )
            existing = cursor.fetchone()
            if existing:
                if existing["proposal_id"] != proposal_id or existing["request_hash"] != fingerprint:
                    raise WorkflowError("IDEMPOTENCY_CONFLICT", "This idempotency key was already used for a different clarification.", 409)
                connection.commit()
                return _get_proposal(cursor, proposal_id), False
            if int(proposal["version"]) != expected_version or proposal["status"] != "needs_clarification":
                raise WorkflowError("STALE_PROPOSAL", "This proposal changed. Refresh it before clarifying.", 409)

            evaluated = _evaluate(cursor, interpretation, proposal["source_channel"], proposal["external_reference"])
            cursor.execute("DELETE FROM order_proposal_items WHERE proposal_id = %s", (proposal_id,))
            _save_lines(cursor, proposal_id, evaluated["lines"])
            cursor.execute(
                """UPDATE order_proposals SET original_text = CONCAT(original_text, '\nClarification: ', %s),
                   interpretation = %s, status = %s, version = version + 1,
                   customer_id = %s, total_minor = %s, currency = %s, validation = %s WHERE id = %s""",
                (
                    answer.strip(), json.dumps(interpretation), evaluated["status"],
                    evaluated["customer"]["id"] if evaluated["customer"] else None,
                    evaluated["total_minor"], evaluated["currency"],
                    json.dumps({"warnings": evaluated["warnings"]}), proposal_id,
                ),
            )
            cursor.execute(
                """INSERT INTO proposal_clarifications
                   (proposal_id, idempotency_key, request_hash, answer, proposal_version)
                   VALUES (%s, %s, %s, %s, %s)""",
                (proposal_id, idempotency_key, fingerprint, answer.strip(), int(proposal["version"]) + 1),
            )
            _audit(cursor, "clarification_received", proposal["source_channel"], {"newStatus": evaluated["status"]}, proposal_id=proposal_id)
            connection.commit()
            return _get_proposal(cursor, proposal_id), True
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()


def list_proposals(status=None, limit=50, offset=0):
    with database_connection() as connection:
        cursor = _cursor(connection)
        try:
            if status:
                cursor.execute(
                    "SELECT id FROM order_proposals WHERE status = %s ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s",
                    (status, limit + 1, offset),
                )
            else:
                cursor.execute(
                    "SELECT id FROM order_proposals ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s",
                    (limit + 1, offset),
                )
            rows = cursor.fetchall()
            has_more = len(rows) > limit
            proposals = [_get_proposal(cursor, row["id"]) for row in rows[:limit]]
            return proposals, (offset + limit if has_more else None)
        finally:
            cursor.close()


def approve_proposal(proposal_id, accept_substitutions, expected_version, idempotency_key, actor="web-user", accept_partial=False):
    with database_connection() as connection:
        cursor = _cursor(connection)
        try:
            connection.start_transaction()
            cursor.execute("SELECT id, proposal_id FROM orders WHERE idempotency_key = %s FOR UPDATE", (idempotency_key,))
            keyed_order = cursor.fetchone()
            if keyed_order:
                if keyed_order["proposal_id"] != proposal_id:
                    raise WorkflowError("IDEMPOTENCY_CONFLICT", "This idempotency key was already used for another approval.", 409)
                connection.commit()
                return get_order(keyed_order["id"]), False
            cursor.execute("SELECT * FROM order_proposals WHERE id = %s FOR UPDATE", (proposal_id,))
            proposal = cursor.fetchone()
            if not proposal:
                raise WorkflowError("NOT_FOUND", "Order proposal was not found.", 404)

            cursor.execute("SELECT id, customer_id, status, total_minor, currency FROM orders WHERE proposal_id = %s", (proposal_id,))
            existing_order = cursor.fetchone()
            if existing_order:
                connection.commit()
                return get_order(existing_order["id"]), False

            if int(proposal["version"]) != expected_version:
                raise WorkflowError("STALE_PROPOSAL", "This proposal changed. Refresh it before approval.", 409)

            if proposal["status"] != "needs_review":
                raise WorkflowError("INVALID_PROPOSAL_STATE", "This proposal is not ready for approval.", 409)

            cursor.execute("SELECT * FROM order_proposal_items WHERE proposal_id = %s ORDER BY id FOR UPDATE", (proposal_id,))
            lines = cursor.fetchall()
            if not lines or any(line["line_status"] not in {"available", "substitution_suggested", "partial_available"} for line in lines):
                raise WorkflowError("PROPOSAL_BLOCKED", "The proposal contains unresolved items.", 422)
            if any(line["line_status"] == "substitution_suggested" for line in lines) and not accept_substitutions:
                raise WorkflowError("SUBSTITUTION_APPROVAL_REQUIRED", "Review and accept the proposed substitutions before approval.", 422)
            if any(line["line_status"] == "partial_available" for line in lines) and not accept_partial:
                raise WorkflowError("PARTIAL_FULFILLMENT_APPROVAL_REQUIRED", "Explicitly accept the available quantity and pending remainder before approval.", 422)

            cursor.execute(
                """SELECT id, credit_limit_minor, credit_used_minor, credit_currency
                   FROM customers WHERE id = %s FOR UPDATE""",
                (proposal["customer_id"],),
            )
            customer = cursor.fetchone()
            if not customer:
                raise WorkflowError("CUSTOMER_NOT_FOUND", "The matched customer no longer exists.", 409)

            total = 0
            persisted_lines = []
            for line in lines:
                product_id = line["substitute_product_id"] if line["line_status"] == "substitution_suggested" else line["product_id"]
                if line["line_status"] == "substitution_suggested":
                    cursor.execute(
                        """SELECT reason FROM product_substitutions
                           WHERE product_id = %s AND substitute_product_id = %s FOR UPDATE""",
                        (line["product_id"], line["substitute_product_id"]),
                    )
                    approved_mapping = cursor.fetchone()
                    if not approved_mapping or approved_mapping["reason"] != line["substitution_reason"]:
                        raise WorkflowError("SUBSTITUTION_CHANGED", "The approved substitution changed. Review a refreshed proposal.", 409)
                cursor.execute(
                    """SELECT id, quantity_on_hand, unit, unit_price_minor, price_currency
                       FROM products WHERE id = %s FOR UPDATE""",
                    (product_id,),
                )
                product = cursor.fetchone()
                requested_quantity = Decimal(line["requested_quantity"])
                quantity = Decimal(line["offered_quantity"] or 0) if line["line_status"] == "partial_available" else requested_quantity
                if not product or product["unit"].casefold() != line["requested_unit"].casefold():
                    raise WorkflowError("PRODUCT_CHANGED", "A product or unit changed. Create a refreshed proposal before approval.", 409)
                if quantity <= 0 or Decimal(product["quantity_on_hand"]) < quantity:
                    raise WorkflowError("INSUFFICIENT_STOCK", "Stock changed and is no longer sufficient. Create a refreshed proposal.", 409)
                product, _customer_specific = _effective_product_price(cursor, customer["id"], product)
                if product["unit_price_minor"] != line["unit_price_minor"] or product["price_currency"] != line["currency"]:
                    raise WorkflowError("PRICE_CHANGED", "A product price changed. Review a refreshed proposal before approval.", 409)
                cursor.execute("UPDATE products SET quantity_on_hand = quantity_on_hand - %s WHERE id = %s", (quantity, product["id"]))
                line_total = _line_total(quantity, product["unit_price_minor"])
                total += line_total
                persisted_lines.append((product, quantity, requested_quantity, requested_quantity - quantity, line["requested_unit"], line_total))

            if customer["credit_currency"] != proposal["currency"] or int(customer["credit_used_minor"]) + total > int(customer["credit_limit_minor"]):
                raise WorkflowError("CREDIT_LIMIT_EXCEEDED", "Available customer credit is not sufficient. No order was created.", 422)
            if proposal["total_minor"] is not None and int(proposal["total_minor"]) != total:
                raise WorkflowError("TOTAL_CHANGED", "The order total changed. Review a refreshed proposal before approval.", 409)

            order_id = str(uuid.uuid4())
            has_pending = any(remaining > 0 for _product, _quantity, _requested, remaining, _unit, _line_total in persisted_lines)
            cursor.execute(
                """INSERT INTO orders
                   (id, proposal_id, idempotency_key, customer_id, source_channel, external_reference, status, total_minor, currency)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (order_id, proposal_id, idempotency_key, customer["id"], proposal["source_channel"], proposal["external_reference"], "partially_fulfilled" if has_pending else "confirmed", total, proposal["currency"]),
            )
            for product, quantity, _requested_quantity, remaining_quantity, unit, line_total in persisted_lines:
                cursor.execute(
                    """INSERT INTO order_items
                       (order_id, product_id, quantity, remaining_quantity, unit, unit_price_minor, line_total_minor, currency)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    (order_id, product["id"], quantity, remaining_quantity, unit, product["unit_price_minor"], line_total, product["price_currency"]),
                )
            cursor.execute("UPDATE customers SET credit_used_minor = credit_used_minor + %s WHERE id = %s", (total, customer["id"]))
            cursor.execute("UPDATE order_proposals SET status = 'committed', version = version + 1 WHERE id = %s", (proposal_id,))
            event_type = "order_partially_fulfilled" if has_pending else "order_approved_and_created"
            event_details = {
                "totalMinor": total,
                "fulfillment": [
                    {"productId": product["id"], "requestedQuantity": format(requested, "f"), "acceptedQuantity": format(quantity, "f"), "remainingQuantity": format(remaining, "f")}
                    for product, quantity, requested, remaining, _unit, _line_total in persisted_lines
                ],
            }
            _audit(cursor, event_type, proposal["source_channel"], event_details, proposal_id, order_id, actor)
            connection.commit()
            return get_order(order_id), True
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()


def reject_proposal(proposal_id, actor="web-user"):
    with database_connection() as connection:
        cursor = _cursor(connection)
        try:
            connection.start_transaction()
            cursor.execute("SELECT status, source_channel FROM order_proposals WHERE id = %s FOR UPDATE", (proposal_id,))
            proposal = cursor.fetchone()
            if not proposal:
                raise WorkflowError("NOT_FOUND", "Order proposal was not found.", 404)
            if proposal["status"] == "rejected":
                connection.commit()
                return {"id": proposal_id, "status": "rejected"}
            if proposal["status"] not in {"needs_review", "needs_clarification"}:
                raise WorkflowError("INVALID_PROPOSAL_STATE", "This proposal cannot be rejected in its current state.", 409)
            cursor.execute("UPDATE order_proposals SET status = 'rejected', version = version + 1 WHERE id = %s", (proposal_id,))
            _audit(cursor, "proposal_rejected", proposal["source_channel"], {}, proposal_id=proposal_id, actor=actor)
            connection.commit()
            return {"id": proposal_id, "status": "rejected"}
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()


def fulfill_pending_order(order_id, idempotency_key, actor="shopkeeper"):
    """Fulfill currently available portions of an explicitly accepted pending order."""
    with database_connection() as connection:
        cursor = _cursor(connection)
        try:
            connection.start_transaction()
            cursor.execute("SELECT order_id FROM order_fulfillment_operations WHERE idempotency_key = %s FOR UPDATE", (idempotency_key,))
            prior = cursor.fetchone()
            if prior:
                if prior["order_id"] != order_id:
                    raise WorkflowError("IDEMPOTENCY_CONFLICT", "This key was already used for another fulfillment.", 409)
                connection.commit()
                return get_order(order_id), False

            cursor.execute("SELECT * FROM orders WHERE id = %s FOR UPDATE", (order_id,))
            order = cursor.fetchone()
            if not order:
                raise WorkflowError("NOT_FOUND", "Order was not found.", 404)
            if order["status"] != "partially_fulfilled":
                raise WorkflowError("INVALID_ORDER_STATE", "This order has no pending fulfillment.", 409)

            cursor.execute("SELECT id, credit_limit_minor, credit_used_minor, credit_currency FROM customers WHERE id = %s FOR UPDATE", (order["customer_id"],))
            customer = cursor.fetchone()
            cursor.execute("SELECT * FROM order_items WHERE order_id = %s AND remaining_quantity > 0 ORDER BY id FOR UPDATE", (order_id,))
            pending_lines = cursor.fetchall()
            fulfilments = []
            additional_total = 0
            for line in pending_lines:
                cursor.execute("SELECT id, quantity_on_hand, unit FROM products WHERE id = %s FOR UPDATE", (line["product_id"],))
                product = cursor.fetchone()
                if not product or product["unit"].casefold() != line["unit"].casefold():
                    raise WorkflowError("PRODUCT_CHANGED", "A pending product or unit changed. No fulfillment was made.", 409)
                pending = Decimal(line["remaining_quantity"])
                available = Decimal(product["quantity_on_hand"])
                quantity = min(pending, available)
                if quantity <= 0:
                    continue
                line_total = _line_total(quantity, line["unit_price_minor"])
                additional_total += line_total
                fulfilments.append((line, product, quantity, line_total))

            if not fulfilments:
                raise WorkflowError("INSUFFICIENT_STOCK", "No pending quantity is currently in stock. No restock date is recorded.", 409)
            if customer["credit_currency"] != order["currency"] or int(customer["credit_used_minor"]) + additional_total > int(customer["credit_limit_minor"]):
                raise WorkflowError("CREDIT_LIMIT_EXCEEDED", "Available customer credit is not sufficient for this fulfillment. No stock or credit was changed.", 422)

            for line, product, quantity, line_total in fulfilments:
                cursor.execute("UPDATE products SET quantity_on_hand = quantity_on_hand - %s WHERE id = %s", (quantity, product["id"]))
                cursor.execute(
                    """UPDATE order_items SET quantity = quantity + %s,
                              remaining_quantity = remaining_quantity - %s,
                              line_total_minor = line_total_minor + %s WHERE id = %s""",
                    (quantity, quantity, line_total, line["id"]),
                )
            cursor.execute("UPDATE customers SET credit_used_minor = credit_used_minor + %s WHERE id = %s", (additional_total, customer["id"]))
            cursor.execute("UPDATE orders SET total_minor = total_minor + %s WHERE id = %s", (additional_total, order_id))
            cursor.execute("SELECT COALESCE(SUM(remaining_quantity), 0) AS remaining FROM order_items WHERE order_id = %s", (order_id,))
            remaining = Decimal(cursor.fetchone()["remaining"])
            next_status = "partially_fulfilled" if remaining > 0 else "confirmed"
            cursor.execute("UPDATE orders SET status = %s WHERE id = %s", (next_status, order_id))
            cursor.execute("INSERT INTO order_fulfillment_operations (order_id, idempotency_key) VALUES (%s, %s)", (order_id, idempotency_key))
            details = {
                "status": next_status,
                "additionalTotalMinor": additional_total,
                "remainingQuantity": format(remaining, "f"),
                "fulfilled": [
                    {"productId": product["id"], "quantity": format(quantity, "f"), "lineTotalMinor": line_total}
                    for _line, product, quantity, line_total in fulfilments
                ],
            }
            _audit(cursor, "pending_fulfillment_completed" if remaining == 0 else "pending_fulfillment_partial", order["source_channel"], details, order_id=order_id, actor=actor)
            connection.commit()
            return get_order(order_id), True
        except mysql.connector.IntegrityError:
            connection.rollback()
            cursor.execute("SELECT order_id FROM order_fulfillment_operations WHERE idempotency_key = %s", (idempotency_key,))
            prior = cursor.fetchone()
            if prior and prior["order_id"] == order_id:
                return get_order(order_id), False
            if prior:
                raise WorkflowError("IDEMPOTENCY_CONFLICT", "This key was already used for another fulfillment.", 409)
            raise
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()


def _order_payload(cursor, row):
    cursor.execute(
        """SELECT oi.quantity, oi.requested_quantity, oi.remaining_quantity, oi.unit,
                  oi.unit_price_minor, oi.line_total_minor, oi.currency,
                  p.id AS product_id, p.sku, p.name
           FROM order_items oi JOIN products p ON p.id = oi.product_id
           WHERE oi.order_id = %s ORDER BY oi.id""",
        (row["id"],),
    )
    items = [
        {
            "product": {"id": item["product_id"], "sku": item["sku"], "name": item["name"]},
            "quantity": format(Decimal(item["quantity"]), "f"),
            "requestedQuantity": format(Decimal(item["requested_quantity"]), "f"),
            "remainingQuantity": format(Decimal(item["remaining_quantity"]), "f"),
            "unit": item["unit"],
            "unitPrice": _money(item["unit_price_minor"], item["currency"]),
            "lineTotal": _money(item["line_total_minor"], item["currency"]),
        }
        for item in cursor.fetchall()
    ]
    return {
        "id": row["id"],
        "customerId": row["customer_id"],
        "customerName": row.get("customer_name"),
        "receivedAt": _timestamp(row["created_at"]),
        "total": _money(row["total_minor"], row["currency"]),
        "status": row["status"],
        "source": row["source_channel"],
        "externalReference": row["external_reference"],
        "deliveryPreference": _json_value(row["interpretation"]).get("deliveryPreference"),
        "items": items,
        "pendingItems": [
            {"productId": item["product"]["id"], "productName": item["product"]["name"], "quantity": item["remainingQuantity"], "unit": item["unit"]}
            for item in items if Decimal(item["remainingQuantity"]) > 0
        ],
    }


def _order_summary(row):
    return {
        "id": row["id"],
        "customerId": row["customer_id"],
        "customerName": row.get("customer_name"),
        "receivedAt": _timestamp(row["created_at"]),
        "total": _money(row["total_minor"], row["currency"]),
        "status": row["status"],
        "source": row["source_channel"],
        "externalReference": row["external_reference"],
        "deliveryPreference": _json_value(row["interpretation"]).get("deliveryPreference"),
        "hasPending": Decimal(row.get("pending_quantity") or 0) > 0,
    }


def get_order(order_id):
    with database_connection() as connection:
        cursor = _cursor(connection)
        try:
            cursor.execute(
                """SELECT o.*, c.name AS customer_name, p.interpretation,
                          COALESCE((SELECT SUM(oi.remaining_quantity) FROM order_items oi WHERE oi.order_id = o.id), 0) AS pending_quantity
                   FROM orders o
                   JOIN customers c ON c.id = o.customer_id
                   JOIN order_proposals p ON p.id = o.proposal_id WHERE o.id = %s""",
                (order_id,),
            )
            row = cursor.fetchone()
            return _order_payload(cursor, row) if row else None
        finally:
            cursor.close()


def list_orders(status=None, query=None, source=None, limit=50, offset=0):
    conditions = []
    params = []
    if status:
        conditions.append("o.status = %s")
        params.append(status)
    if source:
        conditions.append("o.source_channel = %s")
        params.append(source)
    if query:
        conditions.append("(o.id LIKE %s OR c.name LIKE %s)")
        params.extend((f"%{query}%", f"%{query}%"))
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    with database_connection() as connection:
        cursor = _cursor(connection)
        try:
            cursor.execute(
                """SELECT o.*, c.name AS customer_name, p.interpretation,
                          COALESCE((SELECT SUM(oi.remaining_quantity) FROM order_items oi WHERE oi.order_id = o.id), 0) AS pending_quantity
                   FROM orders o
                   JOIN customers c ON c.id = o.customer_id
                   JOIN order_proposals p ON p.id = o.proposal_id""" + where +
                " ORDER BY o.created_at DESC, o.id DESC LIMIT %s OFFSET %s",
                tuple(params + [limit + 1, offset]),
            )
            rows = cursor.fetchall()
            has_more = len(rows) > limit
            orders = [_order_summary(row) for row in rows[:limit]]
            return orders, (offset + limit if has_more else None)
        finally:
            cursor.close()


def get_order_events(order_id):
    with database_connection() as connection:
        cursor = _cursor(connection)
        try:
            cursor.execute("SELECT id FROM orders WHERE id = %s", (order_id,))
            if not cursor.fetchone():
                return None
            cursor.execute(
                """SELECT event_type, actor, source_channel, details, created_at
                   FROM audit_events
                   WHERE order_id = %s OR proposal_id = (SELECT proposal_id FROM orders WHERE id = %s)
                   ORDER BY id""",
                (order_id, order_id),
            )
            return [
                {
                    "type": row["event_type"],
                    "actor": row["actor"],
                    "source": row["source_channel"],
                    "details": _json_value(row["details"]),
                    "createdAt": _timestamp(row["created_at"]),
                }
                for row in cursor.fetchall()
            ]
        finally:
            cursor.close()
