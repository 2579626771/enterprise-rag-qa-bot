import unittest
import app.services.embedding_service as embedding_service
from app.services.embedding_service import (
    create_fake_embedding,
    create_fake_embeddings_for_chunks,
    create_fake_query_embedding,
    create_query_embedding,
    create_embedding)
from app.services.document_service import create_document_chunk

class TestEmbeddingService(unittest.TestCase):

    def setUp(self):
        self.original_provider = embedding_service.EMBEDDING_PROVIDER
        embedding_service.EMBEDDING_PROVIDER = "fake"

    def tearDown(self):
        embedding_service.EMBEDDING_PROVIDER = self.original_provider
        

    def test_create_fake_embedding(self):
        embedding = create_fake_embedding(
                  chunk_id=1,
                  text = "abc",
        )
        self.assertEqual(embedding.chunk_id,1)
        self.assertEqual(embedding.vector,[3.0,1.0])

    def test_create_fake_embeddings_for_chunks(self):
        chunks = [
          create_document_chunk(
             chunk_id=1,
             document_id=1,
             chunk_index=0,
             content="abc",
       ),
          create_document_chunk(
              chunk_id=2,
              document_id=1,
              chunk_index=1,
              content="hello",
        ),   
    ]

        embeddings = create_fake_embeddings_for_chunks(chunks)

        self.assertEqual(len(embeddings),2)
        self.assertEqual(embeddings[0].vector,[3.0,1.0])
        self.assertEqual(embeddings[1].vector,[5.0,2.0])

    def test_create_fake_query_embedding(self):
        query_vector = create_fake_query_embedding("abc")

        self.assertEqual(query_vector,[3.0,2.0])


    def test_create_query_embedding(self):
        query_vector = create_query_embedding("abc")

        self.assertEqual(query_vector,[3.0,2.0])


    def test_create_query_embedding_with_unsupported_provider(self):
        original_provider = embedding_service.EMBEDDING_PROVIDER
        embedding_service.EMBEDDING_PROVIDER = "unknown"

        try:
            with self.assertRaises(ValueError):
                embedding_service.create_query_embedding("abc")
        finally:
            embedding_service.EMBEDDING_PROVIDER = original_provider


    def test_create_embedding(self):
        embedding = create_embedding(
            chunk_id=1,    
            text="abc",
        )

        self.assertEqual(embedding.chunk_id,1)
        self.assertEqual(embedding.vector,[3.0,1.0])


    def test_create_embedding_with_unsupported_provider(self):
        original_provider = embedding_service.EMBEDDING_PROVIDER
        embedding_service.EMBEDDING_PROVIDER = "unknown"

        try:
            with self.assertRaises(ValueError):
                embedding_service.create_embedding(
                    chunk_id=1,
                    text="abc",
                )
        finally:
            embedding_service.EMBEDDING_PROVIDER = original_provider

if __name__ == "__main__":
    unittest.main()