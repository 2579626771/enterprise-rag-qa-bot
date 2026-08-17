import unittest
import logging
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import app
from app.services import user_service, kb_service, quota_service, feedback_service


class TestFeedbackApi(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        user_service._set_repo_for_test(user_service.InMemoryUserRepo())
        kb_service._set_repo_for_test(kb_service.InMemoryKbRepo())
        quota_service._set_repo_for_test(quota_service.InMemoryQuotaRepo())
        feedback_service._set_repo_for_test(feedback_service.InMemoryFeedbackRepo())
        self.attachment_dir = Path(tempfile.mkdtemp(prefix="feedback_attachments_test_"))
        self.dir_patch = patch("app.api.FEEDBACK_ATTACHMENT_DIR", str(self.attachment_dir))
        self.dir_patch.start()

        self.admin = user_service.create_user("admin", "admin123", role="admin")
        self.alice = user_service.create_user("alice", "alice123", role="user")
        self.bob = user_service.create_user("bob", "bob12345", role="user")
        self.client = TestClient(app)
        self.admin_header = self._auth_header("admin", "admin123")
        self.alice_header = self._auth_header("alice", "alice123")
        self.bob_header = self._auth_header("bob", "bob12345")

    def tearDown(self):
        self.dir_patch.stop()
        shutil.rmtree(self.attachment_dir, ignore_errors=True)
        feedback_service._reset_repo_for_test()
        user_service._reset_repo_for_test()
        kb_service._reset_repo_for_test()
        quota_service._reset_repo_for_test()
        logging.disable(logging.NOTSET)

    def _login(self, username, password):
        return self.client.post("/auth/login", json={"username": username, "password": password})

    def _auth_header(self, username, password):
        token = self._login(username, password).json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    def test_feedback_requires_login(self):
        self.assertEqual(self.client.get("/feedback/mine").status_code, 401)
        self.assertEqual(self.client.post("/feedback", json={"title": "x"}).status_code, 401)

    def test_user_create_and_list_own_feedback(self):
        resp = self.client.post(
            "/feedback",
            json={"title": "上传失败", "content": "PDF 上传后一直处理中"},
            headers=self.alice_header,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], feedback_service.STATUS_PENDING)

        listed = self.client.get("/feedback/mine", headers=self.alice_header)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()["tickets"]), 1)
        self.assertEqual(listed.json()["tickets"][0]["title"], "上传失败")

        bob_listed = self.client.get("/feedback/mine", headers=self.bob_header)
        self.assertEqual(bob_listed.status_code, 200)
        self.assertEqual(bob_listed.json()["tickets"], [])

    def test_normal_user_forbidden_on_admin_feedback(self):
        resp = self.client.get("/feedback/admin", headers=self.alice_header)
        self.assertEqual(resp.status_code, 403)
        resp = self.client.patch(
            "/feedback/admin/1",
            json={"status": "resolved", "reply": "已处理"},
            headers=self.alice_header,
        )
        self.assertEqual(resp.status_code, 403)

    def test_admin_can_list_and_resolve_feedback(self):
        created = self.client.post(
            "/feedback",
            json={"title": "答案不准确", "content": "来源片段不对"},
            headers=self.alice_header,
        ).json()

        listed = self.client.get("/feedback/admin", headers=self.admin_header)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()["tickets"]), 1)

        resolved = self.client.patch(
            f"/feedback/admin/{created['id']}",
            json={"status": "resolved", "reply": "已修正文档，请重新提问"},
            headers=self.admin_header,
        )
        self.assertEqual(resolved.status_code, 200)
        self.assertEqual(resolved.json()["status"], feedback_service.STATUS_RESOLVED)
        self.assertEqual(resolved.json()["admin_reply"], "已修正文档，请重新提问")

        mine = self.client.get("/feedback/mine", headers=self.alice_header).json()["tickets"]
        self.assertEqual(mine[0]["status"], feedback_service.STATUS_RESOLVED)
        self.assertEqual(mine[0]["admin_reply"], "已修正文档，请重新提问")

    def test_resolved_feedback_requires_reply(self):
        created = self.client.post(
            "/feedback",
            json={"title": "问题", "content": "内容"},
            headers=self.alice_header,
        ).json()
        resp = self.client.patch(
            f"/feedback/admin/{created['id']}",
            json={"status": "resolved", "reply": " "},
            headers=self.admin_header,
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("回复", resp.json()["detail"])

    def test_user_can_close_own_resolved_feedback(self):
        created = self.client.post(
            "/feedback",
            json={"title": "问题", "content": "内容"},
            headers=self.alice_header,
        ).json()
        self.client.patch(
            f"/feedback/admin/{created['id']}",
            json={"status": "resolved", "reply": "已解决"},
            headers=self.admin_header,
        )
        closed = self.client.post(f"/feedback/{created['id']}/close", headers=self.alice_header)
        self.assertEqual(closed.status_code, 200)
        self.assertEqual(closed.json()["status"], feedback_service.STATUS_CLOSED)

    def test_user_cannot_close_others_feedback(self):
        created = self.client.post(
            "/feedback",
            json={"title": "Alice 的问题", "content": "内容"},
            headers=self.alice_header,
        ).json()
        resp = self.client.post(f"/feedback/{created['id']}/close", headers=self.bob_header)
        self.assertEqual(resp.status_code, 404)

    def test_admin_filter_feedback_by_status(self):
        a = self.client.post("/feedback", json={"title": "A"}, headers=self.alice_header).json()
        self.client.post("/feedback", json={"title": "B"}, headers=self.bob_header)
        self.client.patch(
            f"/feedback/admin/{a['id']}",
            json={"status": "processing", "reply": "处理中"},
            headers=self.admin_header,
        )
        pending = self.client.get(
            "/feedback/admin", params={"status": "pending"}, headers=self.admin_header
        )
        self.assertEqual(pending.status_code, 200)
        self.assertEqual(len(pending.json()["tickets"]), 1)
        self.assertEqual(pending.json()["tickets"][0]["title"], "B")

    def _create_alice_feedback(self):
        return self.client.post(
            "/feedback",
            json={"title": "截图问题", "content": "见截图"},
            headers=self.alice_header,
        ).json()

    def _upload_png(self, ticket_id, header=None, filename="shot.png", content=b"fake-png"):
        return self.client.post(
            f"/feedback/{ticket_id}/attachments",
            files={"files": (filename, content, "image/png")},
            headers=header or self.alice_header,
        )

    def test_user_can_upload_and_list_screenshot(self):
        ticket = self._create_alice_feedback()
        resp = self._upload_png(ticket["id"])
        self.assertEqual(resp.status_code, 200)
        attachments = resp.json()["attachments"]
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0]["filename"], "shot.png")
        self.assertNotIn("stored_name", attachments[0])

        mine = self.client.get("/feedback/mine", headers=self.alice_header).json()["tickets"]
        self.assertEqual(len(mine[0]["attachments"]), 1)
        self.assertEqual(mine[0]["attachments"][0]["content_type"], "image/png")

    def test_user_can_upload_multiple_screenshots(self):
        ticket = self._create_alice_feedback()
        resp = self.client.post(
            f"/feedback/{ticket['id']}/attachments",
            files=[
                ("files", ("a.png", b"a", "image/png")),
                ("files", ("b.jpg", b"b", "image/jpeg")),
            ],
            headers=self.alice_header,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["attachments"]), 2)

    def test_reject_non_image_screenshot(self):
        ticket = self._create_alice_feedback()
        resp = self.client.post(
            f"/feedback/{ticket['id']}/attachments",
            files={"files": ("bad.txt", b"text", "text/plain")},
            headers=self.alice_header,
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("截图", resp.json()["detail"])

    def test_reject_too_many_screenshots(self):
        ticket = self._create_alice_feedback()
        files = [("files", (f"{i}.png", b"x", "image/png")) for i in range(6)]
        resp = self.client.post(
            f"/feedback/{ticket['id']}/attachments",
            files=files,
            headers=self.alice_header,
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("最多", resp.json()["detail"])

    def test_user_cannot_upload_to_others_feedback(self):
        ticket = self._create_alice_feedback()
        resp = self._upload_png(ticket["id"], header=self.bob_header)
        self.assertEqual(resp.status_code, 404)

    def test_owner_and_admin_can_download_screenshot(self):
        ticket = self._create_alice_feedback()
        uploaded = self._upload_png(ticket["id"], content=b"image-bytes").json()["attachments"][0]

        owner = self.client.get(
            f"/feedback/{ticket['id']}/attachments/{uploaded['id']}",
            headers=self.alice_header,
        )
        self.assertEqual(owner.status_code, 200)
        self.assertEqual(owner.content, b"image-bytes")

        admin = self.client.get(
            f"/feedback/{ticket['id']}/attachments/{uploaded['id']}",
            headers=self.admin_header,
        )
        self.assertEqual(admin.status_code, 200)
        self.assertEqual(admin.content, b"image-bytes")

    def test_user_cannot_download_others_screenshot(self):
        ticket = self._create_alice_feedback()
        uploaded = self._upload_png(ticket["id"]).json()["attachments"][0]
        resp = self.client.get(
            f"/feedback/{ticket['id']}/attachments/{uploaded['id']}",
            headers=self.bob_header,
        )
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
