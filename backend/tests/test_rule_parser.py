"""Tests for the database-independent deterministic order grammar."""

import unittest

from app.order_service import WorkflowError
from app.rule_parser import _parse_text_items


PRODUCTS = [
    {"id": "rice-1", "sku": "RICE-1", "name": "India Gate Basmati Rice", "aliases": ["India Gate"]},
    {"id": "ghee-1", "sku": "GHEE-1", "name": "Cow Ghee", "aliases": []},
]


class RuleParserTests(unittest.TestCase):
    def test_parses_product_name_and_alias(self):
        items = _parse_text_items("Please send 2 kg of India Gate Basmati Rice.", PRODUCTS)
        self.assertEqual(items, [{
            "productText": "India Gate Basmati Rice",
            "productId": "rice-1",
            "quantity": "2",
            "unitText": "kg",
        }])

    def test_parses_multiple_lines(self):
        items = _parse_text_items("2 kg India Gate\n3 kg Cow Ghee", PRODUCTS)
        self.assertEqual([item["productId"] for item in items], ["rice-1", "ghee-1"])

    def test_rejects_unknown_product(self):
        with self.assertRaises(WorkflowError) as caught:
            _parse_text_items("2 kg unknown flour", PRODUCTS)
        self.assertEqual(caught.exception.code, "PRODUCT_NOT_FOUND")

    def test_rejects_ambiguous_item_quantity(self):
        with self.assertRaises(WorkflowError) as caught:
            _parse_text_items("2 kg India Gate 3 kg Cow Ghee", PRODUCTS)
        self.assertEqual(caught.exception.code, "ORDER_FORMAT_UNCLEAR")

    def test_rejects_nonpositive_quantity(self):
        with self.assertRaises(WorkflowError) as caught:
            _parse_text_items("0 kg Cow Ghee", PRODUCTS)
        self.assertEqual(caught.exception.code, "INVALID_QUANTITY")


if __name__ == "__main__":
    unittest.main()
