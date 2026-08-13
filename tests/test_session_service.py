import unittest

from app.services.session_service import InMemorySessionRepo

UA = 1  # 用户 A
UB = 2  # 用户 B


class TestInMemorySessionRepo(unittest.TestCase):
    """会话仓库的行为测试。用内存实现，不依赖真实 MySQL。
    所有操作都带 user_id，严格按用户归属隔离。"""

    def setUp(self):
        self.repo = InMemorySessionRepo()

    # ---- 会话增删改查 ----
    def test_create_and_list(self):
        s = self.repo.create_session(UA, "会话1")
        self.assertEqual(s["title"], "会话1")
        self.assertFalse(s["is_favorite"])
        listed = self.repo.list_sessions(UA)
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["id"], s["id"])

    def test_create_default_title(self):
        s = self.repo.create_session(UA)
        self.assertEqual(s["title"], "未命名会话")

    def test_rename(self):
        s = self.repo.create_session(UA, "旧名")
        updated = self.repo.rename_session(s["id"], UA, "新名")
        self.assertIsNotNone(updated)
        self.assertEqual(updated["title"], "新名")

    def test_rename_empty_title_rejected(self):
        s = self.repo.create_session(UA, "旧名")
        self.assertIsNone(self.repo.rename_session(s["id"], UA, "   "))

    def test_toggle_favorite(self):
        s = self.repo.create_session(UA)
        self.assertTrue(self.repo.toggle_favorite(s["id"], UA)["is_favorite"])
        self.assertFalse(self.repo.toggle_favorite(s["id"], UA)["is_favorite"])

    def test_delete(self):
        s = self.repo.create_session(UA)
        self.assertTrue(self.repo.delete_session(s["id"], UA))
        self.assertFalse(self.repo.delete_session(s["id"], UA))
        self.assertEqual(self.repo.list_sessions(UA), [])

    # ---- 消息 ----
    def test_append_and_list_messages(self):
        s = self.repo.create_session(UA)
        self.repo.append_message(s["id"], UA, "user", "你好")
        self.repo.append_message(s["id"], UA, "assistant", "在的", sources=[{"filename": "a.txt", "chunk_index": 1, "content": "x"}])
        msgs = self.repo.list_messages(s["id"], UA)
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["role"], "user")
        self.assertEqual(msgs[1]["role"], "assistant")
        self.assertEqual(msgs[1]["sources"][0]["filename"], "a.txt")

    def test_first_user_message_updates_default_title(self):
        s = self.repo.create_session(UA)  # 默认标题
        self.repo.append_message(s["id"], UA, "user", "如何配置数据库连接参数以及更多细节")
        listed = self.repo.list_sessions(UA)
        self.assertTrue(listed[0]["title"].startswith("如何配置数据库连接参数"))
        self.assertNotEqual(listed[0]["title"], "未命名会话")

    def test_named_session_title_not_overwritten(self):
        s = self.repo.create_session(UA, "我的会话")
        self.repo.append_message(s["id"], UA, "user", "问题内容")
        listed = self.repo.list_sessions(UA)
        self.assertEqual(listed[0]["title"], "我的会话")

    def test_empty_sources_serialized(self):
        s = self.repo.create_session(UA)
        m = self.repo.append_message(s["id"], UA, "user", "hi")
        self.assertEqual(m["sources"], [])

    # ---- 归属隔离：用户 B 不能访问用户 A 的会话 ----
    def test_list_isolated_by_user(self):
        self.repo.create_session(UA, "A的会话")
        self.repo.create_session(UB, "B的会话")
        self.assertEqual(len(self.repo.list_sessions(UA)), 1)
        self.assertEqual(self.repo.list_sessions(UA)[0]["title"], "A的会话")
        self.assertEqual(self.repo.list_sessions(UB)[0]["title"], "B的会话")

    def test_cannot_rename_others_session(self):
        s = self.repo.create_session(UA)
        self.assertIsNone(self.repo.rename_session(s["id"], UB, "篡改"))

    def test_cannot_toggle_others_session(self):
        s = self.repo.create_session(UA)
        self.assertIsNone(self.repo.toggle_favorite(s["id"], UB))

    def test_cannot_delete_others_session(self):
        s = self.repo.create_session(UA)
        self.assertFalse(self.repo.delete_session(s["id"], UB))
        # 未被删除
        self.assertEqual(len(self.repo.list_sessions(UA)), 1)

    def test_cannot_read_others_messages(self):
        s = self.repo.create_session(UA)
        self.repo.append_message(s["id"], UA, "user", "机密")
        self.assertIsNone(self.repo.list_messages(s["id"], UB))

    def test_cannot_append_to_others_session(self):
        s = self.repo.create_session(UA)
        self.assertIsNone(self.repo.append_message(s["id"], UB, "user", "注入"))

    def test_delete_removes_messages(self):
        s = self.repo.create_session(UA)
        self.repo.append_message(s["id"], UA, "user", "x")
        self.repo.delete_session(s["id"], UA)
        # 会话没了，消息也应查不到（会话归属校验返回 None）
        self.assertIsNone(self.repo.list_messages(s["id"], UA))


if __name__ == "__main__":
    unittest.main()
