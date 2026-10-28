"""Database health tests that do not require a live MySQL server."""

import unittest
from unittest.mock import call
from unittest.mock import MagicMock, patch

from app import create_app


class DatabaseHealthTests(unittest.TestCase):
    def test_database_health_reports_not_configured_without_connecting(self):
        client = create_app({
            "TESTING": True,
            "MYSQL_HOST": "",
            "MYSQL_DATABASE": "",
            "MYSQL_USER": "",
            "MYSQL_PASSWORD": "",
        }).test_client()

        with patch("app.database.mysql.connector.connect") as connect:
            response = client.get("/api/v1/health/database")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.get_json(),
            {"status": "not_configured", "service": "vyapro-database"},
        )
        connect.assert_not_called()

    def test_database_health_runs_select_one_and_closes_connection(self):
        client = create_app(
            {
                "TESTING": True,
                "MYSQL_HOST": "localhost",
                "MYSQL_PORT": "3306",
                "MYSQL_DATABASE": "vyapro_test",
                "MYSQL_USER": "test_user",
                "MYSQL_PASSWORD": "test_password",
                "MYSQL_CONNECT_TIMEOUT": "3",
            }
        ).test_client()
        connection = MagicMock()

        with patch("app.database.mysql.connector.connect", return_value=connection) as connect:
            response = client.get("/api/v1/health/database")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ok", "service": "vyapro-database"})
        connect.assert_called_once()
        connection.cursor.return_value.execute.assert_has_calls(
            [call("SET time_zone = '+00:00'"), call("SELECT 1")]
        )
        connection.close.assert_called_once()

    def test_existing_health_does_not_depend_on_database_configuration(self):
        client = create_app({
            "TESTING": True,
            "MYSQL_HOST": "",
            "MYSQL_DATABASE": "",
            "MYSQL_USER": "",
            "MYSQL_PASSWORD": "",
        }).test_client()

        response = client.get("/api/v1/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ok", "service": "vyapro-api"})
