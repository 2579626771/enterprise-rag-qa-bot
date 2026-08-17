"""hybrid_search_service 单元测试（BM25+jieba 混合检索）。"""

import unittest

from app.services import hybrid_search_service


class TestHybridSearchService(unittest.TestCase):
    def test_tokenize_keeps_english_terms(self):
        tokens = hybrid_search_service.tokenize("示例系统 支持 webhook 和 csv api")
        self.assertIn("webhook", tokens)
        self.assertIn("csv", tokens)
        self.assertIn("api", tokens)

    def test_bm25_rank_prefers_keyword_match(self):
        docs = [
            {"filename": "a.txt", "chunk_index": 0, "content": "普通终端安全说明"},
            {"filename": "b.txt", "chunk_index": 1, "content": "示例系统 支持 webhook csv api 对接"},
        ]
        ranked = hybrid_search_service.bm25_rank("webhook csv api", docs, top_k=2)
        self.assertGreaterEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["filename"], "b.txt")
        self.assertGreater(ranked[0]["bm25_score"], 0)

    def test_rrf_merge_deduplicates_and_keeps_distance(self):
        vector = [
            {"filename": "a.txt", "chunk_index": 0, "content": "向量第一", "distance": 0.1},
            {"filename": "b.txt", "chunk_index": 1, "content": "向量第二", "distance": 0.2},
        ]
        bm25 = [
            {"filename": "b.txt", "chunk_index": 1, "content": "向量第二", "bm25_score": 3.0},
            {"filename": "c.txt", "chunk_index": 2, "content": "关键词新增", "bm25_score": 2.0},
        ]
        merged = hybrid_search_service.rrf_merge(vector, bm25, rrf_k=60)
        keys = [(x["filename"], x["chunk_index"]) for x in merged]
        self.assertEqual(len(keys), len(set(keys)))
        by_key = {(x["filename"], x["chunk_index"]): x for x in merged}
        self.assertEqual(by_key[("b.txt", 1)]["distance"], 0.2)
        self.assertEqual(by_key[("c.txt", 2)]["distance"], 0.5)
        self.assertIn("rrf_score", merged[0])

    def test_empty_inputs_return_empty(self):
        self.assertEqual(hybrid_search_service.bm25_rank("", [], top_k=5), [])
        self.assertEqual(hybrid_search_service.hybrid_rank("q", [], [], bm25_top_k=5), [])


if __name__ == "__main__":
    unittest.main()
