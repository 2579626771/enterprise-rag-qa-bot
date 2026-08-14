import unittest

import app.services.judge_service as judge_service
from app.services.judge_service import judge_and_answer, REFUSAL_TEXT


class TestJudgeServiceFake(unittest.TestCase):
    """研判服务的 fake provider 逻辑（确定性、不发网络请求）。

    仿 test_answer_service：setUp 切 judge_service.ANSWER_PROVIDER = "fake"。
    judge_service 与 answer_service 一样把 ANSWER_PROVIDER 作为模块级快照引用，
    因此这里 patch 的是 judge_service 自己的模块级名字。
    """

    def setUp(self):
        self.original_provider = judge_service.ANSWER_PROVIDER
        judge_service.ANSWER_PROVIDER = "fake"

    def tearDown(self):
        judge_service.ANSWER_PROVIDER = self.original_provider

    def test_empty_context_is_not_answerable(self):
        # 没有任何资料 → 判为不能回答，返回拒答话术。
        result = judge_and_answer(question="随便问", context="")
        self.assertFalse(result["answerable"])
        self.assertEqual(result["answer"], REFUSAL_TEXT)
        self.assertEqual(result["confidence"], "low")

    def test_blank_context_is_not_answerable(self):
        # 纯空白资料也应判为不能回答。
        result = judge_and_answer(question="随便问", context="   \n  ")
        self.assertFalse(result["answerable"])

    def test_nonempty_context_is_answerable(self):
        # 有资料 → 判为可回答，答案里回显问题与资料（fake 风格）。
        result = judge_and_answer(question="怎么读取文档？", context="用 read_text_file 读取。")
        self.assertTrue(result["answerable"])
        self.assertIn("怎么读取文档？", result["answer"])
        self.assertEqual(result["confidence"], "high")

    def test_return_shape_has_all_keys(self):
        # 返回结构必须包含四个约定字段，供上层与前端消费。
        result = judge_and_answer(question="q", context="some context")
        for key in ("answerable", "reason", "answer", "confidence"):
            self.assertIn(key, result)

    def test_unsupported_provider_raises(self):
        judge_service.ANSWER_PROVIDER = "unknown-provider"
        with self.assertRaises(ValueError):
            judge_and_answer(question="q", context="c")


if __name__ == "__main__":
    unittest.main()
