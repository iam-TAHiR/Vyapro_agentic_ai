"""Import endpoint tests with an in-memory database adapter."""

from contextlib import contextmanager
from decimal import Decimal
from io import BytesIO
import json
import unittest
from unittest.mock import patch

from app import create_app


class MemoryImportDatabase:
    def __init__(self, customers=None, products=None):
        self.tables = {
            "customers": customers or [], "products": products or [], "aliases": [],
            "prices": [], "history": [], "batches": {}, "confirmation": {},
        }
        self.business_writes = []
        self.commit_count = 0
        self.connection = self

    @contextmanager
    def open(self):
        yield self

    def cursor(self, dictionary=False):
        return self

    def start_transaction(self):
        return None

    def commit(self):
        self.commit_count += 1

    def rollback(self):
        return None

    def close(self):
        return None

    def execute(self, query, params=()):
        self.result = []
        if "FROM data_import_batches WHERE fingerprint" in query:
            self.result = [row for row in self.tables["batches"].values() if row["fingerprint"] == params[0]]
        elif "FROM data_import_batches WHERE confirmation_key" in query:
            self.result = [self.tables["batches"][self.tables["confirmation"][params[0]]]] if params[0] in self.tables["confirmation"] else []
        elif "FROM data_import_batches WHERE id" in query:
            self.result = [self.tables["batches"][params[0]]] if params[0] in self.tables["batches"] else []
        elif query.startswith("INSERT INTO data_import_batches"):
            batch_id, fingerprint, content_sha, filename, fmt, allow_updates, status, staged, summary = params
            self.tables["batches"][batch_id] = {
                "id": batch_id, "fingerprint": fingerprint, "content_sha256": content_sha,
                "source_filename": filename, "source_format": fmt, "allow_updates": allow_updates,
                "status": status, "confirmation_key": None, "staged_data": staged, "summary": summary,
            }
        elif query.startswith("UPDATE data_import_batches SET status='imported'"):
            key, summary, batch_id = params
            batch = self.tables["batches"][batch_id]
            batch.update(status="imported", confirmation_key=key, summary=summary)
            self.tables["confirmation"][key] = batch_id
        elif "FROM customers" in query:
            self.result = self.tables["customers"]
        elif "FROM products" in query:
            self.result = self.tables["products"]
        elif "FROM product_aliases" in query:
            self.result = self.tables["aliases"]
        elif "FROM customer_product_prices" in query:
            self.result = self.tables["prices"]
        elif "FROM imported_order_history" in query:
            self.result = self.tables["history"]
        elif query.startswith("INSERT INTO customers"):
            self.business_writes.append(query)
            self.tables["customers"].append(dict(zip(("id", "name", "credit_limit_minor", "credit_used_minor", "credit_currency"), params)))
        elif query.startswith("INSERT INTO products"):
            self.business_writes.append(query)
            keys = ("id", "sku", "name", "quantity_on_hand", "unit", "unit_price_minor", "price_currency", "pack_size", "pack_unit")
            self.tables["products"].append(dict(zip(keys, params)))
        elif query.startswith("INSERT INTO product_aliases"):
            self.business_writes.append(query)
        elif query.startswith("INSERT INTO customer_product_prices"):
            self.business_writes.append(query)
        elif query.startswith("INSERT INTO imported_order_history") or query.startswith("INSERT INTO imported_order_history_items"):
            self.business_writes.append(query)
        elif query.startswith("UPDATE customers") or query.startswith("UPDATE products"):
            self.business_writes.append(query)
        else:
            raise AssertionError(f"Unexpected import query: {query}")

    def fetchone(self):
        return self.result[0] if self.result else None

    def fetchall(self):
        return self.result


class ImportApiTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app({"TESTING": True, "APP_ENV": "development"}).test_client()
        self.database = MemoryImportDatabase()
        self.db_patch = patch("app.imports.database_connection", side_effect=lambda: self.database.open())
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)

    def _preview_customer(self):
        return self.client.post(
            "/api/v1/imports/preview",
            data={"file": (BytesIO(b"customer_id,customer_name,credit_limit,credit_used,currency\nC-1,Sample Shop,1000,0,INR\n"), "customers.csv")},
            content_type="multipart/form-data",
        )

    def test_preview_is_staged_idempotently_and_does_not_write_business_rows(self):
        response = self._preview_customer()
        repeated = self._preview_customer()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "previewed")
        self.assertEqual(response.get_json()["importId"], repeated.get_json()["importId"])
        self.assertEqual(self.database.business_writes, [])

    def test_confirmation_requires_explicit_boolean_confirmation(self):
        preview = self._preview_customer().get_json()
        response = self.client.post(
            f"/api/v1/imports/{preview['importId']}/confirm",
            headers={"Idempotency-Key": "import-1"},
            json={"confirm": False},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.database.business_writes, [])

    def test_confirm_commits_once_and_retry_returns_same_summary(self):
        preview = self._preview_customer().get_json()
        endpoint = f"/api/v1/imports/{preview['importId']}/confirm"
        headers = {"Idempotency-Key": "import-1"}
        imported = self.client.post(endpoint, headers=headers, json={"confirm": True})
        repeated = self.client.post(endpoint, headers=headers, json={"confirm": True})

        self.assertEqual(imported.status_code, 200)
        self.assertEqual(imported.get_json()["status"], "imported")
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.get_json()["importId"], imported.get_json()["importId"])
        self.assertEqual(len(self.database.business_writes), 1)
        self.assertEqual(len(self.database.tables["customers"]), 1)

    def test_existing_rows_are_blocked_until_update_option_is_previewed(self):
        self.database.tables["customers"].append({"id": "C-1", "name": "Sample Shop", "credit_limit_minor": 50000, "credit_used_minor": 0, "credit_currency": "INR"})
        response = self.client.post(
            "/api/v1/imports/preview",
            data={"file": (BytesIO(b"customer_id,customer_name,credit_limit,credit_used,currency\nC-1,Sample Shop,1000,0,INR\n"), "customers.csv")},
            content_type="multipart/form-data",
        )
        preview = response.get_json()
        codes = [item["code"] for item in preview["preview"]["errors"]]

        self.assertEqual(preview["status"], "needs_correction")
        self.assertIn("EXISTING_RECORD_REQUIRES_UPDATE_CONFIRMATION", codes)
        self.assertEqual(self.database.business_writes, [])

    def test_confirmation_rejects_database_changes_after_preview(self):
        preview = self._preview_customer().get_json()
        # Simulate another transaction creating the same customer after preview.
        self.database.tables["customers"].append({"id": "C-1", "name": "Sample Shop", "credit_limit_minor": 1, "credit_used_minor": 0, "credit_currency": "INR"})

        result = self.client.post(
            f"/api/v1/imports/{preview['importId']}/confirm",
            headers={"Idempotency-Key": "stale-preview"},
            json={"confirm": True},
        )

        self.assertEqual(result.status_code, 409)
        self.assertEqual(result.get_json()["error"]["code"], "DATA_CHANGED_SINCE_PREVIEW")
        self.assertFalse(self.database.business_writes)

    def test_forced_dataset_type_is_part_of_preview_idempotency(self):
        source = b"sku,quantity_on_hand,unit\nDEMO-P-1,4,kg\n"
        first = self.client.post(
            "/api/v1/imports/preview",
            data={"datasetType": "inventory", "file": (BytesIO(source), "data.csv")},
            content_type="multipart/form-data",
        )
        second = self.client.post(
            "/api/v1/imports/preview",
            data={"datasetType": "products", "file": (BytesIO(source), "data.csv")},
            content_type="multipart/form-data",
        )

        self.assertNotEqual(first.get_json()["importId"], second.get_json()["importId"])

    def test_history_confirmation_writes_to_separate_imported_history_tables(self):
        self.database.tables["customers"].append({"id": "C-1", "name": "Sample Shop", "credit_limit_minor": 500000, "credit_used_minor": 0, "credit_currency": "INR"})
        self.database.tables["products"].append({"id": "P-1", "sku": "RICE-1", "name": "Rice", "quantity_on_hand": Decimal("20"), "unit": "kg", "unit_price_minor": 5000, "price_currency": "INR", "pack_size": None, "pack_unit": None})
        preview = self.client.post(
            "/api/v1/imports/preview",
            data={"file": (BytesIO(b"order_id,customer_id,order_date,status,sku,quantity,unit,unit_price,currency\nOLD-1,C-1,2025-01-01,delivered,RICE-1,2,kg,50,INR\n"), "previous_orders.csv")},
            content_type="multipart/form-data",
        ).get_json()

        self.assertEqual(preview["status"], "previewed")
        completed = self.client.post(f"/api/v1/imports/{preview['importId']}/confirm", headers={"Idempotency-Key": "history-import"}, json={"confirm": True})
        self.assertEqual(completed.status_code, 200)
        self.assertEqual(completed.get_json()["status"], "imported")
        self.assertTrue(any(query.startswith("INSERT INTO imported_order_history") for query in self.database.business_writes))
        self.assertFalse(any(query.startswith("INSERT INTO orders") for query in self.database.business_writes))


if __name__ == "__main__":
    unittest.main()
