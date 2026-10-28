"""Order API tests that do not invoke an external LLM or live MySQL."""

import unittest
from io import BytesIO
from unittest.mock import patch

from app import create_app


class OrderApiTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app(
            {
                "TESTING": True,
                "APP_ENV": "development",
                "LLM_API_KEY": "",
                "LLM_BASE_URL": "",
                "LLM_MODEL": "",
                "MYSQL_HOST": "",
                "MYSQL_DATABASE": "",
                "MYSQL_USER": "",
                "MYSQL_PASSWORD": "",
            }
        ).test_client()

    def test_proposal_requires_idempotency_key(self):
        response = self.client.post(
            "/api/v1/order-proposals",
            json={"source": {"channel": "web"}, "customerId": "customer-1", "message": {"text": "Order 2 kg rice"}},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"]["code"], "IDEMPOTENCY_KEY_REQUIRED")

    @patch("app.orders.create_proposal")
    @patch("app.orders.build_order_interpretation")
    def test_customer_web_proposal_uses_deterministic_parser(self, parse_order, create):
        parse_order.return_value = (
            {"customerText": "Test Shop", "customerId": "customer-1", "items": [{"productText": "Rice", "productId": "product-1", "quantity": "2", "unitText": "kg"}], "deliveryPreference": None},
            "2 kg Rice",
        )
        create.return_value = ({"id": "proposal-1", "status": "needs_review"}, True)
        response = self.client.post(
            "/api/v1/order-proposals",
            headers={"Idempotency-Key": "request-1"},
            json={"source": {"channel": "web"}, "customerId": "customer-1", "message": {"text": "2 kg Rice"}},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"proposal": {"id": "proposal-1", "status": "needs_review"}})
        parse_order.assert_called_once_with("customer-1", "2 kg Rice", None)
        create.assert_called_once()

    @patch("app.orders.create_proposal")
    @patch("app.orders.build_order_interpretation")
    def test_deterministic_proposal_records_source_and_request_hash(self, parse_order, create):
        parse_order.return_value = ({"customerId": "customer-1", "items": []}, "2 kg Rice")
        create.return_value = ({"id": "proposal-1", "status": "needs_review"}, True)

        response = self.client.post(
            "/api/v1/order-proposals",
            headers={"Idempotency-Key": "request-1"},
            json={"source": {"channel": "web"}, "customerId": "customer-1", "message": {"text": "2 kg Rice"}},
        )

        self.assertEqual(response.status_code, 200)
        args, kwargs = create.call_args
        self.assertEqual(args[:4], ("2 kg Rice", "web", None, "request-1"))
        self.assertEqual(args[4], {"customerId": "customer-1", "items": []})
        self.assertEqual(len(args[5]), 64)

    def test_unconnected_channels_are_not_accepted(self):
        response = self.client.post(
            "/api/v1/order-proposals",
            headers={"Idempotency-Key": "request-1"},
            json={"source": {"channel": "phone"}, "message": {"text": "Order rice"}},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.get_json()["error"]["code"], "UNSUPPORTED_CHANNEL")

    @patch("app.orders.find_idempotent_proposal", return_value=None)
    def test_audio_flow_reports_missing_transcription_provider(self, _find_existing):
        response = self.client.post(
            "/api/v1/audio/order-proposals",
            headers={"Idempotency-Key": "audio-1"},
            data={"audio": (BytesIO(b"audio bytes"), "order.wav", "audio/wav")},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error"]["code"], "TRANSCRIPTION_NOT_CONFIGURED")

    @patch("app.orders.process_order_message", return_value=({"id": "proposal-kn"}, True))
    @patch("app.orders.transcribe_audio", return_value="2 ಕೆಜಿ ಅಕ್ಕಿ")
    @patch("app.orders.find_idempotent_proposal", return_value=None)
    def test_audio_passes_selected_kannada_language_to_transcriber(self, _find_existing, transcribe, _process):
        response = self.client.post(
            "/api/v1/audio/order-proposals",
            headers={"Idempotency-Key": "audio-kannada"},
            data={
                "audio": (BytesIO(b"audio bytes"), "order.wav", "audio/wav"),
                "language": "kn-IN",
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        transcribe.assert_called_once_with(b"audio bytes", "audio/wav", "kn")

    def test_audio_rejects_unsupported_speech_language(self):
        response = self.client.post(
            "/api/v1/audio/order-proposals",
            headers={"Idempotency-Key": "audio-invalid-language"},
            data={
                "audio": (BytesIO(b"audio bytes"), "order.wav", "audio/wav"),
                "language": "fr-FR",
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"]["code"], "UNSUPPORTED_LANGUAGE")

    @patch("app.orders.transcribe_audio")
    @patch("app.orders.find_idempotent_proposal")
    def test_audio_idempotent_replay_does_not_transcribe_again(self, find_existing, transcribe):
        proposal = {"id": "proposal-voice", "transcript": "Order 2 kg rice"}
        find_existing.return_value = proposal
        response = self.client.post(
            "/api/v1/audio/order-proposals",
            headers={"Idempotency-Key": "audio-1"},
            data={"audio": (BytesIO(b"audio bytes"), "order.wav", "audio/wav")},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"transcript": "Order 2 kg rice", "proposal": proposal})
        transcribe.assert_not_called()

    def test_approval_is_disabled_outside_local_development_until_auth_exists(self):
        client = create_app({"TESTING": True, "APP_ENV": "production"}).test_client()

        response = client.post(
            "/api/v1/order-proposals/proposal-1/approval",
            headers={"Idempotency-Key": "approve-1"},
            json={"decision": "approve", "proposalVersion": 1},
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error"]["code"], "AUTHORIZATION_NOT_CONFIGURED")

    def test_approval_rejects_non_string_decisions_as_client_errors(self):
        response = self.client.post(
            "/api/v1/order-proposals/proposal-1/approval",
            headers={"Idempotency-Key": "approve-1"},
            json={"decision": [], "proposalVersion": True},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"]["code"], "INVALID_REQUEST")

    def test_orders_read_returns_json_error_when_database_is_not_configured(self):
        response = self.client.get("/api/v1/orders")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error"]["code"], "DATABASE_NOT_CONFIGURED")

    def test_customer_proposal_requires_registered_customer_id(self):
        response = self.client.post(
            "/api/v1/order-proposals",
            headers={"Idempotency-Key": "request-1"},
            json={"source": {"channel": "web"}, "message": {"text": "2 kg Rice"}},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"]["code"], "CUSTOMER_REQUIRED")

    def test_pending_fulfillment_requires_explicit_confirmation(self):
        response = self.client.post("/api/v1/orders/order-1/fulfill-pending", json={})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.get_json()["error"]["code"], "EXPLICIT_CONFIRMATION_REQUIRED")

    @patch("app.orders.fulfill_pending_order", return_value=({"id": "order-1", "status": "confirmed"}, True))
    def test_pending_fulfillment_requires_key_and_calls_transactional_service(self, fulfill):
        response = self.client.post(
            "/api/v1/orders/order-1/fulfill-pending",
            headers={"Idempotency-Key": "fulfill-1"},
            json={"confirm": True},
        )
        self.assertEqual(response.status_code, 201)
        fulfill.assert_called_once_with("order-1", "fulfill-1", actor="local-development-user")

    @patch("app.orders.get_customer_order_history_by_id", return_value={"customerMatched": True, "customer": {"id": "C-1", "name": "Retailer"}, "orders": [{"id": "O-1", "status": "partially_fulfilled", "hasPending": True}]})
    def test_customer_status_reads_only_the_selected_registered_customer(self, history):
        response = self.client.get("/api/v1/customer-orders?customerId=C-1")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["orders"][0]["hasPending"])
        history.assert_called_once_with("C-1", 20)

    def test_customer_status_requires_a_registered_customer_id(self):
        response = self.client.get("/api/v1/customer-orders")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"]["code"], "CUSTOMER_REQUIRED")

    def test_assistant_rejects_unsupported_interface_locale(self):
        response = self.client.post(
            "/api/v1/assistant/messages",
            headers={"Idempotency-Key": "helper-invalid-locale"},
            json={
                "actor": "customer", "purpose": "helper", "message": "Hi",
                "pageContext": {"page": "customer-order", "locale": "fr"},
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"]["code"], "INVALID_REQUEST")

    def test_assistant_rejects_non_string_interface_locale(self):
        response = self.client.post(
            "/api/v1/assistant/messages",
            headers={"Idempotency-Key": "helper-nonstring-locale"},
            json={
                "actor": "customer", "purpose": "helper", "message": "Hi",
                "pageContext": {"page": "customer-order", "locale": []},
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"]["code"], "INVALID_REQUEST")


if __name__ == "__main__":
    unittest.main()
