import unittest
import logging

from app.services import user_service, quota_service


class TestQuotaService(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        user_service._set_repo_for_test(user_service.InMemoryUserRepo())
        quota_service._set_repo_for_test(quota_service.InMemoryQuotaRepo())
        self.user = user_service.create_user("alice", "a123", role="user")
        self.admin = user_service.create_user("root", "r123", role="admin")

    def tearDown(self):
        user_service._reset_repo_for_test()
        quota_service._reset_repo_for_test()
        logging.disable(logging.NOTSET)

    def test_create_and_list_pending(self):
        req = quota_service.create_request(self.user["id"], 2, "业务需要")
        self.assertEqual(req["status"], "pending")
        self.assertEqual(req["amount"], 2)
        self.assertEqual(len(quota_service.list_pending()), 1)
        self.assertEqual(len(quota_service.list_by_user(self.user["id"])), 1)

    def test_amount_must_be_positive(self):
        with self.assertRaises(ValueError):
            quota_service.create_request(self.user["id"], 0, "")

    def test_approve_increases_quota(self):
        before = user_service.get_quota(self.user["id"])  # 默认 3
        req = quota_service.create_request(self.user["id"], 2, "需要")
        result = quota_service.approve(req["id"], self.admin["id"])
        self.assertEqual(result["status"], "approved")
        self.assertEqual(result["reviewed_by"], self.admin["id"])
        self.assertEqual(user_service.get_quota(self.user["id"]), before + 2)
        # 通过后不再在 pending 列表
        self.assertEqual(len(quota_service.list_pending()), 0)

    def test_reject_does_not_change_quota(self):
        before = user_service.get_quota(self.user["id"])
        req = quota_service.create_request(self.user["id"], 5, "需要")
        result = quota_service.reject(req["id"], self.admin["id"])
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(user_service.get_quota(self.user["id"]), before)

    def test_cannot_double_process(self):
        req = quota_service.create_request(self.user["id"], 1, "")
        quota_service.approve(req["id"], self.admin["id"])
        with self.assertRaises(ValueError):
            quota_service.approve(req["id"], self.admin["id"])
        with self.assertRaises(ValueError):
            quota_service.reject(req["id"], self.admin["id"])


if __name__ == "__main__":
    unittest.main()
