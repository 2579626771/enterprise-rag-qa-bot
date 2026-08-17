import unittest
import logging

from app.services import feedback_service


UA = 1
UB = 2
ADMIN = 99


class TestFeedbackService(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        feedback_service._set_repo_for_test(feedback_service.InMemoryFeedbackRepo())

    def tearDown(self):
        feedback_service._reset_repo_for_test()
        logging.disable(logging.NOTSET)

    def test_create_and_list_by_user(self):
        ticket = feedback_service.create_ticket(UA, "页面无法上传", "上传 PDF 失败")
        self.assertEqual(ticket["status"], feedback_service.STATUS_PENDING)
        self.assertEqual(ticket["title"], "页面无法上传")
        self.assertEqual(len(feedback_service.list_by_user(UA)), 1)
        self.assertEqual(feedback_service.list_by_user(UB), [])

    def test_title_required_and_limited(self):
        with self.assertRaises(ValueError):
            feedback_service.create_ticket(UA, "   ", "内容")
        with self.assertRaises(ValueError):
            feedback_service.create_ticket(UA, "x" * 121, "内容")

    def test_content_limited(self):
        with self.assertRaises(ValueError):
            feedback_service.create_ticket(UA, "标题", "x" * 4001)

    def test_admin_update_processing(self):
        ticket = feedback_service.create_ticket(UA, "问答慢", "研判等待时间较长")
        updated = feedback_service.admin_update(
            ticket["id"], feedback_service.STATUS_PROCESSING, "已收到，排查中", ADMIN
        )
        self.assertEqual(updated["status"], feedback_service.STATUS_PROCESSING)
        self.assertEqual(updated["admin_reply"], "已收到，排查中")

    def test_admin_resolve_requires_reply(self):
        ticket = feedback_service.create_ticket(UA, "问答不准", "来源不匹配")
        with self.assertRaises(ValueError):
            feedback_service.admin_update(ticket["id"], feedback_service.STATUS_RESOLVED, " ", ADMIN)

    def test_admin_resolve_sets_reply_and_resolver(self):
        ticket = feedback_service.create_ticket(UA, "问答不准", "来源不匹配")
        updated = feedback_service.admin_update(
            ticket["id"], feedback_service.STATUS_RESOLVED, "已更新文档，请重试", ADMIN
        )
        self.assertEqual(updated["status"], feedback_service.STATUS_RESOLVED)
        self.assertEqual(updated["resolved_by"], ADMIN)
        self.assertEqual(updated["admin_reply"], "已更新文档，请重试")
        self.assertNotEqual(updated["resolved_at"], "—")

    def test_invalid_status_rejected(self):
        ticket = feedback_service.create_ticket(UA, "标题", "内容")
        with self.assertRaises(ValueError):
            feedback_service.admin_update(ticket["id"], "bad", "回复", ADMIN)
        with self.assertRaises(ValueError):
            feedback_service.list_all("bad")

    def test_list_all_can_filter_status(self):
        a = feedback_service.create_ticket(UA, "A", "")
        feedback_service.create_ticket(UB, "B", "")
        feedback_service.admin_update(a["id"], feedback_service.STATUS_PROCESSING, "处理中", ADMIN)
        pending = feedback_service.list_all(feedback_service.STATUS_PENDING)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["title"], "B")

    def test_owner_can_close_own_ticket_only(self):
        ticket = feedback_service.create_ticket(UA, "标题", "内容")
        self.assertIsNone(feedback_service.close_ticket(ticket["id"], UB))
        closed = feedback_service.close_ticket(ticket["id"], UA)
        self.assertEqual(closed["status"], feedback_service.STATUS_CLOSED)

    def test_add_attachment_and_public_ticket_contains_metadata(self):
        ticket = feedback_service.create_ticket(UA, "截图问题", "见截图")
        attachment = feedback_service.add_attachment(
            ticket["id"], "页面报错.png", "abc.png", "image/png", 12
        )
        self.assertEqual(attachment["filename"], "页面报错.png")
        self.assertNotIn("stored_name", attachment)
        mine = feedback_service.list_by_user(UA)[0]
        self.assertEqual(len(mine["attachments"]), 1)
        self.assertEqual(mine["attachments"][0]["content_type"], "image/png")
        raw = feedback_service.get_attachment_record(attachment["id"])
        self.assertEqual(raw["stored_name"], "abc.png")


if __name__ == "__main__":
    unittest.main()
