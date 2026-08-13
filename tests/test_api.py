import unittest
import logging
import shutil
import chromadb
from pathlib import Path
import app.services.embedding_service as embedding_service
import app.services.answer_service as answer_service
from app.services import knowledge_base_service
from app.services import metadata_service
from app.services import user_service
from app.services import kb_service
from app.services import quota_service
from app.services import auth_service
from app.services.document_service import kb_documents_dir
from fastapi.testclient import TestClient
from app.api import app


class TestApi(unittest.TestCase):
    def setUp(self):
        self.original_embedding_provider = embedding_service.EMBEDDING_PROVIDER
        self.original_answer_provider = answer_service.ANSWER_PROVIDER
        embedding_service.EMBEDDING_PROVIDER = "fake"
        answer_service.ANSWER_PROVIDER = "fake"
        logging.disable(logging.CRITICAL)

        # 所有数据层用内存仓库，隔离测试。
        user_service._set_repo_for_test(user_service.InMemoryUserRepo())
        kb_service._set_repo_for_test(kb_service.InMemoryKbRepo())
        quota_service._set_repo_for_test(quota_service.InMemoryQuotaRepo())
        metadata_service._set_repo_for_test(metadata_service.InMemoryMetadataRepo())

        admin = user_service.create_user(
            "test_admin", "admin_pw", role="admin", display_name="测试管理员"
        )
        # 给测试用户建一个知识库，作为大多数用例的操作目标。
        self.kb = kb_service.create_kb(admin["id"], "测试库", "", enforce_quota=False)
        self.kb_id = self.kb["id"]

        token = auth_service.create_access_token(admin)
        self.client = TestClient(app)
        self.client.headers.update({"Authorization": f"Bearer {token}"})

        # 内存版向量库，隔离测试。
        chroma_client = chromadb.EphemeralClient()
        try:
            chroma_client.delete_collection(name="test_kb")
        except Exception:
            pass
        collection = chroma_client.get_or_create_collection(
            name="test_kb",
            metadata={"hnsw:space": "cosine"},
        )
        knowledge_base_service._set_collection_for_test(collection)

    def tearDown(self):
        embedding_service.EMBEDDING_PROVIDER = self.original_embedding_provider
        answer_service.ANSWER_PROVIDER = self.original_answer_provider

        # 先算出物理目录（依赖 kb 仓库），再重置仓库；清掉该库目录及其空的用户父目录。
        kb_dir = kb_documents_dir(self.kb_id)

        knowledge_base_service._reset_collection_for_test()
        metadata_service._reset_repo_for_test()
        user_service._reset_repo_for_test()
        kb_service._reset_repo_for_test()
        quota_service._reset_repo_for_test()

        if kb_dir.exists():
            shutil.rmtree(kb_dir, ignore_errors=True)
        # 用户目录若已空则一并删掉，保持 data/documents 干净
        parent = kb_dir.parent
        try:
            if parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
        except OSError:
            pass

        logging.disable(logging.NOTSET)

    # ---- 便捷封装：把 kb_id 带上 ----
    def _upload(self, filename, content, topic="未分类", description=""):
        return self.client.post(
            "/documents/upload",
            data={"kb_id": str(self.kb_id), "topic": topic, "description": description},
            files={"file": (filename, content, "text/plain")},
        )

    def test_read_root(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"message": "Enterprise RAG API is running"})

    def test_list_documents(self):
        response = self.client.get("/documents", params={"kb_id": self.kb_id})
        self.assertEqual(response.status_code, 200)
        self.assertIn("documents", response.json())
        docs = response.json()["documents"]
        self.assertIsInstance(docs, list)
        for item in docs:
            self.assertIn("filename", item)
            self.assertIn("topic", item)
            self.assertIn("status", item)
            self.assertIn("uploaded_at", item)

    def test_upload_persists_metadata(self):
        response = self._upload("test_upload.txt", "这是一个带元数据的测试上传文档。",
                                topic="技术文档", description="接口测试用文档")
        self.assertEqual(response.status_code, 200)

        meta = metadata_service.get(self.kb_id, "test_upload.txt")
        self.assertIsNotNone(meta)
        self.assertEqual(meta["topic"], "技术文档")
        self.assertEqual(meta["description"], "接口测试用文档")

        listed = self.client.get("/documents", params={"kb_id": self.kb_id}).json()["documents"]
        found = next((d for d in listed if d["filename"] == "test_upload.txt"), None)
        self.assertIsNotNone(found)
        self.assertEqual(found["topic"], "技术文档")

    def test_delete_removes_metadata(self):
        self._upload("test_delete.txt", "用于测试删除会清理元数据的文档。", topic="产品手册")
        self.assertIsNotNone(metadata_service.get(self.kb_id, "test_delete.txt"))

        delete_response = self.client.delete(
            "/documents/test_delete.txt", params={"kb_id": self.kb_id}
        )
        self.assertEqual(delete_response.status_code, 200)
        self.assertIsNone(metadata_service.get(self.kb_id, "test_delete.txt"))

    def test_upload_document(self):
        response = self._upload("test_upload.txt", "这是一个测试上传文档。")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["filename"], "test_upload.txt")
        # 改为异步入库后，上传响应返回状态而非片段数；片段数由后台入库后经列表查询获取。
        self.assertIn("status", response.json())
        self.assertTrue((kb_documents_dir(self.kb_id) / "test_upload.txt").exists())

    def test_upload_then_ask_rag(self):
        upload_response = self._upload(
            "test_upload.txt", "在测试上传文档中，可以使用 read_text_file 读取文档内容。"
        )
        self.assertEqual(upload_response.status_code, 200)

        ask_response = self.client.post(
            "/rag/ask",
            json={"question": "怎么读取文档内容？", "kb_id": self.kb_id},
        )
        self.assertEqual(ask_response.status_code, 200)
        self.assertIn("answer", ask_response.json())
        self.assertIn("sources", ask_response.json())
        self.assertTrue(len(ask_response.json()["sources"]) >= 1)

    def test_ingest_document(self):
        response = self.client.post(
            "/documents/ingest",
            json={"file_path": "data/sample.txt", "kb_id": self.kb_id},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("chunk_count", response.json())
        self.assertTrue(response.json()["chunk_count"] >= 1)

    def test_ingest_document_with_missing_file(self):
        response = self.client.post(
            "/documents/ingest",
            json={"file_path": "data/not_exists.txt", "kb_id": self.kb_id},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "File not found")

    def test_delete_document(self):
        upload_response = self._upload("test_delete.txt", "这是一个用于测试删除接口的文档。")
        self.assertEqual(upload_response.status_code, 200)
        fpath = kb_documents_dir(self.kb_id) / "test_delete.txt"
        self.assertTrue(fpath.exists())

        delete_response = self.client.delete(
            "/documents/test_delete.txt", params={"kb_id": self.kb_id}
        )
        self.assertEqual(delete_response.status_code, 200)
        self.assertEqual(delete_response.json()["filename"], "test_delete.txt")
        self.assertTrue(delete_response.json()["deleted"])
        self.assertFalse(fpath.exists())

    def test_delete_document_with_missing_file(self):
        response = self.client.delete(
            "/documents/not_exists.txt", params={"kb_id": self.kb_id}
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "File not found")

    def test_delete_document_with_non_txt_file(self):
        response = self.client.delete(
            "/documents/test.exe", params={"kb_id": self.kb_id}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Unsupported file type", response.json()["detail"])

    def test_upload_document_with_non_txt_file(self):
        response = self._upload("test.exe", "fake binary content")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Unsupported file type", response.json()["detail"])

    def test_ask_rag_on_empty_knowledge_base(self):
        response = self.client.post(
            "/rag/ask",
            json={"question": "怎么读取文档内容？", "kb_id": self.kb_id},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("answer", response.json())
        self.assertEqual(response.json()["sources"], [])

    def test_ask_rag_with_empty_question(self):
        response = self.client.post(
            "/rag/ask",
            json={"question": "", "kb_id": self.kb_id},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Question cannot be empty")

    def test_access_others_kb_forbidden(self):
        # 另建一个用户 bob 和他的库，test_admin 是 admin 可跨库；换普通用户验证隔离更合适。
        bob = user_service.create_user("bob", "bob123", role="user")
        bob_kb = kb_service.create_kb(bob["id"], "bob库", "", enforce_quota=False)
        # 用 bob 的令牌访问 admin 的库 → 403
        bob_token = auth_service.create_access_token(bob)
        r = self.client.get(
            "/documents",
            params={"kb_id": self.kb_id},
            headers={"Authorization": f"Bearer {bob_token}"},
        )
        self.assertEqual(r.status_code, 403)
        # bob 访问自己的库 → 200
        r2 = self.client.get(
            "/documents",
            params={"kb_id": bob_kb["id"]},
            headers={"Authorization": f"Bearer {bob_token}"},
        )
        self.assertEqual(r2.status_code, 200)

    # ---- 需求1：更新知识库名称/描述 ----
    def test_update_kb(self):
        r = self.client.put(
            f"/kbs/{self.kb_id}",
            json={"name": "改名后的库", "description": "新描述"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["name"], "改名后的库")
        self.assertEqual(r.json()["description"], "新描述")
        # 落库确认
        self.assertEqual(kb_service.get(self.kb_id)["name"], "改名后的库")

    def test_update_kb_empty_name_rejected(self):
        r = self.client.put(f"/kbs/{self.kb_id}", json={"name": "   "})
        self.assertEqual(r.status_code, 400)

    def test_update_others_kb_forbidden(self):
        bob = user_service.create_user("bob", "bob123", role="user")
        bob_kb = kb_service.create_kb(bob["id"], "bob库", "", enforce_quota=False)
        bob_token = auth_service.create_access_token(bob)
        # bob 改 admin 的库 → 403
        r = self.client.put(
            f"/kbs/{self.kb_id}",
            json={"name": "越权改名"},
            headers={"Authorization": f"Bearer {bob_token}"},
        )
        self.assertEqual(r.status_code, 403)
        # bob 改自己的库 → 200
        r2 = self.client.put(
            f"/kbs/{bob_kb['id']}",
            json={"name": "bob改名"},
            headers={"Authorization": f"Bearer {bob_token}"},
        )
        self.assertEqual(r2.status_code, 200)

    # ---- 需求4：管理员调整用户配额 ----
    def test_admin_update_user_quota(self):
        bob = user_service.create_user("bob", "bob123", role="user")
        r = self.client.patch(f"/users/{bob['id']}/quota", json={"quota": 8})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["kb_quota"], 8)
        self.assertEqual(user_service.get_quota(bob["id"]), 8)

    def test_update_quota_below_used_rejected(self):
        bob = user_service.create_user("bob", "bob123", role="user")
        for i in range(2):
            kb_service.create_kb(bob["id"], f"库{i}", enforce_quota=False)
        # 已用 2 个，设成 1 应被拒
        r = self.client.patch(f"/users/{bob['id']}/quota", json={"quota": 1})
        self.assertEqual(r.status_code, 400)

    def test_update_quota_requires_admin(self):
        bob = user_service.create_user("bob", "bob123", role="user")
        bob_token = auth_service.create_access_token(bob)
        r = self.client.patch(
            f"/users/{bob['id']}/quota",
            json={"quota": 5},
            headers={"Authorization": f"Bearer {bob_token}"},
        )
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
