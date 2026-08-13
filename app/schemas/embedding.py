from dataclasses import dataclass


@dataclass
class Embedding:
    chunk_id:int
    vector:list[float]