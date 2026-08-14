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
            content="这是只属于知识库一的机密内容：项目代号猎户座。",
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


if __name__ == "__main__":
    unittest.main()

