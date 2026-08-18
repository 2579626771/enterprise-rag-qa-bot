import unittest

import app.config as config
from app.services import user_service


class TestProductionConfig(unittest.TestCase):
    def setUp(self):
        self.saved_config = {
            name: getattr(config, name)
            for name in (
                "APP_ENV",
                "MYSQL_ENABLED",
                "MYSQL_PASSWORD",
                "JWT_SECRET",
                "DEFAULT_ADMIN_USERNAME",
                "DEFAULT_ADMIN_PASSWORD",
            )
        }
        self.saved_user_mysql_enabled = user_service.MYSQL_ENABLED
        self.saved_user_repo = user_service.MySQLUserRepo

    def tearDown(self):
        for name, value in self.saved_config.items():
            setattr(config, name, value)
        user_service.MYSQL_ENABLED = self.saved_user_mysql_enabled
        user_service.MySQLUserRepo = self.saved_user_repo

    def _valid_production_config(self):
        config.APP_ENV = "production"
        config.MYSQL_ENABLED = True
        config.MYSQL_PASSWORD = "real-mysql-password"
        config.JWT_SECRET = "a" * 40
        config.DEFAULT_ADMIN_USERNAME = "rag_admin"
        config.DEFAULT_ADMIN_PASSWORD = "real-admin-password"

    def test_production_rejects_default_jwt_and_admin(self):
        config.APP_ENV = "production"
        config.MYSQL_ENABLED = True
        config.MYSQL_PASSWORD = "real-mysql-password"
        config.JWT_SECRET = "dev-only-change-me-in-production"
        config.DEFAULT_ADMIN_USERNAME = "admin"
        config.DEFAULT_ADMIN_PASSWORD = "admin123"

        with self.assertRaises(RuntimeError) as ctx:
            config.validate_production_config()
        message = str(ctx.exception)
        self.assertIn("JWT_SECRET", message)
        self.assertIn("DEFAULT_ADMIN", message)

    def test_production_rejects_mysql_disabled_and_placeholders(self):
        config.APP_ENV = "production"
        config.MYSQL_ENABLED = False
        config.MYSQL_PASSWORD = "change-this-app-password"
        config.JWT_SECRET = "replace-with-at-least-32-random-characters"
        config.DEFAULT_ADMIN_USERNAME = "rag_admin"
        config.DEFAULT_ADMIN_PASSWORD = "change-this-admin-password"

        with self.assertRaises(RuntimeError) as ctx:
            config.validate_production_config()
        message = str(ctx.exception)
        self.assertIn("MYSQL_ENABLED", message)
        self.assertIn("MYSQL_PASSWORD", message)
        self.assertIn("JWT_SECRET", message)
        self.assertIn("DEFAULT_ADMIN_PASSWORD", message)

    def test_user_repo_mysql_failure_is_fatal_in_production(self):
        self._valid_production_config()
        user_service.MYSQL_ENABLED = True

        class BrokenRepo:
            def __init__(self):
                raise RuntimeError("mysql timeout")

        user_service.MySQLUserRepo = BrokenRepo

        with self.assertRaises(RuntimeError) as ctx:
            user_service._build_repo()
        self.assertIn("不可降级", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
