import logging
import shutil
import unittest
from pathlib import Path

import chromadb
from docx import Document as DocxDocument
from fastapi.testclient import TestClient

import app.services.embedding_service as embedding_service
from app.api import app
from app.services import auth_service, kb_service, knowledge_base_service, metadata_service, quota_service, user_service
from app.services.document_service import kb_documents_dir


class TestDocxRechunk(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.orig_embedding_provider = embedding_service.EMBEDDING_PROVIDER
        embedding_service.EMBEDDING_PROVIDER = "fake"

        user_service._set_repo_for_test(user_service.InMemoryUserRepo())
        kb_service._set_repo_for_test(kb_service.InMemoryKbRepo())
        quota_service._set_repo_for_test(quota_service.InMemoryQuotaRepo())
        metadata_service._set_repo_for_test(metadata_service.InMemoryMetadataRepo())

        chroma_client = chromadb.EphemeralClient()
        try:
            chroma_client.delete_collection(name="docx_rechunk")
        except Exception:
            pass
        collection = chroma_client.get_or_create_collection(
            name="docx_rechunk",
            metadata={"hnsw:space": "cosine"},
        )
        knowledge_base_service._set_collection_for_test(collection)
        self.collection = collection

        self.admin = user_service.create_user("admin", "admin123", role="admin")
        self.alice = user_service.create_user("alice", "alice123", role="user")
        self.bob = user_service.create_user("bob", "bob12345", role="user")
        self.alice_kb = kb_service.create_kb(self.alice["id"], "Alice库", enforce_quota=False)["id"]
        self.bob_kb = kb_service.create_kb(self.bob["id"], "Bob库", enforce_quota=False)["id"]
        self._kb_dirs = [self.alice_kb, self.bob_kb]
        self.client = TestClient(app)

    def tearDown(self):
        dirs = [kb_documents_dir(kb_id) for kb_id in self._kb_dirs]
        embedding_service.EMBEDDING_PROVIDER = self.orig_embedding_provider
        knowledge_base_service._reset_collection_for_test()
        metadata_service._reset_repo_for_test()
        user_service._reset_repo_for_test()
        kb_service._reset_repo_for_test()
        quota_service._reset_repo_for_test()
        for d in dirs:
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)
            try:
                if d.parent.exists() and not any(d.parent.iterdir()):
                    d.parent.rmdir()
            except OSError:
                pass
        logging.disable(logging.NOTSET)

    def _hdr(self, username, password):
        token = auth_service.create_access_token(user_service.verify_password(username, password))
        return {"Authorization": f"Bearer {token}"}

    def _write_docx(self, kb_id: int, filename: str, paragraphs: list[str]) -> Path:
        path = kb_documents_dir(kb_id) / filename
        doc = DocxDocument()
        for para in paragraphs:
            doc.add_paragraph(para)
        doc.save(path)
        return path

    def test_service_rechunks_docx_and_removes_old_chunks(self):
        self._write_docx(
            self.alice_kb,
            "manual.docx",
            ["这是新的第一段正文内容。" * 5, "这是新的第二段正文内容。" * 5],
        )
        # 模拟历史旧切分残留：同一个 DOCX 曾经有 5 个片段。
        self.collection.upsert(
            ids=[f"{self.alice_kb}::manual.docx::{i}" for i in range(5)],
            embeddings=[[float(i), 1.0] for i in range(5)],
            documents=[f"旧片段 {i}" for i in range(5)],
            metadatas=[{"kb_id": self.alice_kb, "filename": "manual.docx", "chunk_index": i} for i in range(5)],
        )
        metadata_service.upsert(self.alice_kb, "manual.docx", chunk_count=5)

        result = knowledge_base_service.rechunk_docx_documents(
            self.alice_kb,
            str(kb_documents_dir(self.alice_kb)),
        )

        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["succeeded"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertGreater(result["files"][0]["chunk_count"], 0)
        after = self.collection.get(
            where={"$and": [{"kb_id": self.alice_kb}, {"filename": "manual.docx"}]},
            include=["metadatas", "documents"],
        )
        self.assertEqual(len(after.get("ids") or []), result["files"][0]["chunk_count"])
        self.assertNotIn("旧片段", "\n".join(after.get("documents") or []))
        meta = metadata_service.get(self.alice_kb, "manual.docx")
        self.assertEqual(meta["status"], "就绪")
        self.assertEqual(meta["chunk_count"], result["files"][0]["chunk_count"])

    def test_service_only_processes_docx_files(self):
        self._write_docx(self.alice_kb, "manual.docx", ["Word 正文内容。" * 10])
        (kb_documents_dir(self.alice_kb) / "plain.txt").write_text("txt 不应被重切分", encoding="utf-8")

        result = knowledge_base_service.rechunk_docx_documents(
            self.alice_kb,
            str(kb_documents_dir(self.alice_kb)),
        )

        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["files"][0]["filename"], "manual.docx")
        self.assertIsNone(metadata_service.get(self.alice_kb, "plain.txt"))

    def test_api_requires_owner_or_admin(self):
        self._write_docx(self.alice_kb, "manual.docx", ["Word 正文内容。" * 10])
        alice_h = self._hdr("alice", "alice123")
        bob_h = self._hdr("bob", "bob12345")

        self.assertEqual(
            self.client.post("/maintenance/rechunk-docx", params={"kb_id": self.alice_kb}).status_code,
            401,
        )
        self.assertEqual(
            self.client.post("/maintenance/rechunk-docx", params={"kb_id": self.alice_kb}, headers=bob_h).status_code,
            403,
        )
        ok = self.client.post("/maintenance/rechunk-docx", params={"kb_id": self.alice_kb}, headers=alice_h)
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["succeeded"], 1)


if __name__ == "__main__":
    unittest.main()
