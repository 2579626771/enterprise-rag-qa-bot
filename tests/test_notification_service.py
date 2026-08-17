import unittest
import logging

from app.services import notification_service


ADMIN = 1
UA = 2
UB = 3
UC = 4


class TestNotificationService(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        notification_service._set_repo_for_test(notification_service.InMemoryNotificationRepo())

    def tearDown(self):
        notification_service._reset_repo_for_test()
        logging.disable(logging.NOTSET)

    def test_create_notification_for_all_users(self):
        result = notification_service.create_notification(
            ADMIN,
            "系统维护",
            "今晚 8 点维护",
            [UA, UB, UC],
            notification_service.TARGET_ALL,
        )
        self.assertEqual(result["recipient_count"], 3)
        self.assertEqual(result["unread_count"], 3)
        self.assertEqual(len(notification_service.list_for_user(UA)), 1)
        self.assertEqual(len(notification_service.list_for_user(UB)), 1)

    def test_create_notification_dedupes_recipients(self):
        result = notification_service.create_notification(
            ADMIN,
            "指定通知",
            "请查看",
            [UA, UA, UB],
            notification_service.TARGET_USERS,
        )
        self.assertEqual(result["recipient_count"], 2)
        self.assertEqual(notification_service.count_unread(UA), 1)

    def test_reject_invalid_payload(self):
        with self.assertRaises(ValueError):
            notification_service.create_notification(ADMIN, "  ", "内容", [UA])
        with self.assertRaises(ValueError):
            notification_service.create_notification(ADMIN, "标题", "x" * 4001, [UA])
        with self.assertRaises(ValueError):
            notification_service.create_notification(ADMIN, "标题", "内容", [])
        with self.assertRaises(ValueError):
            notification_service.create_notification(ADMIN, "标题", "内容", [UA], "bad")

    def test_user_list_isolated(self):
        notification_service.create_notification(ADMIN, "A", "", [UA])
        notification_service.create_notification(ADMIN, "B", "", [UB])
        self.assertEqual([n["title"] for n in notification_service.list_for_user(UA)], ["A"])
        self.assertEqual([n["title"] for n in notification_service.list_for_user(UB)], ["B"])

    def test_mark_read_only_affects_current_user(self):
        n = notification_service.create_notification(ADMIN, "通知", "", [UA, UB])
        read = notification_service.mark_read(n["id"], UA)
        self.assertEqual(read["status"], notification_service.STATUS_READ)
        self.assertEqual(notification_service.count_unread(UA), 0)
        self.assertEqual(notification_service.count_unread(UB), 1)

    def test_close_hidden_by_default_but_included_when_requested(self):
        n = notification_service.create_notification(ADMIN, "通知", "", [UA])
        closed = notification_service.close(n["id"], UA)
        self.assertEqual(closed["status"], notification_service.STATUS_CLOSED)
        self.assertEqual(notification_service.list_for_user(UA), [])
        self.assertEqual(len(notification_service.list_for_user(UA, include_closed=True)), 1)

    def test_admin_stats(self):
        n = notification_service.create_notification(ADMIN, "通知", "", [UA, UB, UC])
        notification_service.mark_read(n["id"], UA)
        notification_service.close(n["id"], UB)
        stats = notification_service.list_admin()[0]
        self.assertEqual(stats["recipient_count"], 3)
        self.assertEqual(stats["unread_count"], 1)
        self.assertEqual(stats["read_count"], 1)
        self.assertEqual(stats["closed_count"], 1)


if __name__ == "__main__":
    unittest.main()
