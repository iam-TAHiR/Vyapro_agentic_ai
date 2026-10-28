"""Seeded agent evaluations. All identities, stock, money, and orders are synthetic."""

from contextlib import ExitStack
from copy import deepcopy
from decimal import Decimal
import json
import unittest
from unittest.mock import patch

import mysql.connector

from app import create_app
from app import agent as agent_module
from app.llm import LLMUnavailableError
from app.order_service import WorkflowError, _evaluate
from evaluations import seeded_wholesale as seed


def tool_call(name, arguments):
    return {"role": "assistant", "tool_calls": [{
        "id": f"eval-{name}", "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }]}


def final_message(text="I have checked the available records."):
    return {"role": "assistant", "content": text}


class SeededCursor:
    """SQL-shaped cursor used by the real deterministic `_evaluate` rules."""

    def __init__(self, store):
        self.store = store
        self.rows = []
        self.row = None

    def execute(self, query, params=()):
        self.rows = []
        self.row = None
        if "FROM customers WHERE LOWER(TRIM(name))" in query:
            text = str(params[0]).strip().casefold()
            self.rows = [item for item in self.store.customers if item["name"].strip().casefold() == text][:2]
        elif "FROM products WHERE LOWER(name)" in query:
            text = str(params[0]).strip().casefold()
            self.rows = [product for product in self.store.products if (
                product["name"].casefold() == text or product["sku"].casefold() == text
                or text in seed.ALIASES.get(product["id"], set())
            )][:2]
        elif "FROM customer_product_prices" in query:
            self.row = self.store.customer_prices.get((params[0], params[1]))
        elif "FROM product_substitutions" in query:
            source_id, quantity, unit = params
            candidate = deepcopy(self.store.products[1]) if source_id == "EVAL-P-RICE" and unit == "kg" else None
            if candidate:
                candidate["reason"] = "Approved alternate rice grade for wholesale orders"
            if candidate and Decimal(candidate["quantity_on_hand"]) >= Decimal(str(quantity)):
                self.row = deepcopy(candidate)

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.row


class SeededWholesaleStore:
    def __init__(self):
        self.customers = seed.fresh_customers()
        self.products = seed.fresh_products()
        self.customer_prices = {("EVAL-C-001", "EVAL-P-RICE"): {"unit_price_minor": 9_500, "currency": "INR"}}
        # The alternate is deliberately stocked to cover the evaluated shortage.
        self.products[1]["quantity_on_hand"] = Decimal("150")
        self.history = deepcopy(seed.ORDER_HISTORY)
        self.proposals = {}
        self.orders = []
        self.order_keys = {}
        self.changes = []
        self.tool_service_calls = []
        self.proposal_number = 0

    def cursor(self):
        return SeededCursor(self)

    @staticmethod
    def money(amount, currency):
        return {"amountMinor": int(amount), "currency": currency} if amount is not None and currency else None

    @staticmethod
    def product_payload(product):
        return {
            "id": product["id"], "sku": product["sku"], "name": product["name"],
            "quantityAvailable": format(Decimal(product["quantity_on_hand"]), "f"),
            "unit": product["unit"],
            "unitPrice": {"amountMinor": int(product["unit_price_minor"]), "currency": product["price_currency"]},
        }

    def lookup_customer(self, name):
        self.tool_service_calls.append(("lookup_customer", name))
        item = next((c for c in self.customers if c["name"].casefold() == name.casefold()), None)
        return [{"id": item["id"], "name": item["name"], "creditLimit": self.money(item["credit_limit_minor"], item["credit_currency"]), "creditUsed": self.money(item["credit_used_minor"], item["credit_currency"])}] if item else []

    def match_products(self, query):
        self.tool_service_calls.append(("match_product", query))
        normalized = query.casefold().strip()
        found = [p for p in self.products if p["name"].casefold() == normalized or p["sku"].casefold() == normalized or normalized in seed.ALIASES.get(p["id"], set())]
        return [self.product_payload(p) for p in found]

    def get_product(self, product_id):
        self.tool_service_calls.append(("check_inventory", product_id))
        item = next((p for p in self.products if p["id"] == product_id), None)
        return self.product_payload(item) if item else None

    def get_pricing(self, customer_name, product_id):
        self.tool_service_calls.append(("get_customer_pricing", customer_name, product_id))
        customer = next((c for c in self.customers if c["name"].casefold() == customer_name.casefold()), None)
        product = next((p for p in self.products if p["id"] == product_id), None)
        if not customer or not product:
            return {"customerMatched": False, "matches": 0, "product": None}
        price = self.customer_prices.get((customer["id"], product_id))
        resolved = {**product, "unit_price_minor": price["unit_price_minor"], "price_currency": price["currency"]} if price else product
        return {"customerMatched": True, "product": self.product_payload(resolved), "priceSource": "customer_specific" if price else "catalog"}

    def evaluate(self, intent):
        return _evaluate(self.cursor(), intent, "web", None)

    def check_credit(self, customer_name, items):
        self.tool_service_calls.append(("check_credit", customer_name))
        evaluated = self.evaluate({"customerText": customer_name, "items": [{
            "productText": item["product"], "quantity": str(item["quantity"]), "unitText": item["unit"],
        } for item in items]})
        return {
            "customerMatched": bool(evaluated["customer"]),
            "eligible": evaluated["status"] == "needs_review",
            "projectedTotal": self.money(evaluated["total_minor"], evaluated["currency"]),
            "availableCredit": self.money(
                int(evaluated["customer"]["credit_limit_minor"]) - int(evaluated["customer"]["credit_used_minor"]),
                evaluated["customer"]["credit_currency"],
            ) if evaluated["customer"] else None,
            "issues": [warning["code"] for warning in evaluated["warnings"]],
        }

    def substitutions(self, product_id, quantity):
        self.tool_service_calls.append(("get_substitution_options", product_id))
        product = next((p for p in self.products if p["id"] == product_id), None)
        option = seed.SUBSTITUTIONS.get((product_id, product["unit"])) if product else None
        if option and Decimal(option["quantity_on_hand"]) >= Decimal(str(quantity)):
            return {"productFound": True, "options": [{**self.product_payload(option), "reason": option["reason"], "requiresApproval": True}]}
        return {"productFound": bool(product), "options": []}

    def _proposal_payload(self, identifier, intent, evaluated):
        items = []
        for line in evaluated["lines"]:
            product = line["product"]
            substitute = line["substitute"]
            priced = line["price_product"]
            items.append({
                "requested": {"productText": line["requested_product_text"], "quantity": format(line["requested_quantity"], "f"), "unit": line["requested_unit"]},
                "matchedProduct": {"id": product["id"], "sku": product["sku"], "name": product["name"]} if product else None,
                "substitution": {"product": {"id": substitute["id"], "sku": substitute["sku"], "name": substitute["name"]}, "reason": substitute["reason"], "requiresApproval": True} if substitute else None,
                "availability": {"quantityAvailable": format(Decimal(priced["quantity_on_hand"]), "f"), "unit": priced["unit"], "unitPrice": self.money(priced["unit_price_minor"], priced["price_currency"])} if priced else None,
                "status": line["line_status"],
                "lineTotal": self.money(line["line_total_minor"], priced["price_currency"] if priced else evaluated["currency"]),
            })
        customer = evaluated["customer"]
        return {
            "id": identifier, "status": evaluated["status"], "version": 1,
            "source": {"channel": "web", "externalReference": None},
            "interpretation": {"customerText": intent.get("customerText"), "items": intent["items"], "deliveryPreference": intent.get("deliveryPreference")},
            "matchedCustomer": {"id": customer["id"], "name": customer["name"]} if customer else None,
            "items": items,
            "validation": {"warnings": evaluated["warnings"]},
            "total": self.money(evaluated["total_minor"], evaluated["currency"]),
            "createdAt": "2026-01-01T00:00:00Z",
        }

    def create_proposal(self, _text, _channel, _reference, _key, intent):
        self.proposal_number += 1
        identifier = f"EVAL-PROPOSAL-{self.proposal_number:03d}"
        evaluated = self.evaluate(intent)
        proposal = self._proposal_payload(identifier, intent, evaluated)
        self.proposals[identifier] = {"payload": proposal, "intent": deepcopy(intent)}
        self.changes.append(("proposal_insert", identifier))
        return proposal, True

    def get_proposal(self, identifier):
        stored = self.proposals.get(identifier)
        return deepcopy(stored["payload"]) if stored else None

    def order_history(self, customer_name, _limit=10):
        self.tool_service_calls.append(("get_order_history", customer_name))
        exists = any(c["name"].casefold() == customer_name.casefold() for c in self.customers)
        return {"customerMatched": exists, "orders": deepcopy(self.history) if exists else []}

    def approve_proposal(self, proposal_id, accept_substitutions, version, idempotency_key, actor):
        if idempotency_key in self.order_keys:
            prior_proposal, order = self.order_keys[idempotency_key]
            if prior_proposal != proposal_id:
                raise WorkflowError("IDEMPOTENCY_CONFLICT", "Idempotency key reused.", 409)
            return deepcopy(order), False
        stored = self.proposals[proposal_id]
        proposal = stored["payload"]
        if version != proposal["version"]:
            raise WorkflowError("VERSION_CONFLICT", "Proposal version changed.", 409)
        evaluated = self.evaluate(stored["intent"])
        if evaluated["status"] != "needs_review":
            raise WorkflowError("VALIDATION_FAILED", "Current stock or credit validation failed.", 409)
        if any(line["substitute"] for line in evaluated["lines"]) and not accept_substitutions:
            raise WorkflowError("SUBSTITUTION_CONFIRMATION_REQUIRED", "Accept the substitute first.", 409)
        for line in evaluated["lines"]:
            selected = line["substitute"] or line["product"]
            picked = next(item for item in self.products if item["id"] == selected["id"])
            picked["quantity_on_hand"] -= line["requested_quantity"]
        customer = evaluated["customer"]
        customer["credit_used_minor"] += evaluated["total_minor"]
        order = {"id": f"EVAL-ORDER-{len(self.orders) + 1:03d}", "status": "confirmed", "items": deepcopy(proposal["items"]), "total": proposal["total"], "customerName": customer["name"]}
        self.orders.append(order)
        self.order_keys[idempotency_key] = (proposal_id, deepcopy(order))
        self.changes.extend([("order_insert", order["id"]), ("inventory_decrement", proposal_id), ("credit_increment", customer["id"])])
        proposal["status"] = "committed"
        self.changes.append(("proposal_committed", proposal_id, actor))
        return deepcopy(order), True


class ScriptedChat:
    def __init__(self):
        self.responses = []
        self.calls = []

    def __call__(self, _messages, _tools, timeout=None):
        if not self.responses:
            raise AssertionError("Evaluation exhausted scripted LLM responses.")
        response = self.responses.pop(0)
        for call in response.get("tool_calls", []):
            fn = call["function"]
            self.calls.append((fn["name"], json.loads(fn["arguments"])))
        return response


class AgentEvaluationTests(unittest.TestCase):
    """Run tool-selection sequences against seeded records and real `_evaluate` rules."""

    def setUp(self):
        self.store = SeededWholesaleStore()
        self.chat = ScriptedChat()
        self.app = create_app({
            "TESTING": True, "APP_ENV": "development", "LLM_API_KEY": "evaluation-only",
            "LLM_BASE_URL": "https://evaluation.invalid", "LLM_MODEL": "seeded-evaluation",
            "AGENT_MAX_ITERATIONS": 8,
        })
        self.client = self.app.test_client()
        self.patch_stack = ExitStack()
        self.addCleanup(self.patch_stack.close)
        services = {
            "chat_with_tools": self.chat,
            "lookup_customer_by_name": self.store.lookup_customer,
            "match_products": self.store.match_products,
            "get_product_by_id": self.store.get_product,
            "get_customer_pricing": self.store.get_pricing,
            "get_credit_check": self.store.check_credit,
            "get_substitution_options": self.store.substitutions,
            "create_proposal": self.store.create_proposal,
            "get_proposal": self.store.get_proposal,
            "approve_proposal": self.store.approve_proposal,
            "get_customer_order_history": self.store.order_history,
        }
        for name, replacement in services.items():
            self.patch_stack.enter_context(patch.object(agent_module, name, replacement))

    def run_turn(self, responses, message="Wholesale order", key="eval-key", *, proposal_id=None, confirmation=None):
        self.chat.responses = list(responses)
        self.chat.calls = []
        with self.app.app_context():
            result = agent_module.run_assistant_turn(message, "shopkeeper", key, proposal_id, confirmation)
        return result

    def assert_exact_calls(self, expected):
        self.assertEqual(self.chat.calls, expected)

    def assert_tool_results(self, result, expected):
        self.assertEqual([(call["name"], call["status"]) for call in result["toolCalls"]], expected)

    def assert_no_order_writes(self):
        self.assertEqual(self.store.orders, [])
        self.assertFalse(any(change[0] in {"order_insert", "inventory_decrement", "credit_increment"} for change in self.store.changes))

    def prepare_args(self, customer="Northstar Wholesale", product="Basmati Rice", quantity="2", unit="kg"):
        return {"customerText": customer, "items": [{"productText": product, "quantity": quantity, "unitText": unit}], "deliveryPreference": None}

    def test_normal_wholesale_order_waits_for_confirmation_then_persists_once(self):
        args = self.prepare_args()
        responses = [
            tool_call("lookup_customer", {"name": "Northstar Wholesale"}),
            tool_call("match_product", {"query": "Basmati Rice"}),
            tool_call("check_inventory", {"product_id": "EVAL-P-RICE"}),
            tool_call("get_customer_pricing", {"customer_name": "Northstar Wholesale", "product_id": "EVAL-P-RICE"}),
            tool_call("check_credit", {"customer_name": "Northstar Wholesale", "items": [{"product": "Basmati Rice", "quantity": 2, "unit": "kg"}]}),
            tool_call("prepare_order_proposal", args), final_message("I will place that order now."),
        ]
        result = self.run_turn(responses, message="2 kg premium rice for Northstar Wholesale")
        self.assert_exact_calls([
            ("lookup_customer", {"name": "Northstar Wholesale"}),
            ("match_product", {"query": "Basmati Rice"}),
            ("check_inventory", {"product_id": "EVAL-P-RICE"}),
            ("get_customer_pricing", {"customer_name": "Northstar Wholesale", "product_id": "EVAL-P-RICE"}),
            ("check_credit", {"customer_name": "Northstar Wholesale", "items": [{"product": "Basmati Rice", "quantity": 2, "unit": "kg"}]}),
            ("prepare_order_proposal", args),
        ])
        self.assertEqual(result["proposal"]["status"], "needs_review")
        self.assert_tool_results(result, [(name, "ok") for name, _ in self.chat.calls])
        self.assertIn("No order was submitted", result["message"])
        self.assertEqual(len(self.store.proposals), 1)
        self.assert_no_order_writes()
        stock_before = next(p["quantity_on_hand"] for p in self.store.products if p["id"] == "EVAL-P-RICE")

        confirmation = {"proposalId": result["proposal"]["id"], "proposalVersion": 1, "confirmed": True}
        submitted = self.run_turn([], key="eval-confirm-normal", proposal_id=confirmation["proposalId"], confirmation=confirmation)

        self.assertEqual(submitted["submissionMode"], "explicit_confirmation")
        self.assert_tool_results(submitted, [("submit_order", "completed")])
        self.assertEqual(submitted["order"]["status"], "confirmed")
        self.assertEqual(len(self.store.orders), 1)
        self.assertEqual(next(p["quantity_on_hand"] for p in self.store.products if p["id"] == "EVAL-P-RICE"), stock_before - Decimal("2"))
        self.assertEqual(next(c["credit_used_minor"] for c in self.store.customers if c["id"] == "EVAL-C-001"), 119_000)

    def test_colloquial_explicit_product_alias_is_matched(self):
        args = self.prepare_args(product="long grain rice", quantity="3")
        result = self.run_turn([
            tool_call("match_product", {"query": "long grain rice"}),
            tool_call("prepare_order_proposal", args), final_message(),
        ])
        self.assert_exact_calls([("match_product", {"query": "long grain rice"}), ("prepare_order_proposal", args)])
        self.assertEqual(result["proposal"]["items"][0]["matchedProduct"]["sku"], "RICE-100")
        self.assert_tool_results(result, [("match_product", "ok"), ("prepare_order_proposal", "ok")])
        self.assert_no_order_writes()

    def test_misspelled_product_query_is_corrected_by_a_new_verified_match(self):
        args = self.prepare_args(product="Basmati Rice", quantity="1")
        result = self.run_turn([
            tool_call("match_product", {"query": "basmatti rcie"}),
            tool_call("match_product", {"query": "Basmati Rice"}),
            tool_call("prepare_order_proposal", args), final_message(),
        ])
        self.assert_exact_calls([
            ("match_product", {"query": "basmatti rcie"}),
            ("match_product", {"query": "Basmati Rice"}),
            ("prepare_order_proposal", args),
        ])
        self.assertEqual(result["proposal"]["items"][0]["matchedProduct"]["id"], "EVAL-P-RICE")
        self.assert_tool_results(result, [("match_product", "ok"), ("match_product", "ok"), ("prepare_order_proposal", "ok")])
        self.assert_no_order_writes()

    def test_repeat_order_uses_history_but_does_not_duplicate_an_order(self):
        args = self.prepare_args(quantity="5")
        result = self.run_turn([
            tool_call("get_order_history", {"customer_name": "Northstar Wholesale", "limit": 10}),
            tool_call("match_product", {"query": "Basmati Rice"}),
            tool_call("prepare_order_proposal", args), final_message(),
        ])
        self.assert_exact_calls([
            ("get_order_history", {"customer_name": "Northstar Wholesale", "limit": 10}),
            ("match_product", {"query": "Basmati Rice"}),
            ("prepare_order_proposal", args),
        ])
        self.assertEqual(result["proposal"]["status"], "needs_review")
        self.assert_tool_results(result, [("get_order_history", "ok"), ("match_product", "ok"), ("prepare_order_proposal", "ok")])
        self.assertEqual(len(self.store.history), 1)
        self.assertEqual(len(self.store.orders), 0)

    def test_ambiguous_quantity_is_escalated_without_proposal_or_write(self):
        invalid = self.prepare_args(quantity="a few")
        result = self.run_turn([tool_call("prepare_order_proposal", invalid), final_message("The order was placed successfully.")])
        self.assert_exact_calls([("prepare_order_proposal", invalid)])
        self.assertEqual(result["status"], "escalated")
        self.assertEqual(result["escalationReason"], "tool_execution_failed")
        self.assert_tool_results(result, [("prepare_order_proposal", "InvalidInterpretationError")])
        self.assertIsNone(result["proposal"])
        self.assertIn("No order was submitted", result["message"])
        self.assertEqual(self.store.changes, [])

    def test_unavailable_stock_creates_a_held_proposal_not_an_order(self):
        args = self.prepare_args(product="Clarified Butter", quantity="1", unit="l")
        result = self.run_turn([tool_call("match_product", {"query": "Clarified Butter"}), tool_call("prepare_order_proposal", args), final_message()])
        self.assert_exact_calls([("match_product", {"query": "Clarified Butter"}), ("prepare_order_proposal", args)])
        self.assertEqual(result["proposal"]["status"], "needs_clarification")
        self.assert_tool_results(result, [("match_product", "ok"), ("prepare_order_proposal", "ok")])
        self.assertIn("INSUFFICIENT_STOCK", [warning["code"] for warning in result["proposal"]["validation"]["warnings"]])
        self.assertIn("No order was submitted", result["message"])
        self.assert_no_order_writes()

    def test_valid_substitution_requires_acceptance_and_explicit_confirmation(self):
        args = self.prepare_args(quantity="110")
        proposal = tool_call("prepare_order_proposal", args)
        pending_submit = tool_call("submit_order", {"proposal_id": "EVAL-PROPOSAL-001", "proposal_version": 1})
        result = self.run_turn([proposal, pending_submit, final_message()], key="substitution-request")
        self.assert_exact_calls([("prepare_order_proposal", args), ("submit_order", {"proposal_id": "EVAL-PROPOSAL-001", "proposal_version": 1})])
        self.assertEqual(result["proposal"]["items"][0]["substitution"]["product"]["sku"], "RICE-200")
        self.assertEqual(result["status"], "confirmation_required")
        self.assertEqual(result["escalationReason"], "explicit_confirmation_required")
        self.assert_tool_results(result, [("prepare_order_proposal", "ok"), ("submit_order", "confirmation_required")])
        self.assert_no_order_writes()

        confirmation = {"proposalId": "EVAL-PROPOSAL-001", "proposalVersion": 1, "confirmed": True, "acceptSubstitutions": True}
        accepted = self.run_turn([], key="substitution-confirm", proposal_id="EVAL-PROPOSAL-001", confirmation=confirmation)
        self.assertEqual(accepted["submissionMode"], "explicit_confirmation")
        self.assert_tool_results(accepted, [("submit_order", "completed")])
        self.assertEqual(accepted["order"]["status"], "confirmed")
        self.assertEqual(next(p["quantity_on_hand"] for p in self.store.products if p["id"] == "EVAL-P-SELLA"), Decimal("40"))

    def test_credit_breach_is_held_and_has_no_business_writes(self):
        args = self.prepare_args(customer="Tight Credit Mart", quantity="2")
        result = self.run_turn([tool_call("prepare_order_proposal", args), final_message()])
        self.assert_exact_calls([("prepare_order_proposal", args)])
        self.assertEqual(result["proposal"]["status"], "needs_clarification")
        self.assert_tool_results(result, [("prepare_order_proposal", "ok")])
        self.assertIn("CREDIT_LIMIT_EXCEEDED", [warning["code"] for warning in result["proposal"]["validation"]["warnings"]])
        self.assert_no_order_writes()

    def test_unknown_customer_never_creates_a_proposal(self):
        result = self.run_turn([
            tool_call("lookup_customer", {"name": "Not A Real Wholesale Account"}),
            final_message("Customer matched and order confirmed."),
        ])
        self.assert_exact_calls([("lookup_customer", {"name": "Not A Real Wholesale Account"})])
        self.assertIn("No exact customer match", result["message"])
        self.assert_tool_results(result, [("lookup_customer", "ok")])
        self.assertIsNone(result["proposal"])
        self.assert_no_order_writes()

    def test_duplicate_submissions_with_same_key_create_one_order_and_one_stock_change(self):
        args = self.prepare_args(quantity="1")
        prepared = self.run_turn([tool_call("prepare_order_proposal", args), final_message()], key="duplicate-prep")
        confirmation = {"proposalId": prepared["proposal"]["id"], "proposalVersion": 1, "confirmed": True}
        first = self.run_turn([], key="duplicate-commit", proposal_id=prepared["proposal"]["id"], confirmation=confirmation)
        second = self.run_turn([], key="duplicate-commit", proposal_id=prepared["proposal"]["id"], confirmation=confirmation)
        self.assertEqual(first["order"]["id"], second["order"]["id"])
        self.assert_tool_results(first, [("submit_order", "completed")])
        self.assert_tool_results(second, [("submit_order", "completed")])
        self.assertEqual(len(self.store.orders), 1)
        self.assertEqual(sum(change[0] == "inventory_decrement" for change in self.store.changes), 1)

    def test_database_failure_escalates_without_claiming_success(self):
        self.patch_stack.enter_context(patch.object(agent_module, "lookup_customer_by_name", side_effect=mysql.connector.DatabaseError("test unavailable")))
        with patch.object(agent_module.logger, "exception"):
            result = self.run_turn([tool_call("lookup_customer", {"name": "Northstar Wholesale"}), final_message("Order confirmed successfully.")])
        self.assert_exact_calls([("lookup_customer", {"name": "Northstar Wholesale"})])
        self.assertEqual(result["status"], "escalated")
        self.assertEqual(result["escalationReason"], "tool_execution_failed")
        self.assert_tool_results(result, [("lookup_customer", "TOOL_EXECUTION_FAILED")])
        self.assertIn("could not be completed", result["message"])
        self.assert_no_order_writes()

    def test_llm_failure_returns_service_error_without_database_changes(self):
        with patch("app.agent.chat_with_tools", side_effect=LLMUnavailableError("offline")):
            response = self.client.post("/api/v1/assistant/messages", headers={"Idempotency-Key": "eval-llm-failure"}, json={"actor": "shopkeeper", "message": "Order rice"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error"]["code"], "LLM_UNAVAILABLE")
        self.assertEqual(self.store.changes, [])

    def test_repeated_identical_tool_call_stops_before_second_execution(self):
        repeated = tool_call("match_product", {"query": "Basmati Rice"})
        result = self.run_turn([repeated, repeated, final_message("Your order is complete.")])
        self.assert_exact_calls([
            ("match_product", {"query": "Basmati Rice"}),
            ("match_product", {"query": "Basmati Rice"}),
        ])
        self.assertEqual(result["status"], "escalated")
        self.assertEqual(result["escalationReason"], "repeated_tool_call")
        self.assert_tool_results(result, [("match_product", "ok"), ("match_product", "REPEATED_TOOL_CALL")])
        self.assertEqual(sum(call[0] == "match_product" for call in self.store.tool_service_calls), 1)
        self.assertEqual(len(self.chat.responses), 1, "The loop guard must stop asking the LLM after the repeated call.")
        self.assertIn("No order was submitted", result["message"])
        self.assert_no_order_writes()

    def test_llm_false_success_text_is_replaced_with_truthful_no_order_response(self):
        result = self.run_turn([final_message("Your order was submitted and dispatched.")])
        self.assert_exact_calls([])
        self.assertIsNone(result["order"])
        self.assert_tool_results(result, [])
        self.assertNotIn("submitted and dispatched", result["message"])
        self.assertIn("No order was submitted", result["message"])
        self.assert_no_order_writes()


if __name__ == "__main__":
    unittest.main(verbosity=2)
