"""Structured LLM response validation tests."""

import unittest

from app.llm import InvalidInterpretationError, validate_interpretation


class InterpretationValidationTests(unittest.TestCase):
    def test_accepts_valid_order_shape_and_normalizes_quantity(self):
        result = validate_interpretation(
            {
                "customerText": " Sharma Stores ",
                "items": [{"productText": "Basmati Rice", "quantity": "2.5", "unitText": "kg"}],
                "deliveryPreference": " tomorrow ",
                "inventedPrice": 0,
            }
        )

        self.assertEqual(
            result,
            {
                "customerText": "Sharma Stores",
                "items": [{"productText": "Basmati Rice", "quantity": "2.5", "unitText": "kg"}],
                "deliveryPreference": "tomorrow",
            },
        )

    def test_rejects_non_positive_or_over_precision_quantities(self):
        for quantity in (0, -1, "1.2345", "NaN", "Infinity"):
            with self.subTest(quantity=quantity):
                with self.assertRaises(InvalidInterpretationError):
                    validate_interpretation(
                        {
                            "customerText": "Shop",
                            "items": [{"productText": "Rice", "quantity": quantity, "unitText": "kg"}],
                            "deliveryPreference": None,
                        }
                    )

    def test_rejects_missing_item_information(self):
        with self.assertRaises(InvalidInterpretationError):
            validate_interpretation({"customerText": None, "items": [], "deliveryPreference": None})


if __name__ == "__main__":
    unittest.main()
