import unittest
import logging

from fastapi.testclient import TestClient

from app.api import app
from app.services import user_service, kb_service, quota_service, notification_service


class TestNotificationApi(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        user_service._set_repo_for_test(user_service.InMemoryUserRepo())
        kb_service._set_repo_for_test(kb_service.InMemoryKbRepo())
        quota_service._set_repo_for_test(quota_service.InMemoryQuotaRepo())
        notification_service._set_repo_for_test(notification_service.InMemoryNotificationRepo())

        self.admin = user_service.create_user("admin", "admin123", role="admin")
        self.alice = user_service.create_user("alice", "alice123", role="user")
        self.bob = user_service.create_user("bob", "bob12345", role="user")
        self.client = TestClient(app)
        self.admin_header = self._auth_header("admin", "admin123")
        self.alice_header = self._auth_header("alice", "alice123")
        self.bob_header = self._auth_header("bob", "bob12345")

    def tearDown(self):
        notification_service._reset_repo_for_test()
        user_service._reset_repo_for_test()
        kb_service._reset_repo_for_test()
        quota_service._reset_repo_for_test()
        logging.disable(logging.NOTSET)

    def _login(self, username, password):
        return self.client.post("/auth/login", json={"username": username, "password": password})

    def _auth_header(self, username, password):
        token = self._login(username, password).json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    def _send(self, send_to_all=True, user_ids=None, title="通知"):
        return self.client.post(
            "/notifications/admin",
            json={
                "title": title,
                "content": "请查看",
                "send_to_all": send_to_all,
                "user_ids": user_ids or [],
            },
            headers=self.admin_header,
        )

    def test_notifications_require_login(self):
        self.assertEqual(self.client.get("/notifications/mine").status_code, 401)
        self.assertEqual(self.client.get("/notifications/unread-count").status_code, 401)

    def test_normal_user_forbidden_on_admin_send(self):
        resp = self.client.post(
            "/notifications/admin",
            json={"title": "x", "send_to_all": True},
            headers=self.alice_header,
        )
        self.assertEqual(resp.status_code, 403)

    def test_admin_send_all_and_user_mark_read(self):
        sent = self._send(send_to_all=True, title="全员通知")
        self.assertEqual(sent.status_code, 200)
        # 当前实现全员包含管理员、alice、bob 三人。
        self.assertEqual(sent.json()["recipient_count"], 3)

        mine = self.client.get("/notifications/mine", headers=self.alice_header)
        self.assertEqual(mine.status_code, 200)
        self.assertEqual(len(mine.json()["notifications"]), 1)
        notification_id = mine.json()["notifications"][0]["id"]

        count = self.client.get("/notifications/unread-count", headers=self.alice_header)
        self.assertEqual(count.json()["count"], 1)

        read = self.client.post(f"/notifications/{notification_id}/read", headers=self.alice_header)
        self.assertEqual(read.status_code, 200)
        self.assertEqual(read.json()["status"], notification_service.STATUS_READ)
        count = self.client.get("/notifications/unread-count", headers=self.alice_header)
        self.assertEqual(count.json()["count"], 0)

    def test_admin_send_to_specific_users(self):
        sent = self._send(send_to_all=False, user_ids=[self.alice["id"]], title="指定通知")
        self.assertEqual(sent.status_code, 200)
        self.assertEqual(sent.json()["recipient_count"], 1)
        alice = self.client.get("/notifications/mine", headers=self.alice_header).json()["notifications"]
        bob = self.client.get("/notifications/mine", headers=self.bob_header).json()["notifications"]
        self.assertEqual(len(alice), 1)
        self.assertEqual(alice[0]["title"], "指定通知")
        self.assertEqual(bob, [])

    def test_user_cannot_read_others_notification(self):
        self._send(send_to_all=False, user_ids=[self.alice["id"]])
        n = self.client.get("/notifications/mine", headers=self.alice_header).json()["notifications"][0]
        resp = self.client.post(f"/notifications/{n['id']}/read", headers=self.bob_header)
        self.assertEqual(resp.status_code, 404)

    def test_close_hides_notification_by_default(self):
        self._send(send_to_all=False, user_ids=[self.alice["id"]])
        n = self.client.get("/notifications/mine", headers=self.alice_header).json()["notifications"][0]
        closed = self.client.post(f"/notifications/{n['id']}/close", headers=self.alice_header)
        self.assertEqual(closed.status_code, 200)
        self.assertEqual(closed.json()["status"], notification_service.STATUS_CLOSED)
        self.assertEqual(
            self.client.get("/notifications/mine", headers=self.alice_header).json()["notifications"],
            [],
        )
        included = self.client.get(
            "/notifications/mine", params={"include_closed": True}, headers=self.alice_header
        ).json()["notifications"]
        self.assertEqual(len(included), 1)

    def test_admin_history_stats(self):
        self._send(send_to_all=False, user_ids=[self.alice["id"], self.bob["id"]], title="统计通知")
        n = self.client.get("/notifications/mine", headers=self.alice_header).json()["notifications"][0]
        self.client.post(f"/notifications/{n['id']}/read", headers=self.alice_header)
        history = self.client.get("/notifications/admin", headers=self.admin_header)
        self.assertEqual(history.status_code, 200)
        item = history.json()["notifications"][0]
        self.assertEqual(item["recipient_count"], 2)
        self.assertEqual(item["read_count"], 1)
        self.assertEqual(item["unread_count"], 1)

    def test_empty_specific_target_rejected(self):
        resp = self._send(send_to_all=False, user_ids=[])
        self.assertEqual(resp.status_code, 400)
        self.assertIn("接收人", resp.json()["detail"])


if __name__ == "__main__":
    unittest.main()
