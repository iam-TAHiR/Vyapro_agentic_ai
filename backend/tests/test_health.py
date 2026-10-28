"""Tests for the health endpoint."""

import unittest

from app import create_app


class HealthEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app({"TESTING": True}).test_client()

    def test_health_returns_ok_json(self):
        response = self.client.get("/api/v1/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ok", "service": "vyapro-api"})


if __name__ == "__main__":
    unittest.main()
