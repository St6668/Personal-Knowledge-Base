"""
BGE Embedding 服务 + ChromaDB 向量存储模块

功能：
- 加载 BGE 中文 Embedding 模型（BAAI/bge-small-zh-v1.5）
- 将文本向量化并存储到 ChromaDB
- 提供语义检索能力
- 管理文档分块的增删

依赖：sentence-transformers、chromadb、app.models.schema、app.config
"""

import os
from typing import Optional

import chromadb
from sentence_transformers import SentenceTransformer
from sqlalchemy.orm import Session

from app.config import get_config
from app.models.schema import Document, DocumentChunk, KnowledgeBase

# BGE 模型单例（模块级，避免重复加载）
_bge_model: Optional[SentenceTransformer] = None


def _find_cached_model() -> Optional[str]:
    """查找本地缓存的 BGE 模型路径，避免重复下载"""
    import glob as _glob

    # ModelScope 缓存：~/.cache/modelscope/hub/models/*/bge-small-zh*/
    ms_cache = os.path.join(os.path.expanduser("~"), ".cache", "modelscope", "hub", "models")
    if os.path.exists(ms_cache):
        hits = _glob.glob(os.path.join(ms_cache, "*", "bge-small-zh*"))
        for hit in hits:
            if os.path.isdir(hit):
                return hit

    # HuggingFace 缓存：~/.cache/huggingface/hub/models--*bge-small-zh*/snapshots/*
    hf_cache = os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")
    if os.path.exists(hf_cache):
        hits = _glob.glob(os.path.join(hf_cache, "models--*bge-small-zh*", "snapshots", "*"))
        for hit in hits:
            if os.path.isdir(hit):
                return hit

    return None


def _get_bge_model() -> SentenceTransformer:
    """
    获取 BGE 模型单例，首次调用时加载模型并缓存

    优先使用本地缓存，缓存未命中时从 ModelScope / HuggingFace 下载。
    返回:
        SentenceTransformer 模型实例
    """
    global _bge_model
    if _bge_model is None:
        config = get_config()
        model_name = config.get("embedding", {}).get("model_name", "BAAI/bge-small-zh-v1.5")
        device = config.get("embedding", {}).get("device", "cpu")

        # 1. 检查本地缓存（已下载过则直接加载，跳过网络请求）
        local_path = _find_cached_model()
        if local_path:
            print(f"[Embedding] 使用本地缓存模型: {local_path}")
            _bge_model = SentenceTransformer(local_path, device=device)
            return _bge_model

        # 2. 缓存未命中 → 从 ModelScope 下载
        try:
            from modelscope import snapshot_download
            print("[Embedding] 本地缓存未命中，从 ModelScope 下载模型...")
            local_path = snapshot_download("BAAI/bge-small-zh-v1.5", cache_dir=None)
            print(f"[Embedding] ModelScope 下载完成: {local_path}")
            _bge_model = SentenceTransformer(local_path, device=device)
        except Exception as e:
            # 3. ModelScope 失败 → 回退到 HuggingFace
            print(f"[Embedding] ModelScope 下载失败: {e}，回退到 HuggingFace")
            hf_endpoint = config.get("embedding", {}).get("hf_endpoint", "")
            if hf_endpoint:
                os.environ["HF_ENDPOINT"] = hf_endpoint
            _bge_model = SentenceTransformer(model_name, device=device)

    return _bge_model


class EmbeddingService:
    """
    BGE Embedding 服务 + ChromaDB 向量存储

    封装文本向量化和 ChromaDB 操作，提供：
    - 文本向量化（embed）
    - 文档分块存储（add_chunks）
    - 语义检索（search）
    - 文档向量删除（delete_document）
    """

    def __init__(self, config: dict = None):
        """
        初始化 BGE 模型和 ChromaDB 客户端

        参数:
            config: 配置字典，为 None 时自动从 get_config() 获取
        """
        if config is None:
            config = get_config()
        self.config = config

        # 初始化 ChromaDB 持久化客户端
        chroma_path = config["database"]["chromadb_path"]
        os.makedirs(chroma_path, exist_ok=True)
        self.chroma_client = chromadb.PersistentClient(path=chroma_path)

        # 获取或创建集合（已存在则复用，避免重复创建）
        self.collection = self.chroma_client.get_or_create_collection(
            name="knowledge_chunks",
            metadata={"description": "知识库文档分块向量集合，用于语义检索"},
        )

        # 加载 BGE 模型
        self.model = _get_bge_model()

    def embed(self, texts: list[str]) -> list[list[float]]:
        """
        将文本列表转为向量列表

        参数:
            texts: 待向量化的文本列表

        返回:
            向量列表，每个向量为 float 列表（维度由模型决定，BGE-small-zh 为 512 维）
        """
        if not texts:
            return []

        # BGE 模型对文本进行向量化，normalize_embeddings=True 用于余弦相似度计算
        embeddings = self.model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return embeddings.tolist()

    def add_chunks(self, db: Session, document_id: int, chunks: list[str]) -> list[str]:
        """
        将文本分块向量化后存入 ChromaDB，同时在 SQLite 中记录分块信息

        参数:
            db: 数据库会话
            document_id: 所属文档 ID
            chunks: 文本分块列表

        返回:
            chroma_id 列表
        """
        if not chunks:
            return []

        # 向量化所有分块
        embeddings = self.embed(chunks)

        # 构建 ChromaDB 所需的 ID 和元数据
        chroma_ids = []
        metadatas = []
        for i, chunk_text in enumerate(chunks):
            chroma_id = f"doc_{document_id}_chunk_{i}"
            chroma_ids.append(chroma_id)
            metadatas.append({
                "document_id": document_id,
                "chunk_index": i,
            })

        # 存入 ChromaDB
        self.collection.add(
            ids=chroma_ids,
            embeddings=embeddings,
            documents=chunks,
            metadatas=metadatas,
        )

        # 在 SQLite 中创建 DocumentChunk 记录
        for i, chunk_text in enumerate(chunks):
            chunk_record = DocumentChunk(
                document_id=document_id,
                chunk_index=i,
                content=chunk_text,
                chroma_id=chroma_ids[i],
            )
            db.add(chunk_record)

        # 更新文档的分块数量
        doc = db.query(Document).filter(Document.id == document_id).first()
        if doc:
            doc.chunk_count = doc.chunk_count + len(chunks)

        db.commit()
        return chroma_ids

    def search(
        self, db: Session, query: str, top_k: int = 5, kb_id: int = None
    ) -> list[dict]:
        """
        语义检索：将查询文本向量化后在 ChromaDB 中搜索最相似的分块

        参数:
            db: 数据库会话（用于关联查询文档信息）
            query: 查询文本
            top_k: 返回结果数量
            kb_id: 可选，限定知识库范围

        返回:
            结果列表，每项包含：
            - content: 分块文本内容
            - document_id: 所属文档 ID
            - document_title: 文档标题
            - score: 相似度分数（0~1，越高越相似）
            - chunk_index: 分块序号
            - kb_id: 所属知识库 ID
        """
        if not query.strip():
            return []

        # 向量化查询文本
        query_embedding = self.embed([query])

        # 如果指定了 kb_id 过滤，多取一些结果用于后过滤
        n_results = top_k * 3 if kb_id is not None else top_k

        # 执行向量搜索
        results = self.collection.query(
            query_embeddings=query_embedding,
            n_results=n_results,
        )

        # 解析 ChromaDB 返回结果
        result_list = []
        if results and results.get("ids") and results["ids"][0]:
            for i in range(len(results["ids"][0])):
                chroma_id = results["ids"][0][i]
                doc_id_meta = results["metadatas"][0][i].get("document_id", 0) if results["metadatas"] else 0
                chunk_idx = results["metadatas"][0][i].get("chunk_index", 0) if results["metadatas"] else 0
                content = results["documents"][0][i] if results.get("documents") else ""
                distance = results["distances"][0][i] if results.get("distances") else 0
                # 将余弦距离转换为相似度分数（距离 ∈ [0, 2]，0 表示完全相同）
                score = max(0.0, 1.0 - distance)

                # 从数据库获取文档信息（标题、所属知识库）
                doc = db.query(Document).filter(Document.id == doc_id_meta).first()

                # 如果指定了 kb_id，过滤掉不属于该知识库的结果
                if kb_id is not None and (doc is None or doc.kb_id != kb_id):
                    continue

                # 获取知识库名称
                kb_name = None
                if doc and doc.kb_id:
                    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == doc.kb_id).first()
                    kb_name = kb.name if kb else None

                result_list.append({
                    "content": content,
                    "document_id": doc_id_meta,
                    "document_title": doc.title if doc else "未知文档",
                    "kb_id": doc.kb_id if doc else None,
                    "kb_name": kb_name,
                    "score": round(score, 4),
                    "chunk_index": chunk_idx,
                    "chroma_id": chroma_id,
                })

        # 截取 top_k 条结果返回
        return result_list[:top_k]

    def delete_document(self, db: Session, document_id: int):
        """
        删除某个文档在 ChromaDB 中的所有向量，以及 SQLite 中的分块记录

        参数:
            db: 数据库会话
            document_id: 文档 ID
        """
        # 查找该文档的所有分块记录
        chunks = db.query(DocumentChunk).filter(
            DocumentChunk.document_id == document_id
        ).all()

        if not chunks:
            return

        # 收集所有 chroma_id
        chroma_ids = [chunk.chroma_id for chunk in chunks if chunk.chroma_id]

        # 从 ChromaDB 中删除向量
        if chroma_ids:
            try:
                self.collection.delete(ids=chroma_ids)
            except Exception:
                # ChromaDB 删除失败时仅记录日志，不阻塞数据库操作
                pass

        # 从 SQLite 中删除分块记录
        db.query(DocumentChunk).filter(
            DocumentChunk.document_id == document_id
        ).delete()

        # 重置文档的分块数量
        doc = db.query(Document).filter(Document.id == document_id).first()
        if doc:
            doc.chunk_count = 0

        db.commit()


# 模块级单例（EmbeddingService 实例缓存）
_embedding_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    """
    获取 EmbeddingService 单例

    首次调用时创建实例并缓存，后续调用返回同一实例，
    避免重复加载 BGE 模型和创建 ChromaDB 连接。

    返回:
        EmbeddingService 实例
    """
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
