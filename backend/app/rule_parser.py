"""Small deterministic parser for customer orders in the local MVP."""

import re
from decimal import Decimal, InvalidOperation

from app.database import database_connection
from app.order_service import WorkflowError


_QUANTITY_UNIT = re.compile(
    r"(?<![\w.])(?P<quantity>\d+(?:\.\d{1,})?)\s*"
    r"(?P<unit>kilograms?|kgs?|grams?|g|lit(?:er|re)s?|lts?|l|packs?|pieces?|pcs?)\b",
    re.IGNORECASE,
)
_UNIT_MAP = {
    "kg": "kg", "kgs": "kg", "kilogram": "kg", "kilograms": "kg",
    "g": "g", "gram": "g", "grams": "g",
    "l": "l", "lt": "l", "lts": "l", "liter": "l", "liters": "l",
    "litre": "l", "litres": "l",
    "pack": "pack", "packs": "pack", "piece": "piece", "pieces": "piece",
    "pc": "piece", "pcs": "piece",
}


def _quantity(value):
    try:
        quantity = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise WorkflowError("INVALID_QUANTITY", "Enter a numeric quantity greater than zero.", 400)
    if not quantity.is_finite() or quantity <= 0 or quantity.as_tuple().exponent < -3:
        raise WorkflowError("INVALID_QUANTITY", "Quantity must be positive and use at most three decimal places.", 400)
    return format(quantity, "f")


def _normal_text(value):
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _matching_products(segment, products):
    normalized_segment = f" {_normal_text(segment)} "
    matches = []
    for product in products:
        terms = [product["name"], product["sku"], *product["aliases"]]
        found = [term for term in terms if f" {_normal_text(term)} " in normalized_segment]
        if found:
            matches.append((max(len(_normal_text(term)) for term in found), product))
    if not matches:
        return []
    longest = max(length for length, _product in matches)
    unique = {product["id"]: product for length, product in matches if length == longest}
    return list(unique.values())


def _parse_text_items(text, products):
    items = []
    for line in (part.strip() for part in re.split(r"[\n;]+", text) if part.strip()):
        matches = list(_QUANTITY_UNIT.finditer(line))
        if len(matches) != 1:
            raise WorkflowError(
                "ORDER_FORMAT_UNCLEAR",
                "Use one item per line in the form 'quantity unit product', for example '2 kg India Gate Basmati Rice'.",
                422,
            )
        amount_match = matches[0]
        product_matches = _matching_products(line, products)
        if not product_matches:
            raise WorkflowError("PRODUCT_NOT_FOUND", "Could not match a product in the live catalog. Choose a product or enter its exact name or SKU.", 422)
        if len(product_matches) != 1:
            raise WorkflowError("PRODUCT_AMBIGUOUS", "This product text matches more than one catalog item. Enter the exact product name or SKU.", 422)
        product = product_matches[0]
        items.append({
            "productText": product["name"],
            "productId": product["id"],
            "quantity": _quantity(amount_match.group("quantity")),
            "unitText": _UNIT_MAP[amount_match.group("unit").casefold()],
        })
    if not items:
        raise WorkflowError("ORDER_ITEMS_REQUIRED", "Add a product and quantity before reviewing the order.", 400)
    return items


def build_order_interpretation(customer_id, text, selected_items=None):
    """Resolve a selected registered customer and parse text/cart lines using MySQL records."""
    if not isinstance(customer_id, str) or not customer_id.strip():
        raise WorkflowError("CUSTOMER_REQUIRED", "Choose a registered customer before creating an order proposal.", 400)
    if not isinstance(text, str):
        raise WorkflowError("INVALID_REQUEST", "message.text must be text.", 400)

    with database_connection() as connection:
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute("SELECT id, name FROM customers WHERE id = %s", (customer_id.strip(),))
            customer = cursor.fetchone()
            if not customer:
                raise WorkflowError("CUSTOMER_NOT_FOUND", "The selected customer record was not found.", 404)

            if selected_items is None:
                if not text.strip():
                    raise WorkflowError("ORDER_ITEMS_REQUIRED", "Add a product and quantity before reviewing the order.", 400)
                cursor.execute("SELECT id, sku, name, unit FROM products ORDER BY id")
                products = cursor.fetchall()
                cursor.execute("SELECT product_id, alias FROM product_aliases ORDER BY product_id, alias")
                aliases = cursor.fetchall()
                by_id = {product["id"]: product for product in products}
                for product in products:
                    product["aliases"] = []
                for alias in aliases:
                    if alias["product_id"] in by_id:
                        by_id[alias["product_id"]]["aliases"].append(alias["alias"])
                items = _parse_text_items(text.strip(), products)
                original_text = text.strip()
            else:
                if not isinstance(selected_items, list) or not selected_items or len(selected_items) > 50:
                    raise WorkflowError("ORDER_ITEMS_REQUIRED", "Select at least one catalog item.", 400)
                items = []
                summaries = []
                for line in selected_items:
                    if not isinstance(line, dict):
                        raise WorkflowError("INVALID_ORDER_ITEM", "Each selected item must include a product and quantity.", 400)
                    product_id = line.get("productId")
                    if not isinstance(product_id, str) or not product_id.strip():
                        raise WorkflowError("INVALID_ORDER_ITEM", "Select a product from the live catalog.", 400)
                    cursor.execute("SELECT id, sku, name, unit FROM products WHERE id = %s", (product_id.strip(),))
                    product = cursor.fetchone()
                    if not product:
                        raise WorkflowError("PRODUCT_NOT_FOUND", "A selected product no longer exists in the live catalog. Refresh and try again.", 409)
                    quantity = _quantity(line.get("quantity"))
                    provided_unit = line.get("unit")
                    if provided_unit is not None and (not isinstance(provided_unit, str) or provided_unit.casefold() != product["unit"].casefold()):
                        raise WorkflowError("PRODUCT_CHANGED", "A selected product unit changed. Refresh the catalog and try again.", 409)
                    items.append({
                        "productText": product["name"],
                        "productId": product["id"],
                        "quantity": quantity,
                        "unitText": product["unit"],
                    })
                    summaries.append(f"{quantity} {product['unit']} {product['name']} (SKU {product['sku']})")
                original_text = text.strip()
                selected_summary = "Selected catalog items: " + "; ".join(summaries)
                original_text = f"{original_text}\n{selected_summary}" if original_text else selected_summary

            return {
                "customerText": customer["name"],
                "customerId": customer["id"],
                "items": items,
                "deliveryPreference": None,
            }, original_text
        finally:
            cursor.close()
