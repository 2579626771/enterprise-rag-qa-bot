"""LangChain 适配层（检索质量专线·阶段1 地基）。

目的：把本项目已有的两块基础设施接入 LangChain 生态，为后续检索增强（rerank、
多查询改写等）铺地基——采用「绞杀者模式」，只接管「检索召回」这一段，其余
（入库/删除/统计）仍走原生 chromadb，把改动的爆炸半径压到最小。

本模块提供两件东西：
1. AliyunEmbeddings：把阿里云百炼 embedding 包成 LangChain 的 Embeddings 子类，
   复用 embedding_service 已有的批量/重试/并发/ fake 逻辑，不重复造轮子。
2. build_chroma_vectorstore(collection)：用 langchain_chroma.Chroma 包住「一个已存在
   的 chromadb collection」，与 knowledge_base_service 的持久化/测试注入共享同一底层集合，
   绝不新建 client（否则会与主链路的档案柜脱节、也会破坏测试注入）。

内网约束（照抄 judge_service 的防御）：langchain_chroma / langchain_core 在 import 与
运行时可能触发 httpx/SSL 相关初始化；沿用「函数内惰性 import + SSL_CERT_FILE 清理 +
truststore 注入 + 失败静默」的成熟模式，保证内网证书环境不崩、非内网环境无副作用。
"""

from app.services import embedding_service
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _inject_truststore_ssl() -> None:
    """内网 HTTPS 证书防御（与 judge_service 一致）。

    langchain / httpx 自建 SSL 上下文、不读系统证书库，公司安全网关拦截 HTTPS 时会握手
    失败。用 truststore 把 Python SSL 接到系统信任库；注入前先清掉指向不存在文件的
    SSL_CERT_FILE（否则 httpx 的 load_verify_locations 会抛 FileNotFoundError）。
    全程静默失败：非内网环境本就不需要，出错也不该影响功能。
    """
    try:
        import os

        cert_file = os.environ.get("SSL_CERT_FILE")
        if cert_file and not os.path.exists(cert_file):
            logger.warning(f"SSL_CERT_FILE 指向不存在的文件，已忽略：{cert_file}")
            os.environ.pop("SSL_CERT_FILE", None)

        import truststore

        truststore.inject_into_ssl()
    except Exception:  # noqa: BLE001 —— 防御性，失败不影响主流程
        pass


class AliyunEmbeddings:
    """把阿里云 embedding 适配成 LangChain 的 Embeddings 接口。

    只实现 LangChain 检索所需的两个方法：embed_documents / embed_query。
    内部完全委托 embedding_service —— 复用它的批量/重试/并发，以及 EMBEDDING_PROVIDER=fake
    分支（测试与离线开发零网络）。不继承 langchain_core.embeddings.Embeddings 的类型标注，
    而是用鸭子类型（langchain_chroma 只调这两个方法），避免 import-time 依赖 langchain_core。
    """

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """向量化一批文档文本（入库/批量场景）。委托 embedding_service。"""
        # embedding_service 内部按 EMBEDDING_PROVIDER 分流（aliyun 批量 / fake 确定性）。
        from app.config import EMBEDDING_PROVIDER

        if EMBEDDING_PROVIDER == "fake":
            # 与 create_fake_query_embedding 同构：保证测试确定、零网络。
            return [[float(len(t)), 2.0] for t in texts]
        if EMBEDDING_PROVIDER == "aliyun":
            return embedding_service.create_aliyun_embedding_vectors(texts)
        raise ValueError(f"Unsupported embedding provider: {EMBEDDING_PROVIDER}")

    def embed_query(self, text: str) -> list[float]:
        """向量化查询文本（检索场景）。委托 embedding_service.create_query_embedding。"""
        return embedding_service.create_query_embedding(text)


def build_chroma_vectorstore(client, collection_name: str):
    """用 langchain_chroma.Chroma 包住「一个已存在的 chromadb 集合」。

    参数：
    - client：chromadb 的**公共** ClientAPI（PersistentClient / EphemeralClient 返回的对象），
      不是 collection._client（那是底层 RustBindingsAPI，签名/返回类型不同，langchain 用它会崩）。
    - collection_name：集合名（与 knowledge_base_service.get_collection() 用的同名）。

    这样 LangChain 复用主链路同一个持久化集合（检索到的就是入库的），测试注入的
    EphemeralClient 集合也能被正确包住——绝不新建 client/collection。

    两个关键点（已实测验证）：
    - create_collection_if_not_exists=False：走 client.get_collection(name) 路径，返回带 .query
      的 Collection；集合必然已存在（get_collection() 早已 get_or_create 过），无需再建。
    - embedding_function 传 AliyunEmbeddings：similarity_search_with_score 用它的 embed_query
      把问题向量化后再查（与主链路 create_query_embedding 完全一致）。

    返回对象的 similarity_search_with_score(query, k, filter) 的 score 即 Chroma 原始余弦
    距离（越小越相似，无任何换算）—— 保证 distance 语义不漂移、RAG_MAX_DISTANCE 阈值继续有效。
    """
    _inject_truststore_ssl()
    # 惰性 import：只有真正走到检索召回时才加载 langchain_chroma，未用到时零依赖零副作用。
    from langchain_chroma import Chroma

    return Chroma(
        client=client,
        collection_name=collection_name,
        embedding_function=AliyunEmbeddings(),
        create_collection_if_not_exists=False,
    )
