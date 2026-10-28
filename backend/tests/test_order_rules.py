"""Pure unit tests for deterministic order validation rules."""

import unittest
from decimal import Decimal

from app.order_service import _evaluate, _lookup_product, _save_lines


CUSTOMER = {
    "id": "cust-1",
    "name": "Sharma Stores",
    "credit_limit_minor": 100000,
    "credit_used_minor": 0,
    "credit_currency": "INR",
}


def product(identifier, name, stock, price=1000):
    return {
        "id": identifier,
        "sku": identifier.upper(),
        "name": name,
        "quantity_on_hand": Decimal(stock),
        "unit": "kg",
        "unit_price_minor": price,
        "price_currency": "INR",
    }


class CatalogCursor:
    def __init__(self, available_products, substitutes=None, customer=CUSTOMER, aliases=None, price_overrides=None):
        self.available_products = available_products
        self.substitutes = substitutes or {}
        self.customer = customer
        self.aliases = aliases or {}
        self.price_overrides = price_overrides or {}
        self.rows = []
        self.row = None

    def execute(self, query, params):
        self.row = None
        if "FROM customers" in query:
            self.rows = [self.customer] if self.customer else []
        elif "FROM customer_product_prices" in query:
            self.row = self.price_overrides.get(params[1])
        elif "FROM products WHERE" in query:
            self.rows = [p for p in self.available_products if p["name"].casefold() == params[0].casefold() or p["sku"].casefold() == params[1].casefold() or self.aliases.get(p["id"], "").casefold() == params[2].casefold()][:2]
        elif "FROM product_substitutions" in query:
            self.row = self.substitutes.get((params[0], params[2]))

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.row


class OrderRuleTests(unittest.TestCase):
    def test_product_alias_matches_only_explicit_alias_data(self):
        rice = product("rice-1", "Basmati Rice", "20.000")
        cursor = CatalogCursor([rice], aliases={"rice-1": "long grain"})

        self.assertEqual(len(_lookup_product(cursor, "long grain")), 1)
        self.assertEqual(_lookup_product(cursor, "basmati rice")[0]["id"], "rice-1")

    def test_customer_price_override_is_used_in_proposal_total(self):
        rice = product("rice-1", "Basmati Rice", "20.000", 2500)
        cursor = CatalogCursor([rice], price_overrides={"rice-1": {"unit_price_minor": 1800, "currency": "INR"}})
        result = _evaluate(
            cursor,
            {"customerText": "Sharma Stores", "items": [{"productText": "Basmati Rice", "quantity": "2", "unitText": "kg"}]},
            "web",
            None,
        )

        self.assertEqual(result["total_minor"], 3600)
        self.assertEqual(result["lines"][0]["price_product"]["unit_price_minor"], 1800)
    def test_saved_proposal_line_keeps_price_total_and_currency_in_schema_order(self):
        cursor = type("Cursor", (), {"execute": lambda self, query, params: setattr(self, "params", params)})()
        rice = product("rice-1", "Basmati Rice", "20.000", 2500)
        _save_lines(cursor, "proposal-1", [{
            "requested_product_text": "Basmati Rice",
            "requested_quantity": Decimal("2"),
            "requested_unit": "kg",
            "product": rice,
            "substitute": None,
            "line_total_minor": 5000,
            "line_status": "available",
        }])

        self.assertEqual(cursor.params[3], Decimal("2"))
        self.assertEqual(cursor.params[8:12], (2500, 5000, "INR", "available"))

    def test_available_product_and_credit_produce_reviewable_total(self):
        rice = product("rice-1", "Basmati Rice", "20.000", 2500)
        result = _evaluate(
            CatalogCursor([rice]),
            {"customerText": "Sharma Stores", "items": [{"productText": "Basmati Rice", "quantity": "2", "unitText": "kg"}]},
            "web",
            None,
        )

        self.assertEqual(result["status"], "needs_review")
        self.assertEqual(result["total_minor"], 5000)
        self.assertEqual(result["lines"][0]["line_status"], "available")
        self.assertEqual(result["warnings"], [])

    def test_shortage_requires_explicit_substitution_approval(self):
        rice = product("rice-1", "Basmati Rice", "1.000")
        alternative = {**product("rice-2", "Sella Rice", "10.000", 1200), "reason": "Approved similar rice"}
        result = _evaluate(
            CatalogCursor([rice], {(rice["id"], "kg"): alternative}),
            {"customerText": "Sharma Stores", "items": [{"productText": "Basmati Rice", "quantity": "2", "unitText": "kg"}]},
            "web",
            None,
        )

        self.assertEqual(result["status"], "needs_review")
        self.assertEqual(result["lines"][0]["line_status"], "substitution_suggested")
        self.assertEqual(result["lines"][0]["substitute"]["name"], "Sella Rice")
        self.assertEqual(result["warnings"][0]["code"], "SUBSTITUTION_PROPOSED")

    def test_over_credit_is_blocked_for_clarification(self):
        rice = product("rice-1", "Basmati Rice", "20.000", 2000)
        customer = {**CUSTOMER, "credit_limit_minor": 1000}
        result = _evaluate(
            CatalogCursor([rice], customer=customer),
            {"customerText": "Sharma Stores", "items": [{"productText": "Basmati Rice", "quantity": "2", "unitText": "kg"}]},
            "web",
            None,
        )

        self.assertEqual(result["status"], "needs_clarification")
        self.assertIn("CREDIT_LIMIT_EXCEEDED", [warning["code"] for warning in result["warnings"]])

    def test_partial_stock_is_offered_and_remainder_is_explicit(self):
        rice = product("rice-1", "Basmati Rice", "1.000")
        result = _evaluate(
            CatalogCursor([rice]),
            {"customerText": "Sharma Stores", "items": [{"productText": "Basmati Rice", "quantity": "2", "unitText": "kg"}]},
            "web",
            None,
        )

        self.assertEqual(result["status"], "needs_review")
        self.assertEqual(result["lines"][0]["line_status"], "partial_available")
        self.assertEqual(result["lines"][0]["offered_quantity"], Decimal("1.000"))
        self.assertEqual(result["total_minor"], 1000)
        self.assertIn("PARTIAL_FULFILLMENT_OFFERED", [warning["code"] for warning in result["warnings"]])

    def test_zero_stock_does_not_offer_or_create_a_partial_fulfillment(self):
        rice = product("rice-1", "Basmati Rice", "0.000")
        result = _evaluate(
            CatalogCursor([rice]),
            {"customerText": "Sharma Stores", "items": [{"productText": "Basmati Rice", "quantity": "2", "unitText": "kg"}]},
            "web",
            None,
        )
        self.assertEqual(result["status"], "needs_clarification")
        self.assertEqual(result["lines"][0]["line_status"], "insufficient_stock")
        self.assertIsNone(result["total_minor"])


if __name__ == "__main__":
    unittest.main()
