"""Opt-in real-MySQL integration coverage for partial order fulfillment.

Run only against a dedicated, empty test schema by setting
VYAPRO_TEST_MYSQL_DATABASE=vyapro_shortage_test.
"""

import os
import unittest
import uuid

import mysql.connector

from app import create_app
from app.database import database_connection
from app.migrations import apply_migrations


TEST_DATABASE = os.getenv("VYAPRO_TEST_MYSQL_DATABASE", "")


@unittest.skipUnless(TEST_DATABASE == "vyapro_shortage_test", "requires the dedicated vyapro_shortage_test schema")
class ShortageMySQLIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app({"TESTING": True, "APP_ENV": "development", "MYSQL_DATABASE": TEST_DATABASE})
        with cls.app.app_context():
            apply_migrations()
            with database_connection() as connection:
                cursor = connection.cursor()
                for table in ("customers", "products", "order_proposals", "orders", "audit_events"):
                    cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
                    if cursor.fetchone()[0]:
                        raise RuntimeError(f"Refusing to run integration tests: dedicated database table {table} is not empty.")
                cursor.close()
        cls.client = cls.app.test_client()

    def setUp(self):
        self.customer_id = f"IT-C-{uuid.uuid4().hex[:20]}"
        self.product_id = f"IT-P-{uuid.uuid4().hex[:20]}"
        with self.app.app_context(), database_connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "INSERT INTO customers (id, name, credit_limit_minor, credit_used_minor, credit_currency) VALUES (%s, %s, %s, 0, 'INR')",
                (self.customer_id, f"Integration Retailer {self.customer_id[-6:]}", 50000),
            )
            cursor.execute(
                "INSERT INTO products (id, sku, name, quantity_on_hand, unit, unit_price_minor, price_currency) VALUES (%s, %s, %s, 5, 'kg', 1000, 'INR')",
                (self.product_id, f"{self.product_id}-SKU", f"Integration Rice {self.product_id[-6:]}",),
            )
            connection.commit()
            cursor.close()

    def tearDown(self):
        with self.app.app_context(), database_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT id FROM order_proposals WHERE idempotency_key LIKE %s", (f"it-{self.customer_id}-%",))
            proposal_ids = [row[0] for row in cursor.fetchall()]
            if proposal_ids:
                marks = ",".join(["%s"] * len(proposal_ids))
                cursor.execute(f"SELECT id FROM orders WHERE proposal_id IN ({marks})", tuple(proposal_ids))
                order_ids = [row[0] for row in cursor.fetchall()]
                if order_ids:
                    order_marks = ",".join(["%s"] * len(order_ids))
                    cursor.execute(f"DELETE FROM audit_events WHERE order_id IN ({order_marks})", tuple(order_ids))
                    cursor.execute(f"DELETE FROM order_fulfillment_operations WHERE order_id IN ({order_marks})", tuple(order_ids))
                    cursor.execute(f"DELETE FROM order_items WHERE order_id IN ({order_marks})", tuple(order_ids))
                    cursor.execute(f"DELETE FROM orders WHERE id IN ({order_marks})", tuple(order_ids))
                cursor.execute(f"DELETE FROM audit_events WHERE proposal_id IN ({marks})", tuple(proposal_ids))
                cursor.execute(f"DELETE FROM order_proposal_items WHERE proposal_id IN ({marks})", tuple(proposal_ids))
                cursor.execute(f"DELETE FROM order_proposals WHERE id IN ({marks})", tuple(proposal_ids))
            cursor.execute("DELETE FROM products WHERE id = %s", (self.product_id,))
            cursor.execute("DELETE FROM customers WHERE id = %s", (self.customer_id,))
            connection.commit()
            cursor.execute("SELECT COUNT(*) FROM customers WHERE id = %s", (self.customer_id,))
            self.assertEqual(cursor.fetchone()[0], 0)
            cursor.execute("SELECT COUNT(*) FROM products WHERE id = %s", (self.product_id,))
            self.assertEqual(cursor.fetchone()[0], 0)
            cursor.execute("SELECT COUNT(*) FROM order_proposals WHERE idempotency_key LIKE %s", (f"it-{self.customer_id}-%",))
            self.assertEqual(cursor.fetchone()[0], 0)
            cursor.close()

    def _counts(self):
        with self.app.app_context(), database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute("SELECT quantity_on_hand FROM products WHERE id = %s", (self.product_id,))
            stock = cursor.fetchone()["quantity_on_hand"]
            cursor.execute("SELECT credit_used_minor FROM customers WHERE id = %s", (self.customer_id,))
            credit = cursor.fetchone()["credit_used_minor"]
            cursor.execute("SELECT COUNT(*) AS n FROM orders o JOIN order_proposals p ON p.id = o.proposal_id WHERE p.idempotency_key LIKE %s", (f"it-{self.customer_id}-%",))
            orders = cursor.fetchone()["n"]
            return stock, credit, orders

    def _proposal(self, suffix="main"):
        key = f"it-{self.customer_id}-{suffix}"
        response = self.client.post(
            "/api/v1/order-proposals",
            headers={"Idempotency-Key": key},
            json={
                "source": {"channel": "web", "externalReference": None},
                "customerId": self.customer_id,
                "message": {"text": f"Please send 10 kg Integration Rice {self.product_id[-6:]}."},
            },
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()["proposal"]

    def _approve(self, proposal, accept_partial, suffix="approve"):
        return self.client.post(
            f"/api/v1/order-proposals/{proposal['id']}/approval",
            headers={"Idempotency-Key": f"it-{self.customer_id}-{suffix}"},
            json={"decision": "approve", "proposalVersion": proposal["version"], "acceptPartial": accept_partial},
        )

    def test_accept_partial_then_idempotently_fulfill_recorded_remainder(self):
        proposal = self._proposal()
        item = proposal["items"][0]
        self.assertEqual(item["requested"]["quantity"], "10.000")
        self.assertEqual(item["offeredQuantity"], "5.000")
        self.assertEqual(item["remainingQuantity"], "5.000")
        self.assertEqual(proposal["status"], "needs_review")

        rejected_consent = self._approve(proposal, False, "without-consent")
        self.assertEqual(rejected_consent.status_code, 422)
        self.assertEqual(self._counts(), (5, 0, 0))

        accepted = self._approve(proposal, True)
        self.assertEqual(accepted.status_code, 201, accepted.get_json())
        order = accepted.get_json()["order"]
        self.assertEqual(order["status"], "partially_fulfilled")
        self.assertEqual(order["items"][0]["requestedQuantity"], "10.000")
        self.assertEqual(order["items"][0]["quantity"], "5.000")
        self.assertEqual(order["items"][0]["remainingQuantity"], "5.000")
        self.assertEqual(self._counts(), (0, 5000, 1))
        customer_status = self.client.get(f"/api/v1/customer-orders?customerId={self.customer_id}")
        self.assertEqual(customer_status.status_code, 200)
        self.assertTrue(customer_status.get_json()["orders"][0]["hasPending"])

        self.assertEqual(self.client.post(f"/api/v1/orders/{order['id']}/fulfill-pending", json={}).status_code, 422)
        with self.app.app_context(), database_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("UPDATE products SET quantity_on_hand = 3 WHERE id = %s", (self.product_id,))
            connection.commit()
            cursor.close()
        fulfillment_key = f"it-{self.customer_id}-fulfill"
        fulfillment = self.client.post(
            f"/api/v1/orders/{order['id']}/fulfill-pending",
            headers={"Idempotency-Key": fulfillment_key}, json={"confirm": True},
        )
        self.assertEqual(fulfillment.status_code, 201, fulfillment.get_json())
        partial = fulfillment.get_json()["order"]
        self.assertEqual(partial["status"], "partially_fulfilled")
        self.assertEqual(partial["items"][0]["quantity"], "8.000")
        self.assertEqual(partial["items"][0]["remainingQuantity"], "2.000")
        self.assertEqual(self._counts(), (0, 8000, 1))

        no_stock = self.client.post(
            f"/api/v1/orders/{order['id']}/fulfill-pending",
            headers={"Idempotency-Key": f"it-{self.customer_id}-no-stock"}, json={"confirm": True},
        )
        self.assertEqual(no_stock.status_code, 409)
        self.assertEqual(no_stock.get_json()["error"]["code"], "INSUFFICIENT_STOCK")
        self.assertEqual(self._counts(), (0, 8000, 1))

        with self.app.app_context(), database_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("UPDATE products SET quantity_on_hand = 2 WHERE id = %s", (self.product_id,))
            connection.commit()
            cursor.close()
        completed = self.client.post(
            f"/api/v1/orders/{order['id']}/fulfill-pending",
            headers={"Idempotency-Key": f"it-{self.customer_id}-complete"}, json={"confirm": True},
        )
        self.assertEqual(completed.status_code, 201, completed.get_json())
        final_order = completed.get_json()["order"]
        self.assertEqual(final_order["status"], "confirmed")
        self.assertEqual(final_order["items"][0]["quantity"], "10.000")
        self.assertEqual(final_order["items"][0]["remainingQuantity"], "0.000")
        self.assertEqual(self._counts(), (0, 10000, 1))
        self.assertFalse(self.client.get(f"/api/v1/customer-orders?customerId={self.customer_id}").get_json()["orders"][0]["hasPending"])

        retry = self.client.post(
            f"/api/v1/orders/{order['id']}/fulfill-pending",
            headers={"Idempotency-Key": fulfillment_key}, json={"confirm": True},
        )
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.get_json()["order"]["items"][0]["quantity"], "10.000")
        self.assertEqual(self._counts(), (0, 10000, 1))
        events = self.client.get(f"/api/v1/orders/{order['id']}/events").get_json()["events"]
        self.assertEqual([event["type"] for event in events].count("order_partially_fulfilled"), 1)
        self.assertEqual([event["type"] for event in events].count("pending_fulfillment_partial"), 1)
        self.assertEqual([event["type"] for event in events].count("pending_fulfillment_completed"), 1)

    def test_rejection_and_stock_race_do_not_change_credit_or_create_order(self):
        rejected = self._proposal("reject")
        rejection = self.client.post(
            f"/api/v1/order-proposals/{rejected['id']}/approval",
            headers={"Idempotency-Key": f"it-{self.customer_id}-reject"}, json={"decision": "reject"},
        )
        self.assertEqual(rejection.status_code, 200)
        self.assertEqual(self._counts(), (5, 0, 0))

        raced = self._proposal("race")
        with self.app.app_context(), database_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("UPDATE products SET quantity_on_hand = 4 WHERE id = %s", (self.product_id,))
            connection.commit()
            cursor.close()
        failed = self._approve(raced, True, "race-approve")
        self.assertEqual(failed.status_code, 409)
        self.assertEqual(failed.get_json()["error"]["code"], "INSUFFICIENT_STOCK")
        self.assertEqual(self._counts(), (4, 0, 0))

    def test_pending_fulfillment_credit_failure_rolls_back_inventory(self):
        proposal = self._proposal("credit-on-pending")
        accepted = self._approve(proposal, True, "credit-approve")
        self.assertEqual(accepted.status_code, 201)
        order = accepted.get_json()["order"]
        with self.app.app_context(), database_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("UPDATE products SET quantity_on_hand = 5 WHERE id = %s", (self.product_id,))
            cursor.execute("UPDATE customers SET credit_limit_minor = credit_used_minor WHERE id = %s", (self.customer_id,))
            connection.commit()
            cursor.close()
        response = self.client.post(
            f"/api/v1/orders/{order['id']}/fulfill-pending",
            headers={"Idempotency-Key": f"it-{self.customer_id}-credit-fulfill"}, json={"confirm": True},
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.get_json()["error"]["code"], "CREDIT_LIMIT_EXCEEDED")
        self.assertEqual(self._counts(), (5, 5000, 1))
