import unittest
import logging

from app.services import user_service, kb_service


class TestKbService(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        user_service._set_repo_for_test(user_service.InMemoryUserRepo())
        kb_service._set_repo_for_test(kb_service.InMemoryKbRepo())
        # 普通用户默认配额 3
        self.user = user_service.create_user("alice", "a123", role="user")

    def tearDown(self):
        user_service._reset_repo_for_test()
        kb_service._reset_repo_for_test()
        logging.disable(logging.NOTSET)

    def test_create_and_list(self):
        kb = kb_service.create_kb(self.user["id"], "库1", "描述")
        self.assertEqual(kb["name"], "库1")
        self.assertEqual(kb["owner_id"], self.user["id"])
        kbs = kb_service.list_by_owner(self.user["id"])
        self.assertEqual(len(kbs), 1)

    def test_quota_enforced(self):
        for i in range(3):
            kb_service.create_kb(self.user["id"], f"库{i}")
        # 第 4 个超配额
        with self.assertRaises(kb_service.QuotaExceededError):
            kb_service.create_kb(self.user["id"], "库4")

    def test_quota_increase_allows_more(self):
        for i in range(3):
            kb_service.create_kb(self.user["id"], f"库{i}")
        user_service.increase_quota(self.user["id"], 2)
        # 现在能建到第 5 个
        kb_service.create_kb(self.user["id"], "库4")
        kb_service.create_kb(self.user["id"], "库5")
        self.assertEqual(kb_service.count_by_owner(self.user["id"]), 5)
        with self.assertRaises(kb_service.QuotaExceededError):
            kb_service.create_kb(self.user["id"], "库6")

    def test_is_owner(self):
        kb = kb_service.create_kb(self.user["id"], "库1")
        other = user_service.create_user("bob", "b123", role="user")
        self.assertTrue(kb_service.is_owner(kb["id"], self.user["id"]))
        self.assertFalse(kb_service.is_owner(kb["id"], other["id"]))

    def test_delete(self):
        kb = kb_service.create_kb(self.user["id"], "库1")
        self.assertTrue(kb_service.delete(kb["id"]))
        self.assertEqual(kb_service.count_by_owner(self.user["id"]), 0)

    def test_ensure_default_kb_idempotent(self):
        first = kb_service.ensure_default_kb(self.user["id"])
        second = kb_service.ensure_default_kb(self.user["id"])
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(kb_service.count_by_owner(self.user["id"]), 1)

    def test_admin_quota_large(self):
        admin = user_service.create_user("root", "r123", role="admin")
        # 管理员配额很大，建很多也不拦
        for i in range(10):
            kb_service.create_kb(admin["id"], f"kb{i}")
        self.assertEqual(kb_service.count_by_owner(admin["id"]), 10)

    def test_admin_unlimited_even_with_low_quota(self):
        # 即使 admin 的 kb_quota 被设成很小（例如老账号迁移后被补成 3），
        # 也应不受配额限制（基于角色判断）。
        admin = user_service.create_user("root2", "r123", role="admin")
        user_service._get_repo().update_quota(admin["id"], 1)  # 强行把配额压到 1
        for i in range(5):
            kb_service.create_kb(admin["id"], f"akb{i}")
        self.assertEqual(kb_service.count_by_owner(admin["id"]), 5)


if __name__ == "__main__":
    unittest.main()
