import json
import time
from http.client import IncompleteRead
from urllib import request
from urllib.error import URLError, HTTPError
from app.schemas.embedding import Embedding
from app.schemas.document_chunk import DocumentChunk
from app.config import EMBEDDING_PROVIDER,ALIYUN_API_KEY, ALIYUN_EMBEDDING_MODEL

# 向量化 HTTP 请求的健壮性参数。
# 阿里云 embedding 接口是远程 HTTP 服务，网络抖动 / keep-alive 连接被中途关闭时，
# response.read() 会抛 IncompleteRead（“已读 N 字节，还差 M 字节”）——这正是
# “上传成功但入库失败”的真正原因：文件已落盘，但向量化那一步的 HTTP 响应被截断。
# 单次失败不该让整份文档入库失败，所以这里对可重试的网络错误做指数退避重试。
_HTTP_MAX_RETRIES = 4          # 总尝试次数 = 1 + 重试；含首次共 4 次
_HTTP_BACKOFF_BASE = 1.0       # 退避基数（秒）：1s, 2s, 4s ...
_HTTP_TIMEOUT = 60             # 单次请求超时（秒）


def _post_json_with_retry(url: str, payload: dict) -> dict:
    """向远程接口 POST 一段 JSON，并健壮地读取响应。

    针对“上传成功、入库失败”的根因做加固：
    - IncompleteRead：连接在读完整个响应体之前被关闭（最常见的截断）。
    - URLError / socket 超时 / 远端 5xx：临时性网络或服务端抖动。
    以上都做指数退避重试；重试耗尽后才抛出，让错误信息更明确、可定位。
    HTTP 4xx（除 429）通常是请求本身有问题，不重试，直接抛出。
    """
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {ALIYUN_API_KEY}",
        "Content-Type": "application/json",
    }

    last_exc: Exception | None = None
    for attempt in range(_HTTP_MAX_RETRIES):
        try:
            req = request.Request(url=url, data=data, headers=headers, method="POST")
            with request.urlopen(req, timeout=_HTTP_TIMEOUT) as response:
                raw = response.read()
            return json.loads(raw.decode("utf-8"))
        except HTTPError as exc:
            # 4xx 客户端错误（限流 429 除外）通常重试也没用，直接抛出。
            if exc.code != 429 and 400 <= exc.code < 500:
                raise
            last_exc = exc
        except (IncompleteRead, URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as exc:
            last_exc = exc

        # 还有下一次机会就退避后重试；最后一次失败则跳出去抛错。
        if attempt < _HTTP_MAX_RETRIES - 1:
            time.sleep(_HTTP_BACKOFF_BASE * (2 ** attempt))

    raise RuntimeError(
        f"向量化请求失败（已重试 {_HTTP_MAX_RETRIES} 次）：{type(last_exc).__name__}: {last_exc}"
    )

def create_fake_embedding(
    chunk_id:int,
    text:str,        
) -> Embedding:
    vector =[ 
    float(len(text)),
    float(chunk_id),
    ]

    return Embedding(
        chunk_id=chunk_id,
        vector=vector,
    )

def create_aliyun_embedding_vector(text:str) -> list[float]:
    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
    payload = {
        "model" : ALIYUN_EMBEDDING_MODEL,
        "input" : text,
    }

    response_data = _post_json_with_retry(url, payload)

    return response_data["data"][0]["embedding"]

def create_aliyun_embedding_vectors(texts: list[str]) -> list[list[float]]:
    """一次请求向量化多条文本，返回与输入顺序对齐的向量列表。

    阿里云 embedding 接口的 input 可以是数组，一次返回多条，
    大幅减少 HTTP 往返次数（这是入库慢的主因）。
    返回的 data 顺序不一定与输入一致，这里按每项的 index 排序对齐。
    """
    if not texts:
        return []

    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
    payload = {
        "model": ALIYUN_EMBEDDING_MODEL,
        "input": texts,
    }
    response_data = _post_json_with_retry(url, payload)

    items = sorted(response_data["data"], key=lambda d: d["index"])
    return [item["embedding"] for item in items]

def create_embedding(
    chunk_id:int,
    text:str,        
) -> Embedding:
    if EMBEDDING_PROVIDER == "fake":
        return create_fake_embedding(
            chunk_id=chunk_id,
            text=text,    
        )
    
    if EMBEDDING_PROVIDER == "aliyun":
        vector = create_aliyun_embedding_vector(text)
        return Embedding(
            chunk_id=chunk_id,
            vector=vector,    
        )

    raise ValueError(f"Unsupported embedding provider: {EMBEDDING_PROVIDER}")

    

def create_embeddings_for_chunks(
        chunks:list[DocumentChunk],
) -> list[Embedding]:
    # 根据配置走真实 provider（阿里云）或 fake。
    # 阿里云走"分批批量"：一次请求向量化多条，显著减少 HTTP 往返、加快入库。
    if EMBEDDING_PROVIDER == "aliyun":
        return _create_aliyun_embeddings_batched(chunks)

    embeddings = []
    for chunk in chunks:
        embedding = create_embedding(
            chunk_id=chunk.id,
            text=chunk.content,
        )
        embeddings.append(embedding)
    return embeddings

# 每批向量化的文本条数。阿里云 embedding 单次批量有上限，取较保守值以兼容不同模型/网关。
EMBEDDING_BATCH_SIZE = 10

def _create_aliyun_embeddings_batched(
        chunks: list[DocumentChunk],
) -> list[Embedding]:
    embeddings: list[Embedding] = []
    for start in range(0, len(chunks), EMBEDDING_BATCH_SIZE):
        batch = chunks[start:start + EMBEDDING_BATCH_SIZE]
        vectors = create_aliyun_embedding_vectors([c.content for c in batch])
        for chunk, vector in zip(batch, vectors):
            embeddings.append(Embedding(chunk_id=chunk.id, vector=vector))
    return embeddings

# 兼容旧名字：老代码/老测试如果还调用 create_fake_embeddings_for_chunks，仍然能用。
create_fake_embeddings_for_chunks = create_embeddings_for_chunks

def create_fake_query_embedding(question:str) -> list[float]:
    return [
        float(len(question)),
        2.0,    
    ]

def create_query_embedding(question:str) -> list[float]:
    if EMBEDDING_PROVIDER == "fake":
        return create_fake_query_embedding(question)
    
    if EMBEDDING_PROVIDER == "aliyun":
        return create_aliyun_embedding_vector(question)
    
    raise ValueError(f"Unsupported embedding provider: {EMBEDDING_PROVIDER}")