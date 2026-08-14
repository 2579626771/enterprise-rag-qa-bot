"""rerank_service 单元测试（检索质量专线·阶段3）。

覆盖三件事，全部走 fake / 打桩，零网络零付费：
1. fake provider 的确定性排序（按与 query 的字符重叠度降序）。
2. top_n 截断正确。
3. 失败降级：真实 provider 内部异常时，返回「保持原顺序」而非抛出。
"""

import unittest
import logging

import app.services.rerank_service as rerank_service


class TestRerankService(unittest.TestCase):
    def setUp(self):
        self._orig_provider = rerank_service.RERANK_PROVIDER
        logging.disable(logging.CRITICAL)

    def tearDown(self):
        rerank_service.RERANK_PROVIDER = self._orig_provider
        logging.disable(logging.NOTSET)

    def test_fake_orders_by_char_overlap(self):
        # fake：与 query 字符重叠越多越靠前。
        rerank_service.RERANK_PROVIDER = "fake"
        query = "多租户隔离"
        docs = [
            "今天天气很好和风和日丽",          # 与 query 几乎无重叠
            "多租户隔离通过 kb_id 过滤实现",   # 与 query 高度重叠
            "隔离是一种手段",                  # 部分重叠
        ]
        order = rerank_service.rerank(query, docs, top_n=3)
        # 返回结构：[{index, relevance_score}]，index 指向原 docs 下标。
        self.assertEqual(len(order), 3)
        self.assertIn("index", order[0])
        self.assertIn("relevance_score", order[0])
        # 最相关的应是 index=1（重叠最多），最不相关的 index=0 排最后。
        self.assertEqual(order[0]["index"], 1)
        self.assertEqual(order[-1]["index"], 0)
        # 分数应降序。
        scores = [o["relevance_score"] for o in order]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_top_n_truncates(self):
        rerank_service.RERANK_PROVIDER = "fake"
        docs = ["aaa", "bbb", "ccc", "ddd"]
        order = rerank_service.rerank("abc", docs, top_n=2)
        self.assertEqual(len(order), 2)

    def test_empty_documents_returns_empty(self):
        rerank_service.RERANK_PROVIDER = "fake"
        self.assertEqual(rerank_service.rerank("q", [], top_n=5), [])

    def test_top_n_larger_than_docs_is_clamped(self):
        rerank_service.RERANK_PROVIDER = "fake"
        order = rerank_service.rerank("abc", ["abc", "xyz"], top_n=10)
        self.assertEqual(len(order), 2)

    def test_failure_degrades_to_original_order(self):
        # 真实 provider 内部抛错时，应降级为「保持原顺序」而非抛出。
        rerank_service.RERANK_PROVIDER = "aliyun"

        def _boom(query, documents, top_n):
            raise RuntimeError("模拟网络故障")

        orig = rerank_service._aliyun_rerank
        rerank_service._aliyun_rerank = _boom
        try:
            docs = ["d0", "d1", "d2"]
            order = rerank_service.rerank("q", docs, top_n=3)
        finally:
            rerank_service._aliyun_rerank = orig

        # 降级：原顺序 0,1,2，分数置 0。
        self.assertEqual([o["index"] for o in order], [0, 1, 2])
        self.assertTrue(all(o["relevance_score"] == 0.0 for o in order))

    def test_unknown_provider_degrades(self):
        # 未知 provider 也走降级（不抛出），保证检索主流程稳。
        rerank_service.RERANK_PROVIDER = "nope"
        order = rerank_service.rerank("q", ["a", "b"], top_n=2)
        self.assertEqual([o["index"] for o in order], [0, 1])


if __name__ == "__main__":
    unittest.main()
