from dataclasses import dataclass

@dataclass
class DocumentChunk:
    id:int
    document_id:int
    chunk_index:int
    content:str