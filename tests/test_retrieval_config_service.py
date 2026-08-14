"""检索配置服务的单元测试 + HTTP 层三级配置与隔离回归。

覆盖：
- resolve_effective 三级优先级（kb→tenant→system→硬默认）。
- 多/全库按 tenant.multi_scope 偏好取 system 或 tenant。
- HTTP：系统级仅管理员可写；kb 级隔离（他人 403）；tenant 级各自独立。
"""

import unittest
import logging

import app.services.answer_service as answer_service
from app.services import (
    retrieval_config_service as rc,
    knowledge_base_service,
    metadata_service,
    user_service,
    kb_service,
    quota_service,
    topic_service,
    auth_service,
)
import chromadb
from fastapi.testclient import TestClient
from app.api import app


class TestResolveEffective(unittest.TestCase):
    """纯服务层：解析优先级与兜底（不走 HTTP）。"""

    def setUp(self):
        logging.disable(logging.CRITICAL)
        rc._set_repo_for_test(rc.InMemoryConfigRepo())

    def tearDown(self):
        rc._reset_repo_for_test()
        logging.disable(logging.NOTSET)

    def test_hard_defaults_when_empty(self):
        d = rc.resolve_effective(owner_id=1, kb_id=99)
        # 无任何配置行 → 硬默认（含默认作答提示词）
        self.assertEqual(d["top_k"], rc.RAG_TOP_K)
        self.assertEqual(d["max_distance"], rc.RAG_MAX_DISTANCE)
        self.assertTrue(d["answer_prompt"])

    def test_single_kb_priority_kb_over_tenant_over_system(self):
        rc.set_system(top_k=5, max_distance=0.5, judge_enabled=False, answer_prompt="sys")
        rc.set_tenant(owner_id=1, top_k=7, max_distance=0.4,
                      judge_enabled=False, answer_prompt="tenant", multi_scope="system")
        rc.set_kb(kb_id=10, owner_id=1, top_k=9, max_distance=0.3,
                  judge_enabled=True, answer_prompt="kb")

        # 有 kb 行 → 用 kb
        d = rc.resolve_effective(owner_id=1, kb_id=10)
        self.assertEqual((d["top_k"], d["max_distance"], d["answer_prompt"]), (9, 0.3, "kb"))

        # 另一个库无 kb 行 → 落到 tenant
        d2 = rc.resolve_effective(owner_id=1, kb_id=11)
        self.assertEqual((d2["top_k"], d2["answer_prompt"]), (7, "tenant"))

    def test_single_kb_falls_to_system_when_no_tenant(self):
        rc.set_system(top_k=6, max_distance=0.6, judge_enabled=True, answer_prompt="sys")
        d = rc.resolve_effective(owner_id=2, kb_id=20)
        self.assertEqual((d["top_k"], d["answer_prompt"], d["judge_enabled"]), (6, "sys", True))

    def test_multi_scope_system_uses_system_not_tenant(self):
        rc.set_system(top_k=5, max_distance=0.5, judge_enabled=False, answer_prompt="sys")
        rc.set_tenant(owner_id=1, top_k=8, max_distance=0.2,
                      judge_enabled=True, answer_prompt="tenant", multi_scope="system")
        # 多/全库(kb_id=None) + 偏好 system → 取 system，忽略 tenant
        d = rc.resolve_effective(owner_id=1, kb_id=None)
        self.assertEqual((d["top_k"], d["answer_prompt"]), (5, "sys"))

    def test_multi_scope_tenant_uses_tenant(self):
        rc.set_system(top_k=5, max_distance=0.5, judge_enabled=False, answer_prompt="sys")
        rc.set_tenant(owner_id=1, top_k=8, max_distance=0.2,
                      judge_enabled=True, answer_prompt="tenant", multi_scope="tenant")
        d = rc.resolve_effective(owner_id=1, kb_id=None)
        self.assertEqual((d["top_k"], d["answer_prompt"]), (8, "tenant"))

    def test_multi_scope_tenant_falls_to_system_when_no_tenant_row(self):
        # 偏好想用 tenant，但没有 tenant 行 → get_multi_scope 默认 system → 用 system
        rc.set_system(top_k=5, max_distance=0.5, judge_enabled=False, answer_prompt="sys")
        d = rc.resolve_effective(owner_id=1, kb_id=None)
        self.assertEqual(d["answer_prompt"], "sys")

    def test_clear_kb_falls_back(self):
        rc.set_tenant(owner_id=1, top_k=7, max_distance=0.4,
                      judge_enabled=False, answer_prompt="tenant", multi_scope="system")
        rc.set_kb(kb_id=10, owner_id=1, top_k=9, max_distance=0.3,
                  judge_enabled=True, answer_prompt="kb")
        self.assertEqual(rc.resolve_effective(1, 10)["answer_prompt"], "kb")
        rc.clear_kb(10)
        self.assertEqual(rc.resolve_effective(1, 10)["answer_prompt"], "tenant")


class TestRetrievalConfigApi(unittest.TestCase):
    """HTTP 层：鉴权 + 多租户隔离（红线）。"""

    def setUp(self):
        self.orig_ans = answer_service.ANSWER_PROVIDER
        answer_service.ANSWER_PROVIDER = "fake"
        logging.disable(logging.CRITICAL)

        user_service._set_repo_for_test(user_service.InMemoryUserRepo())
        kb_service._set_repo_for_test(kb_service.InMemoryKbRepo())
        quota_service._set_repo_for_test(quota_service.InMemoryQuotaRepo())
        metadata_service._set_repo_for_test(metadata_service.InMemoryMetadataRepo())
        topic_service._set_repo_for_test(topic_service.InMemoryTopicRepo())
        rc._set_repo_for_test(rc.InMemoryConfigRepo())

        chroma_client = chromadb.EphemeralClient()
        collection = chroma_client.get_or_create_collection(
            name="rc_iso_kb", metadata={"hnsw:space": "cosine"}
        )
        knowledge_base_service._set_collection_for_test(collection)

        self.client = TestClient(app)
        self.admin = user_service.create_user("admin", "admin123", role="admin")
        self.alice = user_service.create_user("alice", "alice123", role="user")
        self.bob = user_service.create_user("bob", "bob123", role="user")
        self.alice_kb = kb_service.create_kb(self.alice["id"], "Alice库", enforce_quota=False)["id"]

    def tearDown(self):
        answer_service.ANSWER_PROVIDER = self.orig_ans
        knowledge_base_service._reset_collection_for_test()
        for svc in (metadata_service, user_service, kb_service, quota_service):
            svc._reset_repo_for_test()
        topic_service._reset_repo_for_test()
        rc._reset_repo_for_test()
        logging.disable(logging.NOTSET)

    def _hdr(self, username, password):
        token = auth_service.create_access_token(
            user_service.verify_password(username, password)
        )
        return {"Authorization": f"Bearer {token}"}

    def _body(self, **over):
        base = {"top_k": 5, "max_distance": 0.5, "judge_enabled": False, "answer_prompt": "p"}
        base.update(over)
        return base

    def test_system_config_admin_only(self):
        admin_h = self._hdr("admin", "admin123")
        alice_h = self._hdr("alice", "alice123")

        # 管理员可写系统配置
        r = self.client.put("/config/retrieval", params={"scope": "system"},
                            json=self._body(top_k=8), headers=admin_h)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["top_k"], 8)

        # 普通用户写系统配置 → 403
        r2 = self.client.put("/config/retrieval", params={"scope": "system"},
                             json=self._body(top_k=3), headers=alice_h)
        self.assertEqual(r2.status_code, 403)

        # 系统配置未被普通用户改动
        r3 = self.client.get("/config/retrieval", params={"scope": "system"}, headers=admin_h)
        self.assertEqual(r3.json()["top_k"], 8)

    def test_kb_config_isolation(self):
        alice_h = self._hdr("alice", "alice123")
        bob_h = self._hdr("bob", "bob123")

        # Alice 给自己的库设配置
        r = self.client.put("/config/retrieval", params={"scope": "kb", "kb_id": self.alice_kb},
                            json=self._body(max_distance=0.3), headers=alice_h)
        self.assertEqual(r.status_code, 200)

        # Bob 读/写 Alice 库的配置 → 403（隔离红线）
        rd = self.client.get("/config/retrieval", params={"scope": "kb", "kb_id": self.alice_kb},
                            headers=bob_h)
        self.assertEqual(rd.status_code, 403)
        wr = self.client.put("/config/retrieval", params={"scope": "kb", "kb_id": self.alice_kb},
                            json=self._body(max_distance=0.9), headers=bob_h)
        self.assertEqual(wr.status_code, 403)

        # 管理员可跨库读
        admin_h = self._hdr("admin", "admin123")
        ad = self.client.get("/config/retrieval", params={"scope": "kb", "kb_id": self.alice_kb},
                            headers=admin_h)
        self.assertEqual(ad.status_code, 200)
        self.assertEqual(ad.json()["max_distance"], 0.3)

    def test_tenant_config_is_per_user(self):
        alice_h = self._hdr("alice", "alice123")
        bob_h = self._hdr("bob", "bob123")

        self.client.put("/config/retrieval", params={"scope": "tenant"},
                        json=self._body(top_k=9, multi_scope="tenant"), headers=alice_h)
        # Bob 读自己的 tenant 配置：应是继承/默认，不是 Alice 的 9
        bob_view = self.client.get("/config/retrieval", params={"scope": "tenant"}, headers=bob_h).json()
        self.assertNotEqual(bob_view["top_k"], 9)
        self.assertTrue(bob_view["inherited"])
        # Alice 读回自己的 9
        alice_view = self.client.get("/config/retrieval", params={"scope": "tenant"}, headers=alice_h).json()
        self.assertEqual(alice_view["top_k"], 9)
        self.assertFalse(alice_view["inherited"])

    def test_put_validates_range(self):
        admin_h = self._hdr("admin", "admin123")
        # top_k 超范围 → pydantic 422
        r = self.client.put("/config/retrieval", params={"scope": "system"},
                            json=self._body(top_k=999), headers=admin_h)
        self.assertEqual(r.status_code, 422)


if __name__ == "__main__":
    unittest.main()
