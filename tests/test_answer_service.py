import unittest
import app.services.answer_service as answer_service
from app.services.answer_service import generate_fake_answer, generate_answer

class TestAnswerService(unittest.TestCase):

    def setUp(self):
        self.original_provider = answer_service.ANSWER_PROVIDER
        answer_service.ANSWER_PROVIDER = "fake"

    def tearDown(self):
        answer_service.ANSWER_PROVIDER = self.original_provider
        
    def test_generate_fake_answer(self):
        answer = generate_fake_answer(
            question="怎么读取文档？",
            context="可以使用 read_text_file 读取文档。",      
        )

        self.assertIn("可以使用 read_text_file 读取文档。",answer)
        self.assertIn("怎么读取文档？",answer)

    def test_generate_answer(self):
        answer = generate_answer(
            question="怎么读取文档？",
            context="可以使用 read_text_file 读取文档。",
        )

        self.assertIn("可以使用 read_text_file 读取文档。", answer)
        self.assertIn("怎么读取文档？", answer)

    def test_generate_answer_with_unsupported_provider(self):
        original_provider = answer_service.ANSWER_PROVIDER
        answer_service.ANSWER_PROVIDER = "unknown"

        try:
            with self.assertRaises(ValueError):
                answer_service.generate_answer(
                    question="怎么读取文档？",
                    context="可以使用 read_text_file 读取文档。",
                )
        finally:
            answer_service.ANSWER_PROVIDER = original_provider


if __name__ == "__main__":
    unittest.main()
