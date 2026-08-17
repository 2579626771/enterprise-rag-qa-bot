import unittest
import logging

from app.services import model_usage_service as usage


class TestModelUsageService(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        usage._set_repo_for_test(usage.InMemoryModelUsageRepo())

    def tearDown(self):
        usage._reset_repo_for_test()
        logging.disable(logging.NOTSET)

    def test_record_call_with_context(self):
        with usage.usage_context(user_id=10, kb_id=20, request_id="req-1", operation="rag_ask"):
            row = usage.record_call(
                model_type=usage.MODEL_CHAT,
                provider="deepseek",
                model_name="deepseek-test",
                success=True,
                latency_ms=123,
                prompt_tokens=10,
                completion_tokens=5,
            )
        self.assertEqual(row["user_id"], 10)
        self.assertEqual(row["kb_id"], 20)
        self.assertEqual(row["request_id"], "req-1")
        self.assertEqual(row["operation"], "rag_ask")
        self.assertEqual(row["total_tokens"], 15)

    def test_summarize_by_model_and_user(self):
        usage.record_call(usage.MODEL_EMBEDDING, "aliyun", "emb", "query_embedding", True, 100, total_tokens=3, user_id=1)
        usage.record_call(usage.MODEL_CHAT, "deepseek", "chat", "answer", True, 200, prompt_tokens=10, completion_tokens=20, user_id=1)
        usage.record_call(usage.MODEL_CHAT, "deepseek", "chat", "answer", False, 300, user_id=2, error_type="TimeoutError")

        summary = usage.summarize(days=7)
        self.assertEqual(summary["overall"]["call_count"], 3)
        self.assertEqual(summary["overall"]["failed_count"], 1)
        self.assertEqual(summary["overall"]["total_tokens"], 33)
        by_model = {r["model_type"]: r for r in summary["by_model_type"]}
        self.assertEqual(by_model[usage.MODEL_CHAT]["call_count"], 2)
        by_user = {r["user_id"]: r for r in summary["by_user"]}
        self.assertEqual(by_user[1]["total_tokens"], 33)
        self.assertEqual(by_user[2]["failed_count"], 1)

    def test_list_records_filters(self):
        usage.record_call(usage.MODEL_EMBEDDING, "aliyun", "emb", "query_embedding", True, user_id=1)
        usage.record_call(usage.MODEL_CHAT, "deepseek", "chat", "answer", False, user_id=2)
        records = usage.list_records(days=7, user_id=2, success=False)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["model_type"], usage.MODEL_CHAT)

    def test_alerts_for_error_rate_latency_and_tokens(self):
        for _ in range(5):
            usage.record_call(
                usage.MODEL_CHAT,
                "deepseek",
                "chat",
                "answer",
                False,
                latency_ms=25000,
                total_tokens=25000,
                user_id=7,
            )
        alerts = usage.list_alerts(days=1)
        types = {a["type"] for a in alerts}
        self.assertIn("error_rate_high", types)
        self.assertIn("latency_high", types)
        self.assertIn("token_spike", types)

    def test_extract_usage_variants(self):
        self.assertEqual(
            usage.extract_usage({"usage": {"prompt_tokens": 2, "completion_tokens": 3}})["total_tokens"],
            5,
        )
        self.assertEqual(
            usage.extract_usage({"usage": {"input_tokens": 4, "output_tokens": 6, "total_tokens": 12}})["total_tokens"],
            12,
        )


if __name__ == "__main__":
    unittest.main()
