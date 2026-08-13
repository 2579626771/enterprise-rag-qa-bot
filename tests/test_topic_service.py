import unittest

from app.services.topic_service import InMemoryTopicRepo, DEFAULT_TOPICS

KB1 = 1
KB2 = 2


class TestInMemoryTopicRepo(unittest.TestCase):
    """主题分类仓库的行为测试（按 kb_id 隔离）。用内存实现，不依赖真实 MySQL。"""

    def setUp(self):
        self.repo = InMemoryTopicRepo()

    def test_seed_defaults_per_kb(self):
        self.repo.seed_defaults(KB1)
        names = [t["name"] for t in self.repo.list_topics(KB1)]
        self.assertEqual(names, DEFAULT_TOPICS)

    def test_empty_before_seed(self):
        self.assertEqual(self.repo.list_topics(KB1), [])

    def test_seed_is_idempotent(self):
        self.repo.seed_defaults(KB1)
        self.repo.seed_defaults(KB1)  # 再种一次不应重复
        self.assertEqual(len(self.repo.list_topics(KB1)), len(DEFAULT_TOPICS))

    # ---- 跨库隔离 ----
    def test_kb_isolation_on_seed(self):
        self.repo.seed_defaults(KB1)
        self.repo.seed_defaults(KB2)
        self.assertEqual(len(self.repo.list_topics(KB1)), 8)
        self.assertEqual(len(self.repo.list_topics(KB2)), 8)

    def test_add_isolated(self):
        self.repo.seed_defaults(KB1)
        self.repo.seed_defaults(KB2)
        self.repo.add_topic(KB1, "安全合规")
        self.assertIn("安全合规", [t["name"] for t in self.repo.list_topics(KB1)])
        self.assertNotIn("安全合规", [t["name"] for t in self.repo.list_topics(KB2)])

    def test_same_name_different_kb_allowed(self):
        a = self.repo.add_topic(KB1, "专属")
        b = self.repo.add_topic(KB2, "专属")
        self.assertNotEqual(a["id"], b["id"])
        self.assertEqual(a["kb_id"], KB1)
        self.assertEqual(b["kb_id"], KB2)

    # ---- 增 ----
    def test_add_idempotent_within_kb(self):
        self.repo.seed_defaults(KB1)
        before = len(self.repo.list_topics(KB1))
        again = self.repo.add_topic(KB1, "技术文档")  # 已存在
        self.assertEqual(again["name"], "技术文档")
        self.assertEqual(len(self.repo.list_topics(KB1)), before)

    def test_add_empty_rejected(self):
        with self.assertRaises(ValueError):
            self.repo.add_topic(KB1, "   ")

    def test_add_strips_whitespace(self):
        t = self.repo.add_topic(KB1, "  运维手册  ")
        self.assertEqual(t["name"], "运维手册")

    # ---- 改 ----
    def test_rename(self):
        t = self.repo.add_topic(KB1, "旧名")
        res = self.repo.rename_topic(t["id"], "新名")
        self.assertEqual(res["old_name"], "旧名")
        self.assertEqual(res["new_name"], "新名")
        self.assertEqual(res["kb_id"], KB1)
        self.assertIn("新名", [x["name"] for x in self.repo.list_topics(KB1)])
        self.assertNotIn("旧名", [x["name"] for x in self.repo.list_topics(KB1)])

    def test_rename_missing_returns_none(self):
        self.assertIsNone(self.repo.rename_topic(99999, "x"))

    def test_rename_empty_rejected(self):
        t = self.repo.add_topic(KB1, "旧名")
        with self.assertRaises(ValueError):
            self.repo.rename_topic(t["id"], "  ")

    def test_rename_to_existing_name_rejected(self):
        self.repo.add_topic(KB1, "A")
        b = self.repo.add_topic(KB1, "B")
        with self.assertRaises(ValueError):
            self.repo.rename_topic(b["id"], "A")

    # ---- 查 / 删 ----
    def test_get_returns_kb_id(self):
        t = self.repo.add_topic(KB1, "分类")
        got = self.repo.get(t["id"])
        self.assertEqual(got["kb_id"], KB1)
        self.assertEqual(got["name"], "分类")

    def test_delete(self):
        t = self.repo.add_topic(KB1, "临时")
        self.assertTrue(self.repo.delete_topic(t["id"]))
        self.assertFalse(self.repo.delete_topic(t["id"]))
        self.assertNotIn("临时", [x["name"] for x in self.repo.list_topics(KB1)])


if __name__ == "__main__":
    unittest.main()
