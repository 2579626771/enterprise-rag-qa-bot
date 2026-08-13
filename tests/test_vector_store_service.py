import unittest
from app.schemas.embedding import Embedding
from app.services.vector_store_service import (create_vector_store,
add_embeddings_to_store,
list_all_embeddings,
find_embedding_by_chunk_id,
calculate_distance,
find_most_similar_embedding,
find_top_k_similar_embeddings)


class TestVectorStoreService(unittest.TestCase):
    def test_add_embeddings_to_store(self):
        vector_store = create_vector_store()

        embeddings = [
            Embedding(chunk_id=1,vector=[3.0,1.0]),
            Embedding(chunk_id=2,vector=[5.0,2.0]),
        ]

        add_embeddings_to_store(vector_store,embeddings)

        self.assertEqual(len(vector_store),2)
        self.assertEqual(vector_store[0].chunk_id,1)
        self.assertEqual(vector_store[1].vector,[5.0,2.0])
    def test_list_all_embeddings(self):
        vector_store = create_vector_store()

        embeddings = [
            Embedding(chunk_id=1,vector=[3.0,1.0]),
            ]
        
        add_embeddings_to_store(vector_store,embeddings)

        result = list_all_embeddings(vector_store)

        self.assertEqual(len(result),1)
        self.assertEqual(result[0].chunk_id,1)
        self.assertEqual(result[0].vector,[3.0,1.0])

    def test_find_embedding_by_chunk_id(self):
        vector_store = create_vector_store()

        embeddings = [
            Embedding(chunk_id=1,vector=[3.0,1.0]),
            Embedding(chunk_id=2,vector=[5.0,2.0]),    
        ]

        add_embeddings_to_store(vector_store,embeddings)

        result = find_embedding_by_chunk_id(
            vector_store,
            chunk_id=2,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.chunk_id,2)
        self.assertEqual(result.vector,[5.0,2.0])
    

    def test_find_embedding_by_chunk_id_not_found(self):
        vector_store = create_vector_store()

        embeddings = [
            Embedding(chunk_id=1,vector=[3.0,1.0]),    
        ]

        add_embeddings_to_store(vector_store,embeddings)

        result =find_embedding_by_chunk_id(
            vector_store,    
            chunk_id=999,        
        )

        self.assertIsNone(result)


    def test_calculate_distance(self):
        distance = calculate_distance(
            [1.0,2.0],
            [1.0,4.0],
        )

        self.assertEqual(distance,4.0)



    def test_find_most_similar_embedding(self):
        vector_store = create_vector_store()

        embeddings = [
            Embedding(chunk_id=1,vector=[10.0,1.0]),
            Embedding(chunk_id=2,vector=[20.0,1.0]),
        ] 

        add_embeddings_to_store(vector_store,embeddings)

        result = find_most_similar_embedding(
            vector_store,
            query_vector=[19.0,2.0],
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.chunk_id,2)
    

    def test_find_most_similar_embedding_with_empty_store(self):
        vector_store = create_vector_store()

        result = find_most_similar_embedding(
            vector_store,
            query_vector=[1.0,2.0],    
        )

        self.assertIsNone(result)

    def test_find_top_k_similar_embeddings(self):
        vector_store = create_vector_store()

        embeddings = [
            Embedding(chunk_id=1, vector=[10.0, 1.0]),
            Embedding(chunk_id=2, vector=[20.0, 2.0]),
            Embedding(chunk_id=3, vector=[100.0, 3.0]),
        ]

        add_embeddings_to_store(vector_store, embeddings)

        results = find_top_k_similar_embeddings(
            vector_store,
            query_vector=[19.0, 2.0],
            k=2,
        )

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].chunk_id, 2)
        self.assertEqual(results[1].chunk_id, 1)

if __name__ == "__main__":
    unittest.main()