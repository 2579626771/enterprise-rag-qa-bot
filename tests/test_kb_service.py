import unittest
import logging

from app.services import user_service, kb_service, topic_service


class TestKbService(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        user_service._set_repo_for_test(user_service.InMemoryUserRepo())
        kb_service._set_repo_for_test(kb_service.InMemoryKbRepo())
        # 建库会种入默认分类，用内存分类仓库隔离，避免触碰真实 MySQL
        topic_service._set_repo_for_test(topic_service.InMemoryTopicRepo())
        # 普通用户默认配额 3
        self.user = user_service.create_user("alice", "a123", role="user")

    def tearDown(self):
        user_service._reset_repo_for_test()
        kb_service._reset_repo_for_test()
        topic_service._reset_repo_for_test()
        logging.disable(logging.NOTSET)

    def test_create_and_list(self):
        kb = kb_service.create_kb(self.user["id"], "库1", "描述")
        self.assertEqual(kb["name"], "库1")
        self.assertEqual(kb["owner_id"], self.user["id"])
        kbs = kb_service.list_by_owner(self.user["id"])
        self.assertEqual(len(kbs), 1)

    def test_create_kb_seeds_default_topics(self):
        kb = kb_service.create_kb(self.user["id"], "库1", "描述")
        topics = topic_service.list_topics(kb["id"])
        self.assertEqual(len(topics), len(topic_service.DEFAULT_TOPICS))
        self.assertIn("技术文档", [t["name"] for t in topics])

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

    def test_update_kb(self):
        kb = kb_service.create_kb(self.user["id"], "旧名", "旧描述")
        updated = kb_service.update_kb(kb["id"], "新名", "新描述")
        self.assertEqual(updated["name"], "新名")
        self.assertEqual(updated["description"], "新描述")
        # 再取一次确认已持久化
        again = kb_service.get(kb["id"])
        self.assertEqual(again["name"], "新名")
        self.assertEqual(again["description"], "新描述")

    def test_update_kb_empty_name_rejected(self):
        kb = kb_service.create_kb(self.user["id"], "库1")
        with self.assertRaises(ValueError):
            kb_service.update_kb(kb["id"], "   ")

    def test_update_kb_missing_returns_none(self):
        self.assertIsNone(kb_service.update_kb(9999, "x"))

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
