import unittest
import logging
import chromadb
import app.services.embedding_service as embedding_service
import app.services.answer_service as answer_service
from app.services import knowledge_base_service
from app.services.rag_service import answer_from_knowledge_base
from app.services.document_service import create_document


class TestRagService(unittest.TestCase):
    def setUp(self):
        # 用 fake provider，避免调用真实阿里云 / DeepSeek 付费接口。
        self.original_embedding_provider = embedding_service.EMBEDDING_PROVIDER
        self.original_answer_provider = answer_service.ANSWER_PROVIDER
        embedding_service.EMBEDDING_PROVIDER = "fake"
        answer_service.ANSWER_PROVIDER = "fake"
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
        knowledge_base_service._reset_collection_for_test()
        logging.disable(logging.NOTSET)

    def test_answer_from_empty_knowledge_base(self):
        # 知识库为空时，应给出友好提示而不是报错。
        result = answer_from_knowledge_base(question="随便问点什么？")
        self.assertIn("answer", result)
        self.assertIn("sources", result)
        self.assertEqual(result["sources"], [])

    def test_answer_from_knowledge_base(self):
        # 先入库一个文档到 kb=1，再在 kb=1 范围内提问。
        document = create_document(
            document_id=0,
            filename="rag_demo.txt",
            file_type="txt",
            content="第一段：如何读取文档内容。\n\n第二段：如何上传文档。",
        )
        knowledge_base_service.ingest_document(document, kb_id=1)

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


if __name__ == "__main__":
    unittest.main()
