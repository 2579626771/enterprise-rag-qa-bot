"""多知识库隔离的端到端测试（走 HTTP API）。

核心验证：用户 A 在自己的知识库上传文档后，用户 B 既看不到、也问不到 A 的内容；
管理员可跨库访问；配额申请 → 审批 → 可建更多库 的完整闭环。
"""

import unittest
import logging
import shutil
import chromadb
from pathlib import Path

import app.services.embedding_service as embedding_service
import app.services.answer_service as answer_service
from app.services import (
    knowledge_base_service,
    metadata_service,
    user_service,
    kb_service,
    quota_service,
    auth_service,
)
from app.services.document_service import kb_documents_dir
from fastapi.testclient import TestClient
from app.api import app


class TestKbIsolation(unittest.TestCase):
    def setUp(self):
        self.orig_emb = embedding_service.EMBEDDING_PROVIDER
        self.orig_ans = answer_service.ANSWER_PROVIDER
        embedding_service.EMBEDDING_PROVIDER = "fake"
        answer_service.ANSWER_PROVIDER = "fake"
        logging.disable(logging.CRITICAL)

        user_service._set_repo_for_test(user_service.InMemoryUserRepo())
        kb_service._set_repo_for_test(kb_service.InMemoryKbRepo())
        quota_service._set_repo_for_test(quota_service.InMemoryQuotaRepo())
        metadata_service._set_repo_for_test(metadata_service.InMemoryMetadataRepo())

        chroma_client = chromadb.EphemeralClient()
        try:
            chroma_client.delete_collection(name="iso_kb")
        except Exception:
            pass
        collection = chroma_client.get_or_create_collection(
            name="iso_kb", metadata={"hnsw:space": "cosine"}
        )
        knowledge_base_service._set_collection_for_test(collection)

        self.client = TestClient(app)

        # 三个角色
        self.admin = user_service.create_user("admin", "admin123", role="admin")
        self.alice = user_service.create_user("alice", "alice123", role="user")
        self.bob = user_service.create_user("bob", "bob123", role="user")
        # 各自一个库
        self.alice_kb = kb_service.create_kb(self.alice["id"], "Alice库", enforce_quota=False)["id"]
        self.bob_kb = kb_service.create_kb(self.bob["id"], "Bob库", enforce_quota=False)["id"]

        self._kb_dirs = [self.alice_kb, self.bob_kb]

    def tearDown(self):
        embedding_service.EMBEDDING_PROVIDER = self.orig_emb
        answer_service.ANSWER_PROVIDER = self.orig_ans
        # 先算出物理目录（依赖 kb 仓库），再重置仓库。
        dirs = [kb_documents_dir(kb_id) for kb_id in self._kb_dirs]
        knowledge_base_service._reset_collection_for_test()
        for svc in (metadata_service, user_service, kb_service, quota_service):
            svc._reset_repo_for_test()
        for d in dirs:
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)
            # 空的用户父目录一并清掉
            try:
                if d.parent.exists() and not any(d.parent.iterdir()):
                    d.parent.rmdir()
            except OSError:
                pass
        logging.disable(logging.NOTSET)

    def _hdr(self, username, password):
        token = auth_service.create_access_token(
            user_service.verify_password(username, password)
        )
        return {"Authorization": f"Bearer {token}"}

    def _upload(self, header, kb_id, filename, content):
        return self.client.post(
            "/documents/upload",
            data={"kb_id": str(kb_id), "topic": "技术文档", "description": ""},
            files={"file": (filename, content, "text/plain")},
            headers=header,
        )

    def test_document_isolation(self):
        alice_h = self._hdr("alice", "alice123")
        bob_h = self._hdr("bob", "bob123")

        # Alice 上传到自己的库
        r = self._upload(alice_h, self.alice_kb, "secret.txt", "Alice的机密：项目代号猎户座启动。")
        self.assertEqual(r.status_code, 200)

        # Alice 能在自己库看到
        alice_docs = self.client.get("/documents", params={"kb_id": self.alice_kb}, headers=alice_h).json()["documents"]
        self.assertTrue(any(d["filename"] == "secret.txt" for d in alice_docs))

        # Bob 看自己的库：空
        bob_docs = self.client.get("/documents", params={"kb_id": self.bob_kb}, headers=bob_h).json()["documents"]
        self.assertEqual(len(bob_docs), 0)

        # Bob 试图访问 Alice 的库 → 403
        forbidden = self.client.get("/documents", params={"kb_id": self.alice_kb}, headers=bob_h)
        self.assertEqual(forbidden.status_code, 403)

    def test_qa_isolation(self):
        alice_h = self._hdr("alice", "alice123")
        bob_h = self._hdr("bob", "bob123")

        self._upload(alice_h, self.alice_kb, "secret.txt", "项目代号是猎户座，预算一千万。")

        # Alice 在自己库能问到
        a = self.client.post("/rag/ask", json={"question": "项目代号是什么？", "kb_id": self.alice_kb}, headers=alice_h)
        self.assertEqual(a.status_code, 200)
        self.assertTrue(len(a.json()["sources"]) >= 1)

        # Bob 在自己（空）库问 → 无来源
        b = self.client.post("/rag/ask", json={"question": "项目代号是什么？", "kb_id": self.bob_kb}, headers=bob_h)
        self.assertEqual(b.status_code, 200)
        self.assertEqual(b.json()["sources"], [])

        # Bob 试图在 Alice 库问 → 403
        f = self.client.post("/rag/ask", json={"question": "项目代号？", "kb_id": self.alice_kb}, headers=bob_h)
        self.assertEqual(f.status_code, 403)

    def test_admin_cross_kb(self):
        alice_h = self._hdr("alice", "alice123")
        admin_h = self._hdr("admin", "admin123")
        self._upload(alice_h, self.alice_kb, "secret.txt", "内容：管理员应当能跨库查看。")

        # 管理员访问 Alice 的库 → 200 且能看到文档
        r = self.client.get("/documents", params={"kb_id": self.alice_kb}, headers=admin_h)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(any(d["filename"] == "secret.txt" for d in r.json()["documents"]))

    def test_quota_request_flow(self):
        alice_h = self._hdr("alice", "alice123")
        admin_h = self._hdr("admin", "admin123")

        # Alice 默认配额 3，已用 1（setup 建了 Alice库）。再建 2 个到上限。
        self.client.post("/kbs", json={"name": "库2"}, headers=alice_h)
        self.client.post("/kbs", json={"name": "库3"}, headers=alice_h)
        # 第 4 个 → 403
        over = self.client.post("/kbs", json={"name": "库4"}, headers=alice_h)
        self.assertEqual(over.status_code, 403)

        # 提交申请 +2
        req = self.client.post("/kb-requests", json={"amount": 2, "reason": "扩容"}, headers=alice_h)
        self.assertEqual(req.status_code, 200)
        req_id = req.json()["id"]

        # 管理员看到待审批
        pending = self.client.get("/kb-requests/pending", headers=admin_h).json()["requests"]
        self.assertTrue(any(x["id"] == req_id for x in pending))

        # 普通用户访问待审批 → 403
        self.assertEqual(self.client.get("/kb-requests/pending", headers=alice_h).status_code, 403)

        # 管理员通过
        self.client.post(f"/kb-requests/{req_id}/approve", headers=admin_h)

        # 现在 Alice 能建第 4 个库
        ok = self.client.post("/kbs", json={"name": "库4"}, headers=alice_h)
        self.assertEqual(ok.status_code, 200)

    def test_reload_reports_scoped_count(self):
        alice_h = self._hdr("alice", "alice123")
        bob_h = self._hdr("bob", "bob123")
        # Alice 库与 Bob 库各放一个文档
        self._upload(alice_h, self.alice_kb, "a.txt", "Alice 的第一段内容。第二段内容。")
        self._upload(bob_h, self.bob_kb, "b.txt", "Bob 的第一段。第二段。第三段。")
        # 重载 Alice 的库：片段数应只统计 Alice 库，与其 stats 一致（不是两库之和）
        r = self.client.post("/maintenance/reload", params={"kb_id": self.alice_kb}, headers=alice_h)
        self.assertEqual(r.status_code, 200)
        alice_total = r.json()["total_chunks"]
        stats = self.client.get("/stats", params={"kb_id": self.alice_kb}, headers=alice_h).json()
        self.assertEqual(alice_total, stats["total_chunks"])
        # Bob 无权重载 Alice 的库
        self.assertEqual(
            self.client.post("/maintenance/reload", params={"kb_id": self.alice_kb}, headers=bob_h).status_code,
            403,
        )

    def test_delete_kb_cascades(self):
        alice_h = self._hdr("alice", "alice123")
        self._upload(alice_h, self.alice_kb, "d.txt", "将被连带删除的内容。")
        # 删库前先记住物理目录（删库后 kb 记录没了就解析不出来了）
        kb_dir = kb_documents_dir(self.alice_kb)
        self.assertTrue(kb_dir.exists())
        # 删库
        r = self.client.delete(f"/kbs/{self.alice_kb}", headers=alice_h)
        self.assertEqual(r.status_code, 200)
        # 库没了：再访问其文档 → 404（知识库不存在）
        after = self.client.get("/documents", params={"kb_id": self.alice_kb}, headers=alice_h)
        self.assertEqual(after.status_code, 404)
        # 物理目录被清除
        self.assertFalse(kb_dir.exists())


if __name__ == "__main__":
    unittest.main()
