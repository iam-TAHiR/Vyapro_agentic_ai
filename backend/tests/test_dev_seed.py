import unittest

from app.database import DatabaseNotConfiguredError
from seed_dev import validate_seed_target


class DevelopmentSeedSafetyTests(unittest.TestCase):
    def test_requires_development_environment(self):
        with self.assertRaisesRegex(ValueError, "VYAPRO_ENV=development"):
            validate_seed_target({"APP_ENV": "production", "MYSQL_DATABASE": "shop_dev"})

    def test_requires_database_configuration(self):
        with self.assertRaises(DatabaseNotConfiguredError):
            validate_seed_target({"APP_ENV": "development", "MYSQL_DATABASE": "vyapro_dev"})

    def test_refuses_database_without_development_suffix(self):
        with self.assertRaisesRegex(ValueError, "end with _dev"):
            validate_seed_target({
                "APP_ENV": "development",
                "MYSQL_HOST": "localhost",
                "MYSQL_DATABASE": "vyapro",
                "MYSQL_USER": "user",
                "MYSQL_PASSWORD": "password",
            })

    def test_accepts_explicit_development_database(self):
        validate_seed_target({
            "APP_ENV": "development",
            "MYSQL_HOST": "localhost",
            "MYSQL_DATABASE": "vyapro_dev",
            "MYSQL_USER": "user",
            "MYSQL_PASSWORD": "password",
        })


if __name__ == "__main__":
    unittest.main()
