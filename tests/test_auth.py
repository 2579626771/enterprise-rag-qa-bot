import unittest
import logging

from fastapi.testclient import TestClient

from app.services import user_service
from app.services import kb_service
from app.services import quota_service
from app.services import auth_service
from app.api import app


class TestAuth(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        # 每个测试独立的内存仓库（用户 + 知识库 + 配额）
        user_service._set_repo_for_test(user_service.InMemoryUserRepo())
        kb_service._set_repo_for_test(kb_service.InMemoryKbRepo())
        quota_service._set_repo_for_test(quota_service.InMemoryQuotaRepo())
        self.admin = user_service.create_user(
            "admin", "admin123", role="admin", display_name="系统管理员"
        )
        self.client = TestClient(app)

    def tearDown(self):
        user_service._reset_repo_for_test()
        kb_service._reset_repo_for_test()
        quota_service._reset_repo_for_test()
        logging.disable(logging.NOTSET)

    def _login(self, username, password):
        return self.client.post(
            "/auth/login", json={"username": username, "password": password}
        )

    def _auth_header(self, username, password):
        token = self._login(username, password).json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    # ---- 自助注册 ----
    def test_register_success_and_auto_login(self):
        resp = self.client.post(
            "/auth/register",
            json={"username": "newuser01", "password": "pass1234", "display_name": "新用户"},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("access_token", body)
        self.assertEqual(body["user"]["username"], "newuser01")
        # 注册只能是普通用户
        self.assertEqual(body["user"]["role"], "user")
        self.assertNotIn("password_hash", body["user"])
        # 之后可用该账号登录
        self.assertEqual(self._login("newuser01", "pass1234").status_code, 200)

    def test_register_cannot_be_admin(self):
        # 即使 body 里塞 role=admin，也应被忽略，仍是普通用户
        resp = self.client.post(
            "/auth/register",
            json={"username": "hacker01", "password": "pass1234", "role": "admin"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["user"]["role"], "user")

    def test_register_duplicate_username(self):
        self.client.post("/auth/register", json={"username": "dup01", "password": "pass1234"})
        resp = self.client.post("/auth/register", json={"username": "dup01", "password": "pass1234"})
        self.assertEqual(resp.status_code, 400)

    def test_register_password_too_short(self):
        resp = self.client.post("/auth/register", json={"username": "shortpw", "password": "123"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("密码", resp.json()["detail"])

    def test_register_invalid_username(self):
        # 含空格 / 中文 / 过短都应拒绝
        for bad in ["ab", "has space", "中文名", "a" * 40]:
            resp = self.client.post("/auth/register", json={"username": bad, "password": "pass1234"})
            self.assertEqual(resp.status_code, 400, f"用户名 {bad!r} 应被拒绝")

    def test_register_default_display_name(self):
        resp = self.client.post("/auth/register", json={"username": "nodisplay", "password": "pass1234"})
        self.assertEqual(resp.status_code, 200)
        # 不填显示名时，默认等于用户名
        self.assertEqual(resp.json()["user"]["display_name"], "nodisplay")

    # ---- 登录 ----
    def test_login_success_returns_token(self):
        resp = self._login("admin", "admin123")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("access_token", body)
        self.assertEqual(body["token_type"], "bearer")
        self.assertEqual(body["user"]["username"], "admin")
        self.assertEqual(body["user"]["role"], "admin")
        # 返回体绝不能带密码哈希
        self.assertNotIn("password_hash", body["user"])

    def test_login_wrong_password(self):
        resp = self._login("admin", "wrong")
        self.assertEqual(resp.status_code, 401)

    def test_login_unknown_user(self):
        resp = self._login("ghost", "whatever")
        self.assertEqual(resp.status_code, 401)

    # ---- 受保护接口（用 /auth/me 作为通用鉴权探针，不涉及 kb_id）----
    def test_protected_without_token(self):
        self.assertEqual(self.client.get("/auth/me").status_code, 401)

    def test_protected_with_token(self):
        header = self._auth_header("admin", "admin123")
        self.assertEqual(self.client.get("/auth/me", headers=header).status_code, 200)

    def test_protected_with_garbage_token(self):
        header = {"Authorization": "Bearer not-a-real-token"}
        self.assertEqual(self.client.get("/auth/me", headers=header).status_code, 401)

    def test_me_endpoint(self):
        header = self._auth_header("admin", "admin123")
        resp = self.client.get("/auth/me", headers=header)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["username"], "admin")

    # ---- 角色控制 ----
    def test_admin_can_list_users(self):
        header = self._auth_header("admin", "admin123")
        resp = self.client.get("/users", headers=header)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any(u["username"] == "admin" for u in resp.json()["users"]))

    def test_normal_user_forbidden_on_users(self):
        # 管理员先建一个普通用户
        admin_header = self._auth_header("admin", "admin123")
        self.client.post(
            "/users",
            json={"username": "bob", "password": "bob123", "role": "user"},
            headers=admin_header,
        )
        # 普通用户访问 /users → 403
        user_header = self._auth_header("bob", "bob123")
        self.assertEqual(self.client.get("/users", headers=user_header).status_code, 403)

    def test_create_duplicate_user_rejected(self):
        header = self._auth_header("admin", "admin123")
        payload = {"username": "carol", "password": "carol123", "role": "user"}
        self.assertEqual(self.client.post("/users", json=payload, headers=header).status_code, 200)
        # 重名 → 400
        self.assertEqual(self.client.post("/users", json=payload, headers=header).status_code, 400)

    def test_cannot_delete_self(self):
        header = self._auth_header("admin", "admin123")
        resp = self.client.delete(f"/users/{self.admin['id']}", headers=header)
        self.assertEqual(resp.status_code, 400)

    def test_cannot_delete_last_admin(self):
        # 建一个普通用户，用管理员令牌尝试删掉“另一个管理员”场景：
        # 这里 admin 是唯一管理员，删自己已被上一条覆盖；此处验证删唯一管理员的保护，
        # 通过再建一个管理员、删掉原管理员应成功，但删到只剩一个时被拦。
        header = self._auth_header("admin", "admin123")
        # 目前只有 1 个 admin，尝试删除它（用另一个 admin 令牌）
        second = user_service.create_user("admin2", "admin2pw", role="admin")
        header2 = self._auth_header("admin2", "admin2pw")
        # 删掉第一个 admin：此时仍剩 admin2，应成功
        self.assertEqual(
            self.client.delete(f"/users/{self.admin['id']}", headers=header2).status_code, 200
        )
        # 现在只剩 admin2 一个管理员，删它 → 400（不能删最后一个管理员，且也是自己）
        self.assertEqual(
            self.client.delete(f"/users/{second['id']}", headers=header2).status_code, 400
        )

    # ---- 密码与令牌 ----
    def test_password_hash_is_salted(self):
        h1 = user_service.hash_password("same")
        h2 = user_service.hash_password("same")
        self.assertNotEqual(h1, h2)  # bcrypt 每次 salt 不同
        self.assertTrue(user_service.check_password("same", h1))
        self.assertTrue(user_service.check_password("same", h2))
        self.assertFalse(user_service.check_password("other", h1))

    def test_token_roundtrip(self):
        token = auth_service.create_access_token(self.admin)
        payload = auth_service.decode_token(token)
        self.assertEqual(payload["sub"], "admin")
        self.assertEqual(payload["role"], "admin")

    def test_decode_invalid_token_raises(self):
        with self.assertRaises(auth_service.TokenError):
            auth_service.decode_token("garbage.token.here")

    def test_ensure_default_admin_idempotent(self):
        # 重置为空仓库，连续调用只建一个 admin
        user_service._set_repo_for_test(user_service.InMemoryUserRepo())
        user_service.ensure_default_admin()
        user_service.ensure_default_admin()
        self.assertEqual(user_service.count("admin"), 1)


if __name__ == "__main__":
    unittest.main()
