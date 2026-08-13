import unittest
from app.services.document_service import(create_document,
split_document_into_chunks, 
read_text_file,
create_document_from_file,
split_document_by_paragraphs,
list_text_files,)




class TestDocumentService(unittest.TestCase):
    def test_split_document_into_chunks(self):
        document = create_document(
            document_id=1,
            filename = "test.txt",
            file_type="txt",
            content="abcdefghijklmnopqrstuvwxyz",
        )
        
        chunks = split_document_into_chunks(
            document,
            chunk_size=10,
            overlap=0,
        )
        
        self.assertEqual(len(chunks),3)
        self.assertEqual(chunks[0].content,"abcdefghij")
        self.assertEqual(chunks[1].content, "klmnopqrst")
        self.assertEqual(chunks[2].content, "uvwxyz")


    def test_split_document_into_chunks_with_overlap(self):
        document = create_document(
            document_id=1,
            filename="test.txt",
            file_type="txt",
            content="abcdefghijklmnopqrstuvwxyz",
        )
        
        chunks = split_document_into_chunks(
            document,
            chunk_size=10,
            overlap=3,
        )
        
        self.assertEqual(len(chunks),4)
        self.assertEqual(chunks[0].content,"abcdefghij")
        self.assertEqual(chunks[1].content,"hijklmnopq")
        self.assertEqual(chunks[2].content,"opqrstuvwx")
        self.assertEqual(chunks[3].content,"vwxyz")

    def test_split_document_into_chunks_with_zero_chunk_size(self):
        document = create_document(
            document_id=1,
            filename="test.txt",
            file_type="txt",
            content="abcdefghijklmnopqrstuvwxyz"
        )
        
        with self.assertRaises(ValueError):
            split_document_into_chunks(
                document,
                chunk_size=0,
                overlap=0,
        )

    def test_split_document_into_chunks_with_negative_overlap(self):
        document = create_document(
            document_id=1,
            filename="test.txt",
            file_type="txt",
            content="abcdefghijklmnopqrstuvwxyz"
        )

        with self.assertRaises(ValueError):
            split_document_into_chunks(
                document,
                chunk_size=10,
                overlap=-1,
        )
            
    def test_split_document_into_chunks_with_overlap_equal_to_chunk_size(self):
        document = create_document(
            document_id=1,
            filename="test.txt",
            file_type="txt",
            content="abcdefghijklmnopqrstuvwxyz"
        )

        with self.assertRaises(ValueError):
            split_document_into_chunks(
                document,
                chunk_size=10,
                overlap=10,
        )

    def test_split_document_into_chunks_with_empty_content(self):
        document = create_document(
            document_id=1,
            filename="tempty.txt",
            file_type="txt",
            content=""
        )

        chunks = split_document_into_chunks(
            document,
            chunk_size=10,
            overlap=0,
        )
        self.assertEqual(chunks,[])

    def test_split_document_into_chunks_metadata(self):
        document = create_document(
            document_id=1,
            filename="tempty.txt",
            file_type="txt",
            content="abcdefghijklmnopqrstuvwxyz"
        )

        chunks = split_document_into_chunks(
            document,
            chunk_size=10,
            overlap=0,
        )

        self.assertEqual(chunks[0].id,1)
        self.assertEqual(chunks[0].document_id,1)
        self.assertEqual(chunks[0].chunk_index,0)
        self.assertEqual(chunks[1].id,2)
        self.assertEqual(chunks[1].document_id,1)
        self.assertEqual(chunks[1].chunk_index,1)


    def test_read_text_file(self):
        content = read_text_file("data/sample.txt")

        self.assertIn("这是一个用于测试 RAG 文档读取功能的示例文本。",content)
        self.assertIn("可以使用 read_text_file(file_path) 函数读取 txt 文档内容。",content)


    def test_create_document_from_file(self):
        document = create_document_from_file(
            document_id=1,
            file_path="data/sample.txt",
        )
        self.assertEqual(document.id,1)
        self.assertEqual(document.filename,"sample.txt")
        self.assertEqual(document.file_type,"txt")
        self.assertIn("这是一个用于测试 RAG 文档读取功能的示例文本。",document.content)


    def test_split_document_by_paragraphs(self):
        document = create_document(
            document_id=1,
            filename="paragraphs.txt",
            file_type="txt",
            content="第一段内容。\n\n第二段内容。",
        )

        # 短段落会被合并（min_chunk_len 默认 30），两个 6 字短段合成一个片段
        chunks = split_document_by_paragraphs(document)

        self.assertEqual(len(chunks), 1)
        self.assertIn("第一段内容。", chunks[0].content)
        self.assertIn("第二段内容。", chunks[0].content)

    def test_split_document_long_paragraphs_stay_separate(self):
        # 达到长度阈值的段落各自独立成片段
        para1 = "这是用于测试的第一段正文内容。" * 6
        para2 = "这是用于测试的第二段正文内容。" * 6
        document = create_document(
            document_id=1,
            filename="long.txt",
            file_type="txt",
            content=f"{para1}\n\n{para2}",
        )
        chunks = split_document_by_paragraphs(document)
        self.assertEqual(len(chunks), 2)

    def test_split_document_caps_long_block(self):
        # 超长块（无空行分隔）会被二次切分为多个不超过 max_chunk_len 的片段
        document = create_document(
            document_id=1,
            filename="big.txt",
            file_type="txt",
            content="句子。" * 300,  # 1200 字的大块
        )
        chunks = split_document_by_paragraphs(document, max_chunk_len=200)
        self.assertGreater(len(chunks), 1)
        for c in chunks:
            self.assertLessEqual(len(c.content), 200)


    def test_list_text_files(self):
        # 用独立临时目录，不依赖 data/documents 里的存量文件（多知识库迁移后已清空）。
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.txt").write_text("hello", encoding="utf-8")
            (Path(tmp) / "b.md").write_text("# md", encoding="utf-8")
            (Path(tmp) / "ignore.exe").write_text("x", encoding="utf-8")

            text_files = list_text_files(tmp)
            names = {Path(p).name for p in text_files}

            # 支持的类型被列出，不支持的被过滤
            self.assertIn("a.txt", names)
            self.assertIn("b.md", names)
            self.assertNotIn("ignore.exe", names)

    def test_list_text_files_missing_dir_returns_empty(self):
        self.assertEqual(list_text_files("no/such/dir/xyz"), [])

    # ---- 目录名清洗（层级目录安全）----
    def test_sanitize_blocks_path_traversal(self):
        from app.services.document_service import _sanitize_path_segment
        # 结果绝不含路径分隔符或 ..，杜绝逃逸
        for evil in ["../etc", "..\\..\\win", "a/b/c", "a\\b", "..", "../../x"]:
            out = _sanitize_path_segment(evil)
            self.assertNotIn("/", out)
            self.assertNotIn("\\", out)
            self.assertNotIn("..", out)

    def test_sanitize_illegal_chars(self):
        from app.services.document_service import _sanitize_path_segment
        out = _sanitize_path_segment('con:name*?"<>|')
        for ch in ':*?"<>|':
            self.assertNotIn(ch, out)

    def test_sanitize_strips_trailing_dot_space(self):
        from app.services.document_service import _sanitize_path_segment
        self.assertEqual(_sanitize_path_segment("  hidden.  "), "hidden")

    def test_sanitize_empty_uses_fallback(self):
        from app.services.document_service import _sanitize_path_segment
        self.assertEqual(_sanitize_path_segment("", fallback="kb"), "kb")
        self.assertEqual(_sanitize_path_segment("   ", fallback="kb"), "kb")

    def test_sanitize_keeps_chinese_and_normal(self):
        from app.services.document_service import _sanitize_path_segment
        self.assertEqual(_sanitize_path_segment("我的知识库"), "我的知识库")
        self.assertEqual(_sanitize_path_segment("user01"), "user01")


if __name__ == "__main__":
    unittest.main()