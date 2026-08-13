import unittest

from app.services.metadata_service import InMemoryMetadataRepo

KB = 1  # 测试用知识库 id


class TestInMemoryMetadataRepo(unittest.TestCase):
    """元数据仓库的行为测试。用内存实现，不依赖真实 MySQL。
    多知识库隔离后，所有操作都带 kb_id，主键为 (kb_id, filename)。"""

    def setUp(self):
        self.repo = InMemoryMetadataRepo()

    def test_upsert_creates_record(self):
        result = self.repo.upsert(
            KB, "a.txt", topic="技术文档", description="desc", chunk_count=3
        )
        self.assertEqual(result["filename"], "a.txt")
        self.assertEqual(result["kb_id"], KB)
        self.assertEqual(result["topic"], "技术文档")
        self.assertEqual(result["description"], "desc")
        self.assertEqual(result["chunk_count"], 3)
        self.assertEqual(result["status"], "就绪")
        self.assertNotEqual(result["uploaded_at"], "—")

    def test_partial_update_preserves_existing_fields(self):
        self.repo.upsert(KB, "a.txt", topic="技术文档", description="原始描述", chunk_count=3)
        updated = self.repo.upsert(KB, "a.txt", chunk_count=9)
        self.assertEqual(updated["chunk_count"], 9)
        self.assertEqual(updated["topic"], "技术文档")
        self.assertEqual(updated["description"], "原始描述")

    def test_uploaded_at_not_overwritten_on_update(self):
        first = self.repo.upsert(KB, "a.txt", topic="技术文档")
        again = self.repo.upsert(KB, "a.txt", chunk_count=5)
        self.assertEqual(first["uploaded_at"], again["uploaded_at"])

    def test_get_missing_returns_none(self):
        self.assertIsNone(self.repo.get(KB, "nope.txt"))

    def test_list_all_maps_by_filename(self):
        self.repo.upsert(KB, "a.txt", topic="技术文档")
        self.repo.upsert(KB, "b.txt", topic="产品手册")
        listed = self.repo.list_all(KB)
        self.assertEqual(set(listed.keys()), {"a.txt", "b.txt"})
        self.assertEqual(listed["b.txt"]["topic"], "产品手册")

    def test_delete_returns_true_then_false(self):
        self.repo.upsert(KB, "a.txt")
        self.assertTrue(self.repo.delete(KB, "a.txt"))
        self.assertFalse(self.repo.delete(KB, "a.txt"))
        self.assertIsNone(self.repo.get(KB, "a.txt"))

    def test_defaults_when_no_optional_fields(self):
        result = self.repo.upsert(KB, "bare.txt")
        self.assertEqual(result["topic"], "未分类")
        self.assertEqual(result["description"], "")
        self.assertEqual(result["status"], "就绪")
        self.assertEqual(result["chunk_count"], 0)

    # ---- 多知识库隔离行为 ----
    def test_same_filename_different_kb_not_overwrite(self):
        self.repo.upsert(1, "a.txt", topic="技术文档")
        self.repo.upsert(2, "a.txt", topic="产品手册")
        self.assertEqual(self.repo.get(1, "a.txt")["topic"], "技术文档")
        self.assertEqual(self.repo.get(2, "a.txt")["topic"], "产品手册")

    def test_list_all_filters_by_kb(self):
        self.repo.upsert(1, "a.txt")
        self.repo.upsert(2, "b.txt")
        self.assertEqual(set(self.repo.list_all(1).keys()), {"a.txt"})
        self.assertEqual(set(self.repo.list_all(2).keys()), {"b.txt"})

    def test_delete_by_kb(self):
        self.repo.upsert(1, "a.txt")
        self.repo.upsert(1, "b.txt")
        self.repo.upsert(2, "c.txt")
        removed = self.repo.delete_by_kb(1)
        self.assertEqual(removed, 2)
        self.assertEqual(self.repo.list_all(1), {})
        self.assertEqual(set(self.repo.list_all(2).keys()), {"c.txt"})


if __name__ == "__main__":
    unittest.main()
