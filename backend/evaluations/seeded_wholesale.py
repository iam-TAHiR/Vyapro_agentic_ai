"""Synthetic wholesale fixture records used only by the isolated agent evaluator."""

from copy import deepcopy
from decimal import Decimal


CUSTOMERS = [
    {"id": "EVAL-C-001", "name": "Northstar Wholesale", "credit_limit_minor": 2_000_000, "credit_used_minor": 100_000, "credit_currency": "INR"},
    {"id": "EVAL-C-002", "name": "Tight Credit Mart", "credit_limit_minor": 25_000, "credit_used_minor": 24_000, "credit_currency": "INR"},
]

PRODUCTS = [
    {"id": "EVAL-P-RICE", "sku": "RICE-100", "name": "Basmati Rice", "quantity_on_hand": Decimal("100"), "unit": "kg", "unit_price_minor": 10_000, "price_currency": "INR"},
    {"id": "EVAL-P-SELLA", "sku": "RICE-200", "name": "Sella Rice", "quantity_on_hand": Decimal("50"), "unit": "kg", "unit_price_minor": 12_000, "price_currency": "INR"},
    {"id": "EVAL-P-OIL", "sku": "OIL-010", "name": "Cooking Oil", "quantity_on_hand": Decimal("2"), "unit": "l", "unit_price_minor": 15_000, "price_currency": "INR"},
    {"id": "EVAL-P-GHEE", "sku": "GHEE-001", "name": "Clarified Butter", "quantity_on_hand": Decimal("0"), "unit": "l", "unit_price_minor": 40_000, "price_currency": "INR"},
]

ALIASES = {
    "EVAL-P-RICE": {"premium long grain rice", "long grain rice", "basmati"},
}

SUBSTITUTIONS = {
    ("EVAL-P-RICE", "kg"): {
        **deepcopy(PRODUCTS[1]),
        "reason": "Approved alternate rice grade for wholesale orders",
    },
}

ORDER_HISTORY = [
    {"id": "EVAL-ORDER-000", "status": "confirmed", "total": {"amountMinor": 20_000, "currency": "INR"}},
]


def fresh_customers():
    return deepcopy(CUSTOMERS)


def fresh_products():
    return deepcopy(PRODUCTS)
