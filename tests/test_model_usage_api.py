import unittest
import logging

from fastapi.testclient import TestClient

from app.api import app
from app.services import user_service, kb_service, quota_service, model_usage_service


class TestModelUsageApi(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        user_service._set_repo_for_test(user_service.InMemoryUserRepo())
        kb_service._set_repo_for_test(kb_service.InMemoryKbRepo())
        quota_service._set_repo_for_test(quota_service.InMemoryQuotaRepo())
        model_usage_service._set_repo_for_test(model_usage_service.InMemoryModelUsageRepo())

        self.admin = user_service.create_user("admin", "admin123", role="admin", display_name="管理员")
        self.alice = user_service.create_user("alice", "alice123", role="user", display_name="Alice")
        self.client = TestClient(app)
        self.admin_header = self._auth_header("admin", "admin123")
        self.alice_header = self._auth_header("alice", "alice123")

    def tearDown(self):
        model_usage_service._reset_repo_for_test()
        user_service._reset_repo_for_test()
        kb_service._reset_repo_for_test()
        quota_service._reset_repo_for_test()
        logging.disable(logging.NOTSET)

    def _auth_header(self, username, password):
        token = self.client.post("/auth/login", json={"username": username, "password": password}).json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    def test_admin_required(self):
        self.assertEqual(self.client.get("/admin/model-usage/summary").status_code, 401)
        self.assertEqual(self.client.get("/admin/model-usage/summary", headers=self.alice_header).status_code, 403)

    def test_summary_records_and_alerts(self):
        model_usage_service.record_call(
            model_usage_service.MODEL_CHAT,
            "deepseek",
            "deepseek-test",
            "answer",
            True,
            latency_ms=100,
            prompt_tokens=10,
            completion_tokens=5,
            user_id=self.alice["id"],
        )
        summary = self.client.get("/admin/model-usage/summary", headers=self.admin_header)
        self.assertEqual(summary.status_code, 200)
        body = summary.json()
        self.assertEqual(body["overall"]["call_count"], 1)
        self.assertEqual(body["by_user"][0]["username"], "alice")
        self.assertEqual(body["by_user"][0]["display_name"], "Alice")

        records = self.client.get("/admin/model-usage/records", headers=self.admin_header)
        self.assertEqual(records.status_code, 200)
        self.assertEqual(len(records.json()["records"]), 1)
        self.assertEqual(records.json()["records"][0]["username"], "alice")

        alerts = self.client.get("/admin/model-usage/alerts", headers=self.admin_header)
        self.assertEqual(alerts.status_code, 200)
        self.assertIn("alerts", alerts.json())

    def test_invalid_model_type_rejected(self):
        resp = self.client.get(
            "/admin/model-usage/summary",
            params={"model_type": "bad"},
            headers=self.admin_header,
        )
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
