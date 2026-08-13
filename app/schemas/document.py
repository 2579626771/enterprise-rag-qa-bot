from dataclasses import dataclass

@dataclass
class Document:
    id:int
    filename : str
    file_type : str
    content : str