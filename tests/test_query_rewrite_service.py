"""query_rewrite_service 单元测试（检索质量专线·阶段4）。

覆盖，全部走 fake / 打桩，零网络零付费：
1. fake provider 产出 n 条不同改写。
2. n<=0 或空问题返回 []。
3. 失败降级：真实 provider 内部异常时返回 []（只用原查询）而非抛出。
"""

import unittest
import logging

import app.services.query_rewrite_service as qr


class TestQueryRewriteService(unittest.TestCase):
    def setUp(self):
        self._orig = qr.QUERY_REWRITE_PROVIDER
        logging.disable(logging.CRITICAL)

    def tearDown(self):
        qr.QUERY_REWRITE_PROVIDER = self._orig
        logging.disable(logging.NOTSET)

    def test_fake_returns_n_distinct(self):
        qr.QUERY_REWRITE_PROVIDER = "fake"
        out = qr.rewrite("多租户隔离怎么实现", n=3)
        self.assertEqual(len(out), 3)
        # 都不等于原问题、互不相同。
        self.assertTrue(all(s != "多租户隔离怎么实现" for s in out))
        self.assertEqual(len(set(out)), 3)

    def test_zero_or_empty_returns_empty(self):
        qr.QUERY_REWRITE_PROVIDER = "fake"
        self.assertEqual(qr.rewrite("问题", n=0), [])
        self.assertEqual(qr.rewrite("", n=3), [])
        self.assertEqual(qr.rewrite("   ", n=3), [])

    def test_failure_degrades_to_empty(self):
        # 真实 provider 内部抛错 → 降级为 []（调用方退回只用原查询），不抛出。
        qr.QUERY_REWRITE_PROVIDER = "deepseek"

        def _boom(question, n):
            raise RuntimeError("模拟网络故障")

        orig = qr._deepseek_rewrite
        qr._deepseek_rewrite = _boom
        try:
            self.assertEqual(qr.rewrite("任意问题", n=3), [])
        finally:
            qr._deepseek_rewrite = orig

    def test_unknown_provider_degrades(self):
        qr.QUERY_REWRITE_PROVIDER = "nope"
        self.assertEqual(qr.rewrite("问题", n=3), [])


if __name__ == "__main__":
    unittest.main()
