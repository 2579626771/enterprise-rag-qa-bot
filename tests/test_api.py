import unittest
import logging
import shutil
import chromadb
from pathlib import Path
import app.services.embedding_service as embedding_service
import app.services.answer_service as answer_service
import app.api as api_module
from app.services import knowledge_base_service
from app.services import metadata_service
from app.services import user_service
from app.services import kb_service
from app.services import quota_service
from app.services import auth_service
from app.services import session_service
from app.services import topic_service
from app.services.document_service import kb_documents_dir
from fastapi.testclient import TestClient
from app.api import app


class TestApi(unittest.TestCase):
    def setUp(self):
        self.original_embedding_provider = embedding_service.EMBEDDING_PROVIDER
        self.original_answer_provider = answer_service.ANSWER_PROVIDER
        self.original_upload_max_mb = api_module.DOCUMENT_UPLOAD_MAX_MB
        embedding_service.EMBEDDING_PROVIDER = "fake"
        answer_service.ANSWER_PROVIDER = "fake"
        logging.disable(logging.CRITICAL)

        # 所有数据层用内存仓库，隔离测试。
        user_service._set_repo_for_test(user_service.InMemoryUserRepo())
        kb_service._set_repo_for_test(kb_service.InMemoryKbRepo())
        quota_service._set_repo_for_test(quota_service.InMemoryQuotaRepo())
        metadata_service._set_repo_for_test(metadata_service.InMemoryMetadataRepo())
        session_service._set_repo_for_test(session_service.InMemorySessionRepo())
        topic_service._set_repo_for_test(topic_service.InMemoryTopicRepo())

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
        api_module.DOCUMENT_UPLOAD_MAX_MB = self.original_upload_max_mb

        # 先算出物理目录（依赖 kb 仓库），再重置仓库；清掉该库目录及其空的用户父目录。
        kb_dir = kb_documents_dir(self.kb_id)

        knowledge_base_service._reset_collection_for_test()
        metadata_service._reset_repo_for_test()
        session_service._reset_repo_for_test()
        topic_service._reset_repo_for_test()
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

    def test_healthz(self):
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_readyz_reports_mysql_failure(self):
        original = api_module.check_mysql_ready
        api_module.check_mysql_ready = lambda: (_ for _ in ()).throw(RuntimeError("mysql down"))
        try:
            response = self.client.get("/readyz")
        finally:
            api_module.check_mysql_ready = original
        self.assertEqual(response.status_code, 503)
        self.assertIn("mysql down", response.json()["detail"])

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

    def test_upload_sanitizes_path_traversal_filename(self):
        response = self._upload("../evil.txt", "路径穿越文件名应被清洗。")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["filename"], "evil.txt")
        self.assertTrue((kb_documents_dir(self.kb_id) / "evil.txt").exists())
        self.assertFalse((kb_documents_dir(self.kb_id).parent / "evil.txt").exists())

    def test_upload_rejects_unsupported_extension(self):
        response = self._upload("bad.exe", "bad")
        self.assertEqual(response.status_code, 400)

    def test_upload_rejects_oversized_file_and_removes_partial(self):
        api_module.DOCUMENT_UPLOAD_MAX_MB = 0
        response = self._upload("too_big.txt", "x")
        self.assertEqual(response.status_code, 413)
        self.assertFalse((kb_documents_dir(self.kb_id) / "too_big.txt").exists())

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
        sample = kb_documents_dir(self.kb_id) / "sample_ingest.txt"
        sample.write_text("可以使用 read_text_file(file_path) 函数读取 txt 文档内容。", encoding="utf-8")
        response = self.client.post(
            "/documents/ingest",
            json={"file_path": str(sample), "kb_id": self.kb_id},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("chunk_count", response.json())
        self.assertTrue(response.json()["chunk_count"] >= 1)

    def test_ingest_requires_admin(self):
        user = user_service.create_user("normal_user", "normal_pw", role="user")
        token = auth_service.create_access_token(user)
        sample = kb_documents_dir(self.kb_id) / "user_forbidden.txt"
        sample.write_text("普通用户不能调用 ingest。", encoding="utf-8")
        response = self.client.post(
            "/documents/ingest",
            json={"file_path": str(sample), "kb_id": self.kb_id},
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(response.status_code, 403)

    def test_ingest_rejects_path_outside_kb_dir(self):
        response = self.client.post(
            "/documents/ingest",
            json={"file_path": "data/sample.txt", "kb_id": self.kb_id},
        )
        self.assertEqual(response.status_code, 403)

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

    # ---- 会话历史（服务端持久化 + 归属隔离）----
    def test_session_crud_flow(self):
        # 新建
        r = self.client.post("/sessions", json={"title": "我的会话"})
        self.assertEqual(r.status_code, 200)
        sid = r.json()["id"]
        # 列表
        listed = self.client.get("/sessions").json()["sessions"]
        self.assertTrue(any(s["id"] == sid for s in listed))
        # 追加消息
        r2 = self.client.post(
            f"/sessions/{sid}/messages",
            json={"role": "user", "content": "你好", "sources": []},
        )
        self.assertEqual(r2.status_code, 200)
        # 读消息
        msgs = self.client.get(f"/sessions/{sid}/messages").json()["messages"]
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["content"], "你好")
        # 改名
        r3 = self.client.patch(f"/sessions/{sid}", json={"title": "改名会话"})
        self.assertEqual(r3.status_code, 200)
        self.assertEqual(r3.json()["title"], "改名会话")
        # 收藏切换
        r4 = self.client.patch(f"/sessions/{sid}", json={"toggle_favorite": True})
        self.assertTrue(r4.json()["is_favorite"])
        # 删除
        r5 = self.client.delete(f"/sessions/{sid}")
        self.assertEqual(r5.status_code, 200)
        self.assertEqual(self.client.get("/sessions").json()["sessions"], [])

    def test_session_isolated_between_users(self):
        # admin 建一个会话
        sid = self.client.post("/sessions", json={"title": "admin会话"}).json()["id"]
        # bob 用自己的令牌
        bob = user_service.create_user("bob", "bob123", role="user")
        bob_headers = {"Authorization": f"Bearer {auth_service.create_access_token(bob)}"}
        # bob 看不到 admin 的会话
        self.assertEqual(self.client.get("/sessions", headers=bob_headers).json()["sessions"], [])
        # bob 无法读取/删除/追加 admin 的会话 → 404
        self.assertEqual(
            self.client.get(f"/sessions/{sid}/messages", headers=bob_headers).status_code, 404
        )
        self.assertEqual(self.client.delete(f"/sessions/{sid}", headers=bob_headers).status_code, 404)
        self.assertEqual(
            self.client.post(
                f"/sessions/{sid}/messages",
                json={"role": "user", "content": "x"},
                headers=bob_headers,
            ).status_code,
            404,
        )

    def test_session_requires_auth(self):
        r = self.client.get("/sessions", headers={"Authorization": ""})
        self.assertEqual(r.status_code, 401)

    def test_session_update_no_content_400(self):
        sid = self.client.post("/sessions", json={"title": "会话"}).json()["id"]
        r = self.client.patch(f"/sessions/{sid}", json={})
        self.assertEqual(r.status_code, 400)

    # ---- 主题分类（按知识库隔离：属主或管理员可增删改查）----
    def test_new_kb_auto_seeded(self):
        # setUp 建库时应已自动种入 8 个默认分类
        r = self.client.get("/topics", params={"kb_id": self.kb_id})
        self.assertEqual(r.status_code, 200)
        names = [t["name"] for t in r.json()["topics"]]
        self.assertEqual(len(names), 8)
        self.assertIn("技术文档", names)

    def test_add_rename_delete_topic(self):
        # 新增
        r = self.client.post("/topics", json={"kb_id": self.kb_id, "name": "安全合规"})
        self.assertEqual(r.status_code, 200)
        tid = r.json()["id"]
        self.assertEqual(r.json()["kb_id"], self.kb_id)
        # 重命名
        rr = self.client.patch(f"/topics/{tid}", json={"name": "安全与合规"})
        self.assertEqual(rr.status_code, 200)
        self.assertEqual(rr.json()["name"], "安全与合规")
        names = [t["name"] for t in self.client.get("/topics", params={"kb_id": self.kb_id}).json()["topics"]]
        self.assertIn("安全与合规", names)
        self.assertNotIn("安全合规", names)
        # 删除
        rd = self.client.delete(f"/topics/{tid}")
        self.assertEqual(rd.status_code, 200)
        names2 = [t["name"] for t in self.client.get("/topics", params={"kb_id": self.kb_id}).json()["topics"]]
        self.assertNotIn("安全与合规", names2)

    def test_rename_cascades_to_documents(self):
        # 上传一个文档并归类为「技术文档」
        self._upload("cascade.txt", "级联重命名测试文档内容。", topic="技术文档")
        # 找到该库「技术文档」分类的 id
        topics = self.client.get("/topics", params={"kb_id": self.kb_id}).json()["topics"]
        tid = next(t["id"] for t in topics if t["name"] == "技术文档")
        # 重命名分类
        self.client.patch(f"/topics/{tid}", json={"name": "技术资料"})
        # 文档的 topic 应联动更新
        doc = metadata_service.get(self.kb_id, "cascade.txt")
        self.assertEqual(doc["topic"], "技术资料")

    def test_add_topic_empty_rejected(self):
        r = self.client.post("/topics", json={"kb_id": self.kb_id, "name": "   "})
        self.assertEqual(r.status_code, 400)

    def test_topic_kb_isolation(self):
        # 再建一个库，它有自己独立的分类
        kb2 = kb_service.create_kb(
            self.client.get("/auth/me").json()["id"], "第二个库", "", enforce_quota=False
        )
        self.client.post("/topics", json={"kb_id": self.kb_id, "name": "仅库一"})
        names2 = [t["name"] for t in self.client.get("/topics", params={"kb_id": kb2["id"]}).json()["topics"]]
        self.assertNotIn("仅库一", names2)  # 库二看不到库一新增的分类
        self.assertEqual(len(names2), 8)  # 库二仍是自己的 8 个默认分类

    def test_delete_missing_topic_404(self):
        r = self.client.delete("/topics/999999")
        self.assertEqual(r.status_code, 404)

    def test_non_owner_forbidden(self):
        # bob 不能访问 admin 的库分类
        bob = user_service.create_user("bob", "bob123", role="user")
        bob_headers = {"Authorization": f"Bearer {auth_service.create_access_token(bob)}"}
        # 读 admin 库 → 403
        self.assertEqual(
            self.client.get("/topics", params={"kb_id": self.kb_id}, headers=bob_headers).status_code,
            403,
        )
        # 增 admin 库 → 403
        self.assertEqual(
            self.client.post(
                "/topics", json={"kb_id": self.kb_id, "name": "越权"}, headers=bob_headers
            ).status_code,
            403,
        )
        # 改/删 admin 库某分类 → 403（先拿一个 admin 库的分类 id）
        tid = self.client.get("/topics", params={"kb_id": self.kb_id}).json()["topics"][0]["id"]
        self.assertEqual(
            self.client.patch(f"/topics/{tid}", json={"name": "x"}, headers=bob_headers).status_code,
            403,
        )
        self.assertEqual(
            self.client.delete(f"/topics/{tid}", headers=bob_headers).status_code, 403
        )


if __name__ == "__main__":
    unittest.main()
