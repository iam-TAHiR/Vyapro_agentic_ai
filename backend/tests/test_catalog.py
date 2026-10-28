"""Tests for MySQL-backed catalog endpoints without requiring MySQL."""

import unittest
from decimal import Decimal
from unittest.mock import patch

import mysql.connector

from app import create_app


class CatalogEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app({"TESTING": True}).test_client()

    @patch("app.catalog._fetch_rows")
    def test_customers_returns_database_records_in_contract_shape(self, fetch_rows):
        fetch_rows.return_value = [
            {
                "id": "cust-1",
                "name": "Sharma Stores",
                "credit_limit_minor": 500000,
                "credit_used_minor": 125000,
                "credit_currency": "INR",
            }
        ]

        response = self.client.get("/api/v1/customers")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {
                "customers": [
                    {
                        "id": "cust-1",
                        "name": "Sharma Stores",
                        "creditLimit": {"amountMinor": 500000, "currency": "INR"},
                        "creditUsed": {"amountMinor": 125000, "currency": "INR"},
                    }
                ]
            },
        )

    @patch("app.catalog._fetch_rows")
    def test_inventory_returns_database_records_with_exact_quantity(self, fetch_rows):
        fetch_rows.return_value = [
            {
                "id": "product-1",
                "sku": "RICE-001",
                "name": "Basmati Rice",
                "quantity_on_hand": Decimal("12.500"),
                "unit": "kg",
                "unit_price_minor": 8500,
                "price_currency": "INR",
            }
        ]

        response = self.client.get("/api/v1/inventory")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {
                "products": [
                    {
                        "id": "product-1",
                        "sku": "RICE-001",
                        "name": "Basmati Rice",
                        "quantityAvailable": "12.500",
                        "unit": "kg",
                        "unitPrice": {"amountMinor": 8500, "currency": "INR"},
                    }
                ]
            },
        )

    def test_customer_database_errors_use_safe_error_envelope(self):
        with patch("app.catalog._fetch_rows", side_effect=mysql.connector.Error("private host info")):
            response = self.client.get("/api/v1/customers")

        self.assertEqual(response.status_code, 503)
        body = response.get_json()
        self.assertEqual(body["error"]["code"], "DATABASE_UNAVAILABLE")
        self.assertEqual(body["error"]["message"], "Customer data is temporarily unavailable.")
        self.assertEqual(body["error"]["details"], [])
        self.assertNotIn("private host info", response.get_data(as_text=True))
        self.assertTrue(body["error"]["requestId"])

    def test_inventory_database_errors_use_safe_error_envelope(self):
        with patch("app.catalog._fetch_rows", side_effect=mysql.connector.Error("offline")):
            response = self.client.get("/api/v1/inventory")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error"]["code"], "DATABASE_UNAVAILABLE")

    def test_unconfigured_database_returns_safe_error(self):
        from app.database import DatabaseNotConfiguredError

        with patch(
            "app.catalog._fetch_rows",
            side_effect=DatabaseNotConfiguredError("MySQL is not configured."),
        ):
            response = self.client.get("/api/v1/inventory")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error"]["code"], "DATABASE_NOT_CONFIGURED")


if __name__ == "__main__":
    unittest.main()
