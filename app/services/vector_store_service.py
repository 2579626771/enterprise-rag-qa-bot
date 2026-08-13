from app.schemas.embedding import Embedding

def create_vector_store() -> list[Embedding]:
    return[]

def add_embeddings_to_store(
        vector_store:list[Embedding],
        embeddings:list[Embedding],
    ) -> None:
        for embedding in embeddings:
              vector_store.append(embedding)

def list_all_embeddings(
    vector_store:list[Embedding],        
    ) -> list[Embedding]:
      return vector_store

def find_embedding_by_chunk_id(
    vector_store:list[Embedding],
    chunk_id:int,        
) -> Embedding | None:
    for embedding in vector_store:
        if embedding.chunk_id == chunk_id:
            return embedding
        
    return None



def calculate_distance(
    vector_a:list[float],          
    vector_b:list[float],
) -> float:
    total = 0.0

    for a,b in zip(vector_a,vector_b):
          total += (a-b)**2
    return total


def find_most_similar_embedding(
    vector_store:list[Embedding],
    query_vector:list[float],         
) -> Embedding | None:
    if not vector_store:
        return None
     
    best_embedding = vector_store[0]
    best_distance = calculate_distance(query_vector,best_embedding.vector)

    for embedding in vector_store[1:]:
        distance = calculate_distance(query_vector,embedding.vector)

        if distance < best_distance:
            best_embedding = embedding
            best_distance = distance

    return best_embedding


def find_top_k_similar_embeddings(
    vector_store: list[Embedding],
    query_vector: list[float],
    k: int,
) -> list[Embedding]:
     scored_embeddings = []

     for embedding in vector_store:
          distance = calculate_distance(query_vector,embedding.vector)
          scored_embeddings.append((distance,embedding))
     
     scored_embeddings.sort(key=lambda item: item[0])

     top_items = scored_embeddings[:k]

     return [embedding for distance,embedding in top_items]
    

