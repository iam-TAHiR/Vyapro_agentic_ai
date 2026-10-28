"""Tests for tool permissions, bounded orchestration, and safe order actions."""

import json
import unittest
from unittest.mock import patch

from app import create_app
from app.agent import _call_tool, _deterministic_tool_calls, _trusted_response, registered_tools


def tool_call(name, arguments, call_id="call-1"):
    return {
        "role": "assistant",
        "tool_calls": [{
            "id": call_id,
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)},
        }],
    }


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "APP_ENV": "development",
            "LLM_API_KEY": "test-only",
            "LLM_BASE_URL": "https://llm.invalid",
            "LLM_MODEL": "test-model",
        })
        self.client = self.app.test_client()

    def test_tool_registry_restricts_customer_order_history(self):
        customer_names = {tool["function"]["name"] for tool in registered_tools("customer")}
        shopkeeper_names = {tool["function"]["name"] for tool in registered_tools("shopkeeper")}

        self.assertNotIn("get_order_history", customer_names)
        self.assertNotIn("list_orders", customer_names)
        self.assertIn("get_my_order_history", customer_names)
        self.assertNotIn("get_my_order_history", shopkeeper_names)
        self.assertNotIn("inspect_order", customer_names)
        self.assertNotIn("inspect_proposal", customer_names)
        self.assertIn("get_order_history", shopkeeper_names)
        self.assertIn("list_orders", shopkeeper_names)
        self.assertIn("inspect_order", shopkeeper_names)
        self.assertIn("inspect_proposal", shopkeeper_names)
        self.assertIn("submit_order", customer_names)

    def test_floating_helper_has_explanation_tool_only(self):
        names = {tool["function"]["name"] for tool in registered_tools("shopkeeper", "helper")}
        self.assertEqual(names, {"explain_page"})

    def test_helper_is_read_only_even_for_order_requests(self):
        response = self.client.post(
            "/api/v1/assistant/messages",
            headers={"Idempotency-Key": "helper-order-request"},
            json={
                "actor": "shopkeeper", "purpose": "helper", "mode": "deterministic",
                "message": "Send 5 kg basmati rice", "pageContext": {"page": "inventory"},
            },
        )
        body = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["toolCalls"], [])
        self.assertIsNone(body["proposal"])
        self.assertIsNone(body["order"])

    @patch("app.agent.get_customer_by_id")
    def test_floating_helper_greets_without_reading_customer_or_business_records(self, customer_lookup):
        response = self.client.post(
            "/api/v1/assistant/messages",
            headers={"Idempotency-Key": "helper-greeting"},
            json={
                "actor": "customer", "purpose": "helper", "selectedCustomerId": "C-1",
                "message": "Hi!", "pageContext": {"page": "customer-order"},
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertIn("Hi!", body["message"])
        self.assertIsNone(body["order"])
        self.assertEqual(body["toolCalls"], [])
        customer_lookup.assert_not_called()

    def test_floating_helper_answers_general_question_without_order_tools(self):
        response = self.client.post(
            "/api/v1/assistant/messages",
            headers={"Idempotency-Key": "helper-about-vyapro"},
            json={"actor": "shopkeeper", "purpose": "helper", "message": "What is Vyapro?"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("manage customer orders", response.get_json()["message"])
        self.assertEqual(response.get_json()["toolCalls"], [])

    def test_floating_helper_uses_selected_interface_language(self):
        response = self.client.post(
            "/api/v1/assistant/messages",
            headers={"Idempotency-Key": "helper-kannada-locale"},
            json={
                "actor": "customer", "purpose": "helper", "mode": "deterministic",
                "message": "Hi", "pageContext": {"page": "customer-order", "locale": "kn"},
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("ನಮಸ್ಕಾರ", response.get_json()["message"])
        self.assertIsNone(response.get_json()["order"])

    def test_partial_order_response_uses_selected_interface_language_truthfully(self):
        proposal = {
            "id": "P-1", "status": "needs_review", "total": {"amountMinor": 5000, "currency": "INR"},
            "items": [{
                "offeredQuantity": "5", "remainingQuantity": "5",
                "requested": {"unit": "kg", "productText": "Rice"},
            }],
        }
        hindi = _trusted_response([], proposal=proposal, locale="hi")
        kannada = _trusted_response([], proposal=proposal, locale="kn")
        self.assertIn("5 kg", hindi)
        self.assertIn("लंबित", hindi)
        self.assertIn("5 kg", kannada)
        self.assertIn("ಬಾಕಿ", kannada)
        self.assertIn("ऑर्डर नहीं", hindi)

    def test_floating_helper_redirects_order_request_to_authorized_workflow(self):
        response = self.client.post(
            "/api/v1/assistant/messages",
            headers={"Idempotency-Key": "helper-order-redirect"},
            json={"actor": "customer", "purpose": "helper", "message": "Please place an order"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Customer Ordering", response.get_json()["message"])
        self.assertIn("Nothing has been submitted", response.get_json()["message"])
        self.assertIsNone(response.get_json()["proposal"])

    def test_helper_cannot_confirm_an_order(self):
        response = self.client.post(
            "/api/v1/assistant/messages",
            headers={"Idempotency-Key": "helper-confirm-order"},
            json={
                "actor": "shopkeeper", "purpose": "helper", "message": "Confirm",
                "confirmation": {"proposalId": "p-1", "proposalVersion": 1, "confirmed": True},
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["error"]["code"], "HELPER_READ_ONLY")

    @patch("app.agent.get_customer_order_history_by_id", return_value={"customerMatched": True, "orders": []})
    @patch("app.agent.get_customer_by_id", return_value={"id": "C-1", "name": "Selected Shop"})
    def test_customer_order_history_is_limited_to_the_selected_customer(self, _customer, history):
        response = self.client.post(
            "/api/v1/assistant/messages",
            headers={"Idempotency-Key": "turn-own-order-history"},
            json={
                "actor": "customer", "mode": "deterministic", "selectedCustomerId": "C-1",
                "message": "Show my recent orders", "pageContext": {"page": "customer-order"},
            },
        )

        body = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["toolCalls"][0]["name"], "get_my_order_history")
        self.assertIn("no saved orders", body["message"])
        history.assert_called_once_with("C-1", 10)

    @patch("app.agent.get_customer_by_id", return_value={"id": "C-1", "name": "Selected Shop"})
    def test_customer_question_about_orders_explains_the_ordering_screen(self, _customer):
        response = self.client.post(
            "/api/v1/assistant/messages",
            headers={"Idempotency-Key": "turn-about-orders"},
            json={
                "actor": "customer", "mode": "deterministic", "selectedCustomerId": "C-1",
                "message": "Tell me about orders", "pageContext": {"page": "customer-order"},
            },
        )

        body = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["toolCalls"][0]["name"], "explain_page")
        self.assertIn("search products", body["message"])

    @patch("app.agent.get_order", return_value={
        "id": "order-42", "customerName": "Kaveri Provision House", "status": "confirmed",
        "total": {"amountMinor": 23800, "currency": "INR"},
        "items": [{"quantity": "2", "unit": "kg", "product": {"name": "Basmati Rice"}}],
    })
    def test_shopkeeper_page_context_inspects_the_current_order(self, get_order_mock):
        response = self.client.post(
            "/api/v1/assistant/messages",
            headers={"Idempotency-Key": "turn-current-order-context"},
            json={
                "actor": "shopkeeper", "mode": "deterministic", "message": "Why is this order held?",
                "pageContext": {"page": "orders", "entityType": "order", "entityId": "order-42"},
            },
        )

        body = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["toolCalls"][0]["name"], "inspect_order")
        self.assertIn("Basmati Rice", body["message"])
        get_order_mock.assert_called_once_with("order-42")

    @patch("app.agent.match_products", return_value=[{"name": "India Gate Basmati Rice"}])
    def test_current_order_context_does_not_override_a_different_stock_question(self, _matches):
        tools = registered_tools("shopkeeper")
        calls = _deterministic_tool_calls(
            "Check rice stock",
            "shopkeeper",
            tools,
            {"page_context": {"page": "orders", "entityType": "order", "entityId": "order-42"}},
        )

        self.assertEqual(calls[0]["function"]["name"], "match_product")

    @patch("app.agent.match_products", return_value=[])
    def test_customer_cannot_request_shopkeeper_record_context(self, _matches):
        response = self.client.post(
            "/api/v1/assistant/messages",
            headers={"Idempotency-Key": "turn-customer-order-context"},
            json={
                "actor": "customer", "mode": "deterministic", "message": "Why is this held?",
                "pageContext": {"page": "orders", "entityType": "order", "entityId": "order-42"},
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertNotIn("inspect_order", [call["name"] for call in body["toolCalls"]])

    def test_page_context_rejects_unknown_fields(self):
        response = self.client.post(
            "/api/v1/assistant/messages",
            headers={"Idempotency-Key": "turn-invalid-page-context"},
            json={"actor": "shopkeeper", "message": "Help", "pageContext": {"page": "orders", "secret": "value"}},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"]["code"], "INVALID_REQUEST")

    def test_deterministic_assistant_explains_the_current_page(self):
        response = self.client.post(
            "/api/v1/assistant/messages",
            headers={"Idempotency-Key": "turn-page-help"},
            json={
                "actor": "shopkeeper", "mode": "deterministic", "message": "What does this page show?",
                "pageContext": {"page": "inventory"},
            },
        )

        body = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["toolCalls"][0]["name"], "explain_page")
        self.assertIn("product code", body["message"])

    @patch("app.agent.list_orders", return_value=([{
        "id": "ORD-100", "customerName": "Kaveri Provision House", "status": "partially_fulfilled",
        "total": {"amountMinor": 12500, "currency": "INR"}, "hasPending": True,
    }], None))
    def test_shopkeeper_available_orders_lists_saved_orders_without_customer_lookup(self, list_orders_mock):
        response = self.client.post(
            "/api/v1/assistant/messages",
            headers={"Idempotency-Key": "turn-available-orders"},
            json={
                "actor": "shopkeeper", "mode": "deterministic", "message": "available orders",
                "pageContext": {"page": "shopkeeper-assistant", "locale": "en"},
            },
        )

        body = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["toolCalls"][0]["name"], "list_orders")
        self.assertIn("ORD-100", body["message"])
        self.assertIn("Kaveri Provision House", body["message"])
        self.assertIn("pending fulfillment", body["message"])
        list_orders_mock.assert_called_once_with(status=None, query=None, limit=10)

    @patch("app.agent.lookup_customer_by_name")
    @patch("app.agent.chat_with_tools")
    def test_customer_cannot_call_shopkeeper_order_history(self, chat, lookup):
        chat.side_effect = [tool_call("get_order_history", {"customer_name": "A"}), {"role": "assistant", "content": "I cannot access that."}]
        response = self.client.post(
            "/api/v1/assistant/messages",
            headers={"Idempotency-Key": "turn-customer-history"},
            json={"actor": "customer", "message": "Show all orders"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["toolCalls"][0]["status"], "TOOL_NOT_PERMITTED")
        lookup.assert_not_called()

    @patch("app.agent.match_products")
    @patch("app.agent.chat_with_tools")
    def test_invalid_tool_arguments_are_not_executed(self, chat, match):
        chat.side_effect = [tool_call("match_product", {"query": "rice", "unexpected": "write"}), {"role": "assistant", "content": "Please rephrase."}]
        response = self.client.post(
            "/api/v1/assistant/messages",
            headers={"Idempotency-Key": "turn-invalid-tool"},
            json={"actor": "shopkeeper", "message": "Find rice"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["toolCalls"][0]["status"], "INVALID_TOOL_ARGUMENTS")
        match.assert_not_called()

    @patch("app.agent.create_proposal", return_value=({"id": "proposal-1", "status": "needs_review", "version": 1, "items": [], "validation": {"warnings": []}}, True))
    @patch("app.agent.chat_with_tools")
    def test_valid_tool_selected_proposal_uses_existing_order_service(self, chat, create):
        chat.side_effect = [
            tool_call("prepare_order_proposal", {"customerText": "Sharma Stores", "items": [{"productText": "Rice", "quantity": "2", "unitText": "kg"}]}),
            {"role": "assistant", "content": "I prepared a proposal for review."},
        ]
        response = self.client.post(
            "/api/v1/assistant/messages",
            headers={"Idempotency-Key": "turn-proposal"},
            json={"actor": "shopkeeper", "message": "Order two kg rice for Sharma Stores"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["proposal"]["id"], "proposal-1")
        create.assert_called_once()
        self.assertEqual(create.call_args.args[1:4], ("web", None, "turn-proposal"))

    @patch("app.agent.clarify_proposal", return_value=({"id": "proposal-1", "status": "needs_review"}, True))
    @patch("app.agent.interpret_order", return_value={"customerText": "Sharma Stores", "items": [{"productText": "Rice", "quantity": "2", "unitText": "kg"}], "deliveryPreference": None})
    @patch("app.agent.get_clarification_context", return_value={"original_text": "Order rice", "version": 2})
    def test_clarification_tool_reuses_existing_interpreter_and_service(self, context, interpret, clarify):
        result = _call_tool("clarify_order", {"proposal_id": "proposal-1", "answer": "Sharma Stores"}, {"idempotency_key": "clarification-1"})

        self.assertEqual(result["proposal"]["status"], "needs_review")
        interpret.assert_called_once_with("Order rice\nClarification: Sharma Stores")
        clarify.assert_called_once()

    @patch("app.agent.approve_proposal")
    @patch("app.agent.get_proposal", return_value={
        "id": "proposal-1", "status": "needs_review", "version": 3,
        "items": [{"substitution": None}], "validation": {"warnings": []},
        "total": {"amountMinor": 5000, "currency": "INR"},
    })
    def test_submit_tool_requires_confirmation_by_default(self, get_proposal_mock, approve):
        with self.app.app_context():
            result = _call_tool(
                "submit_order",
                {"proposal_id": "proposal-1", "proposal_version": 3},
                {"confirmation": None, "autonomous_enabled": False, "autonomous_max_minor": 0, "idempotency_key": "submit-1", "actor": "customer", "request_id": "req-1"},
            )

        self.assertTrue(result["confirmationRequired"])
        approve.assert_not_called()

    @patch("app.agent.get_proposal", return_value={
        "id": "proposal-1", "status": "needs_review", "version": 3,
        "items": [{"substitution": None}], "validation": {"warnings": []},
        "total": {"amountMinor": 5000, "currency": "INR"},
    })
    @patch("app.agent.approve_proposal", return_value=({"id": "order-1", "status": "confirmed"}, True))
    def test_explicit_confirmation_creates_order_through_approval_service(self, approve, get_proposal_mock):
        with self.app.app_context():
            result = _call_tool(
                "submit_order",
                {"proposal_id": "proposal-1", "proposal_version": 3},
                {"confirmation": {"proposalId": "proposal-1", "proposalVersion": 3, "confirmed": True}, "autonomous_enabled": False, "autonomous_max_minor": 0, "idempotency_key": "submit-1", "actor": "customer", "request_id": "req-1"},
            )

        self.assertEqual(result["order"]["id"], "order-1")
        self.assertEqual(result["submissionMode"], "explicit_confirmation")
        approve.assert_called_once_with("proposal-1", False, 3, "submit-1", actor="agent:customer")

    @patch("app.agent.create_proposal", return_value=({"id": "proposal-1", "status": "needs_review"}, True))
    @patch("app.agent.validate_interpretation", return_value={"customerText": "Model Guessed Customer", "items": []})
    def test_registered_customer_selection_overrides_model_customer_text(self, _validate, create):
        _call_tool("prepare_order_proposal", {"items": []}, {
            "message": "Order two kilos rice",
            "idempotency_key": "customer-selected-1",
            "selected_customer": {"id": "C-1", "name": "Registered Shop"},
        })

        self.assertEqual(create.call_args.args[4]["customerText"], "Registered Shop")

    @patch("app.agent.approve_proposal")
    @patch("app.agent.get_proposal", return_value={
        "id": "proposal-1", "status": "needs_review", "version": 3,
        "matchedCustomer": {"id": "C-OTHER", "name": "Other Shop"}, "items": [],
        "validation": {"warnings": []}, "total": {"amountMinor": 100, "currency": "INR"},
    })
    def test_selected_customer_cannot_confirm_another_customers_proposal(self, _get, approve):
        from app.order_service import WorkflowError

        with self.app.app_context(), self.assertRaises(WorkflowError):
            _call_tool("submit_order", {"proposal_id": "proposal-1", "proposal_version": 3}, {
                "confirmation": {"proposalId": "proposal-1", "proposalVersion": 3, "confirmed": True},
                "selected_customer": {"id": "C-1", "name": "Selected Shop"}, "autonomous_enabled": False,
                "autonomous_max_minor": 0, "idempotency_key": "wrong-customer", "actor": "customer", "request_id": "req-2",
            })

        approve.assert_not_called()

    @patch("app.agent.get_customer_by_id", return_value={"id": "C-1", "name": "Registered Shop"})
    @patch("app.agent.chat_with_tools", return_value={"role": "assistant", "content": "hello"})
    def test_customer_turn_sends_server_resolved_registered_identity_to_agent(self, chat, _customer):
        response = self.client.post(
            "/api/v1/assistant/messages",
            headers={"Idempotency-Key": "turn-registered-customer"},
            json={"actor": "customer", "selectedCustomerId": "C-1", "message": "I need rice"},
        )

        self.assertEqual(response.status_code, 200)
        context = json.loads(chat.call_args.args[0][1]["content"])
        self.assertEqual(context["selectedCustomer"], {"id": "C-1", "name": "Registered Shop"})

    def test_unconfigured_llm_fails_closed_without_claiming_completion(self):
        client = create_app({"TESTING": True, "APP_ENV": "development"}).test_client()
        response = client.post(
            "/api/v1/assistant/messages",
            headers={"Idempotency-Key": "turn-no-llm"},
            json={"actor": "customer", "message": "I need rice"},
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error"]["code"], "LLM_NOT_CONFIGURED")

    @patch("app.agent.chat_with_tools", return_value={"role": "assistant", "content": "The order was submitted successfully."})
    def test_model_cannot_claim_order_submission_without_backend_order(self, _chat):
        response = self.client.post(
            "/api/v1/assistant/messages",
            headers={"Idempotency-Key": "turn-no-fake-order"},
            json={"actor": "customer", "message": "Did you order this?"},
        )

        body = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(body["order"])
        self.assertIn("No order was submitted", body["message"])

    @patch("app.agent.chat_with_tools")
    def test_agent_iteration_limit_is_bounded(self, chat):
        chat.return_value = tool_call("match_product", {"query": "rice"})
        app = create_app({
            "TESTING": True, "APP_ENV": "development", "LLM_API_KEY": "test-only",
            "LLM_BASE_URL": "https://llm.invalid", "LLM_MODEL": "test-model",
            "AGENT_MAX_ITERATIONS": 1,
        })
        with patch("app.agent.match_products", return_value=[]):
            response = app.test_client().post(
                "/api/v1/assistant/messages",
                headers={"Idempotency-Key": "turn-bounded"},
                json={"actor": "shopkeeper", "message": "Find rice"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(chat.call_count, 1)
        self.assertEqual(response.get_json()["escalationReason"], "iteration_limit")


if __name__ == "__main__":
    unittest.main()
