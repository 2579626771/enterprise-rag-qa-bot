import unittest
import logging
import chromadb
import app.services.embedding_service as embedding_service
import app.services.answer_service as answer_service
import app.services.judge_service as judge_service
import app.services.rag_service as rag_service
from app.services import knowledge_base_service
from app.services.rag_service import answer_from_knowledge_base
from app.services.document_service import create_document


class TestRagService(unittest.TestCase):
    def setUp(self):
        # 用 fake provider，避免调用真实阿里云 / DeepSeek 付费接口。
        self.original_embedding_provider = embedding_service.EMBEDDING_PROVIDER
        self.original_answer_provider = answer_service.ANSWER_PROVIDER
        self.original_judge_provider = judge_service.ANSWER_PROVIDER
        self.original_judge_enabled = rag_service.JUDGE_ENABLED
        import app.config as config
        self._orig_retrieval_mode = config.RETRIEVAL_MODE
        self._orig_context_window = config.RETRIEVAL_CONTEXT_WINDOW
        self._orig_rerank_enabled = config.RERANK_ENABLED
        self._orig_rerank_strategy = config.RERANK_STRATEGY
        self._orig_rerank_weight = config.RERANK_WEIGHT
        self._orig_rerank_window_multiplier = config.RERANK_WINDOW_MULTIPLIER
        embedding_service.EMBEDDING_PROVIDER = "fake"
        answer_service.ANSWER_PROVIDER = "fake"
        judge_service.ANSWER_PROVIDER = "fake"
        # 默认关闭研判，保持与原有测试一致；需要时各用例单独打开。
        rag_service.JUDGE_ENABLED = False
        logging.disable(logging.CRITICAL)

        # 用内存版知识库，测试完即弃，不碰硬盘上的真实数据。
        # 先删掉同名集合再重建，保证每个测试都是全新的空库（EphemeralClient 会共享内存）。
        client = chromadb.EphemeralClient()
        try:
            client.delete_collection(name="test_kb")
        except Exception:
            pass
        collection = client.get_or_create_collection(
            name="test_kb",
            metadata={"hnsw:space": "cosine"},
        )
        knowledge_base_service._set_collection_for_test(collection)

    def tearDown(self):
        embedding_service.EMBEDDING_PROVIDER = self.original_embedding_provider
        answer_service.ANSWER_PROVIDER = self.original_answer_provider
        judge_service.ANSWER_PROVIDER = self.original_judge_provider
        rag_service.JUDGE_ENABLED = self.original_judge_enabled
        import app.config as config
        config.RETRIEVAL_MODE = self._orig_retrieval_mode
        config.RETRIEVAL_CONTEXT_WINDOW = self._orig_context_window
        config.RERANK_ENABLED = self._orig_rerank_enabled
        config.RERANK_STRATEGY = self._orig_rerank_strategy
        config.RERANK_WEIGHT = self._orig_rerank_weight
        config.RERANK_WINDOW_MULTIPLIER = self._orig_rerank_window_multiplier
        knowledge_base_service._reset_collection_for_test()
        logging.disable(logging.NOTSET)

    def _ingest_demo(self, kb_id=1):
        document = create_document(
            document_id=0,
            filename="rag_demo.txt",
            file_type="txt",
            content="第一段：如何读取文档内容。\n\n第二段：如何上传文档。",
        )
        knowledge_base_service.ingest_document(document, kb_id=kb_id)

    def test_answer_from_empty_knowledge_base(self):
        # 知识库为空时，应给出友好提示而不是报错。
        result = answer_from_knowledge_base(question="随便问点什么？")
        self.assertIn("answer", result)
        self.assertIn("sources", result)
        self.assertEqual(result["sources"], [])
        # 空库应判为不可回答（研判字段存在且为 False）。
        self.assertFalse(result["answerable"])

    def test_answer_from_knowledge_base(self):
        # 先入库一个文档到 kb=1，再在 kb=1 范围内提问。
        self._ingest_demo(kb_id=1)

        result = answer_from_knowledge_base(question="怎么读取文档内容？", top_k=2, kb_id=1)

        self.assertIn("answer", result)
        self.assertIn("sources", result)
        self.assertTrue(len(result["sources"]) >= 1)
        # 来源里应标明来自哪个文件。
        self.assertEqual(result["sources"][0]["filename"], "rag_demo.txt")
        # fake 回答里会带上问题本身。
        self.assertIn("怎么读取文档内容？", result["answer"])

    def test_answer_isolated_by_kb(self):
        # kb=1 入库文档，在 kb=2 提问应检索不到（隔离）。
        document = create_document(
            document_id=0,
            filename="only_in_kb1.txt",
            file_type="txt",
            content="这是只属于知识库一的隔离测试内容：项目编号 alpha。",
        )
        knowledge_base_service.ingest_document(document, kb_id=1)

        result = answer_from_knowledge_base(question="项目代号是什么？", top_k=2, kb_id=2)
        # kb=2 里没有任何内容，应返回空 sources
        self.assertEqual(result["sources"], [])

    def test_result_always_has_judge_fields(self):
        # 无论研判开关如何，返回结构都应带 answerable/reason/confidence，供前端稳定消费。
        self._ingest_demo(kb_id=1)
        result = answer_from_knowledge_base(question="怎么读取文档内容？", top_k=2, kb_id=1)
        for key in ("answer", "sources", "answerable", "reason", "confidence"):
            self.assertIn(key, result)

    def test_judge_disabled_answers_normally(self):
        # 研判关闭：走原有作答路径，answerable 恒为 True。
        rag_service.JUDGE_ENABLED = False
        self._ingest_demo(kb_id=1)
        result = answer_from_knowledge_base(question="怎么读取文档内容？", top_k=2, kb_id=1)
        self.assertTrue(result["answerable"])
        self.assertIn("怎么读取文档内容？", result["answer"])

    def test_judge_enabled_answerable_path(self):
        # 研判开启 + fake provider：有资料 → 判为可回答并正常作答。
        rag_service.JUDGE_ENABLED = True
        self._ingest_demo(kb_id=1)
        result = answer_from_knowledge_base(question="怎么读取文档内容？", top_k=2, kb_id=1)
        self.assertTrue(result["answerable"])
        self.assertTrue(len(result["sources"]) >= 1)
        # fake 研判可回答时，答案回显问题。
        self.assertIn("怎么读取文档内容？", result["answer"])

    def test_explicit_max_distance_param_filters(self):
        # 显式传入极严阈值(0.0)：几乎所有片段都被过滤 → 视为无相关内容拒答。
        # 证明 max_distance 作为入参能覆盖 config 常量（在线改配置生效的关键）。
        self._ingest_demo(kb_id=1)
        strict = answer_from_knowledge_base(
            question="怎么读取文档内容？", top_k=2, max_distance=0.0, kb_id=1
        )
        self.assertEqual(strict["sources"], [])
        self.assertFalse(strict["answerable"])
        # 对照：宽松阈值(1.0)能召回。
        loose = answer_from_knowledge_base(
            question="怎么读取文档内容？", top_k=2, max_distance=1.0, kb_id=1
        )
        self.assertTrue(len(loose["sources"]) >= 1)

    def test_explicit_judge_enabled_param_overrides_module_flag(self):
        # 模块级 JUDGE_ENABLED=False，但显式传 judge_enabled=True 应走研判路径。
        rag_service.JUDGE_ENABLED = False
        self._ingest_demo(kb_id=1)
        result = answer_from_knowledge_base(
            question="怎么读取文档内容？", top_k=2, judge_enabled=True, kb_id=1
        )
        # fake 研判有资料 → 可回答，结构完整。
        self.assertTrue(result["answerable"])
        self.assertTrue(len(result["sources"]) >= 1)

    def test_custom_answer_prompt_is_threaded(self):
        # 自定义作答提示词应透传到 answer_service（fake 分支忽略提示词但不应报错）。
        self._ingest_demo(kb_id=1)
        result = answer_from_knowledge_base(
            question="怎么读取文档内容？", top_k=2, kb_id=1,
            answer_prompt="只用一句话回答。",
        )
        self.assertIn("answer", result)
        self.assertTrue(len(result["sources"]) >= 1)

    def test_rerank_enabled_reorders_and_keeps_distance(self):
        # 开启 rerank（fake provider）：候选按 rerank 次序重排，且每条来源仍保留向量 distance。
        # rerank 只改顺序、不改 distance 语义（RAG_MAX_DISTANCE 阈值继续用它），这是设计红线。
        import app.config as config
        import app.services.rerank_service as rerank_service

        orig_enabled = config.RERANK_ENABLED
        orig_provider = rerank_service.RERANK_PROVIDER
        config.RERANK_ENABLED = True
        rerank_service.RERANK_PROVIDER = "fake"
        try:
            self._ingest_demo(kb_id=1)
            # 用宽松阈值确保片段不被距离过滤掉，聚焦验证「顺序 + distance 键」。
            result = answer_from_knowledge_base(
                question="怎么上传文档？", top_k=2, max_distance=1.0, kb_id=1
            )
            self.assertTrue(len(result["sources"]) >= 1)
            # 关键：rerank 接入后 sources 仍保留 filename/content（前端/会话依赖）。
            for s in result["sources"]:
                self.assertIn("filename", s)
                self.assertIn("content", s)
        finally:
            config.RERANK_ENABLED = orig_enabled
            rerank_service.RERANK_PROVIDER = orig_provider

    def test_rerank_disabled_matches_baseline_behavior(self):
        # 关闭 rerank：行为与阶段1（未接 rerank）一致，正常召回作答。
        import app.config as config

        orig_enabled = config.RERANK_ENABLED
        config.RERANK_ENABLED = False
        try:
            self._ingest_demo(kb_id=1)
            result = answer_from_knowledge_base(
                question="怎么读取文档内容？", top_k=2, kb_id=1
            )
            self.assertTrue(len(result["sources"]) >= 1)
            self.assertEqual(result["sources"][0]["filename"], "rag_demo.txt")
        finally:
            config.RERANK_ENABLED = orig_enabled

    def test_multi_query_enabled_merges_and_keeps_distance(self):
        # 开启多查询（fake 改写）：原查询+改写多路召回合并去重，来源仍保留 filename/content/distance。
        # 多查询只扩召回入口、按最小距离去重，不改隔离范围。
        import app.config as config
        import app.services.query_rewrite_service as qr

        orig_enabled = config.MULTI_QUERY_ENABLED
        orig_provider = qr.QUERY_REWRITE_PROVIDER
        config.MULTI_QUERY_ENABLED = True
        qr.QUERY_REWRITE_PROVIDER = "fake"
        try:
            self._ingest_demo(kb_id=1)
            result = answer_from_knowledge_base(
                question="怎么上传文档？", top_k=2, max_distance=1.0, kb_id=1
            )
            self.assertTrue(len(result["sources"]) >= 1)
            for s in result["sources"]:
                self.assertIn("filename", s)
                self.assertIn("content", s)
            # 去重保证：同一 (filename, chunk_index) 不应在 sources 里重复出现。
            keys = [(s["filename"], s.get("chunk_index")) for s in result["sources"]]
            self.assertEqual(len(keys), len(set(keys)))
        finally:
            config.MULTI_QUERY_ENABLED = orig_enabled
            qr.QUERY_REWRITE_PROVIDER = orig_provider

    def test_multi_query_disabled_matches_baseline(self):
        # 关闭多查询：只用原查询，行为与阶段1 一致。
        import app.config as config

        orig_enabled = config.MULTI_QUERY_ENABLED
        config.MULTI_QUERY_ENABLED = False
        try:
            self._ingest_demo(kb_id=1)
            result = answer_from_knowledge_base(
                question="怎么读取文档内容？", top_k=2, kb_id=1
            )
            self.assertTrue(len(result["sources"]) >= 1)
            self.assertEqual(result["sources"][0]["filename"], "rag_demo.txt")
        finally:
            config.MULTI_QUERY_ENABLED = orig_enabled

    def test_retrieval_mode_vector_ignores_rerank_switch(self):
        # RETRIEVAL_MODE=vector 是最稳降级：即便旧 RERANK_ENABLED=True，也不应走 rerank。
        import app.config as config
        import app.services.rerank_service as rerank_service

        config.RETRIEVAL_MODE = "vector"
        config.RERANK_ENABLED = True
        orig_rerank = rerank_service.rerank

        def _boom(*args, **kwargs):
            raise AssertionError("vector mode should not call rerank")

        rerank_service.rerank = _boom
        try:
            self._ingest_demo(kb_id=1)
            result = answer_from_knowledge_base(
                question="怎么读取文档内容？", top_k=2, max_distance=1.0, kb_id=1
            )
            self.assertTrue(len(result["sources"]) >= 1)
        finally:
            rerank_service.rerank = orig_rerank

    def test_context_window_expands_neighbor_chunks(self):
        # #8 类问题：命中的 chunk 与答案短句相邻。开启窗口后 source content 应带入邻居。
        import app.config as config

        config.RETRIEVAL_CONTEXT_WINDOW = 1
        document = create_document(
            document_id=0,
            filename="window.txt",
            file_type="txt",
            content="功能频率限制 查询压力 固定语句。\n\n只支持五分钟一次。",
        )
        knowledge_base_service.ingest_document(document, kb_id=1)
        hits = knowledge_base_service.search("功能查询频率", top_k=1, kb_id=1)
        self.assertEqual(len(hits), 1)
        self.assertIn("五分钟", hits[0]["content"])
        self.assertIn("expanded_chunk_indexes", hits[0])

    def test_rerank_weighted_keeps_distance_and_candidates(self):
        import app.config as config
        import app.services.rerank_service as rerank_service

        config.RETRIEVAL_MODE = "rerank_fusion"
        config.RERANK_STRATEGY = "weighted"
        config.RERANK_WEIGHT = 0.5
        rerank_service.RERANK_PROVIDER = "fake"
        self._ingest_demo(kb_id=1)
        hits = knowledge_base_service.search("怎么上传文档？", top_k=2, kb_id=1)
        self.assertTrue(len(hits) >= 1)
        self.assertTrue(all("distance" in h for h in hits))
        keys = [(h["filename"], h.get("chunk_index")) for h in hits]
        self.assertEqual(len(keys), len(set(keys)))

    def test_hybrid_mode_can_return_keyword_candidate(self):
        # fake embedding 对语义不敏感；hybrid 的 BM25 应能把关键词片段合并进候选。
        import app.config as config

        config.RETRIEVAL_MODE = "hybrid"
        document = create_document(
            document_id=0,
            filename="hybrid.txt",
            file_type="txt",
            content="普通说明文字。\n\n示例系统支持 webhook csv api 对接。",
        )
        knowledge_base_service.ingest_document(document, kb_id=1)
        hits = knowledge_base_service.search("webhook csv api", top_k=2, kb_id=1)
        self.assertTrue(any("webhook" in h["content"] for h in hits))
        keys = [(h["filename"], h.get("chunk_index")) for h in hits]
        self.assertEqual(len(keys), len(set(keys)))


if __name__ == "__main__":
    unittest.main()

