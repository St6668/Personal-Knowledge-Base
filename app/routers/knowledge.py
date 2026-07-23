"""
知识管理 API 路由

提供知识库的 CRUD、文档上传与解析、语义检索、标签管理等功能。
所有接口前缀：/knowledge（在 main.py 中通过 prefix="/knowledge" 设置）

依赖：
- app.models.schema（ORM 模型）
- app.models.database（get_db 依赖注入）
- app.services.document（文档解析、文本分块）
- app.services.embedding（BGE Embedding + ChromaDB）
"""

import os
import shutil
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.config import get_config, PROJECT_ROOT
from app.models.database import get_db
from app.models.schema import (
    Document,
    DocumentChunk,
    DocumentTag,
    KnowledgeBase,
    Tag,
)
from app.services.document import DocumentParser, TextChunker
from app.services.embedding import EmbeddingService, get_embedding_service

# Jinja2 模板引擎
templates = Jinja2Templates(directory=os.path.join(PROJECT_ROOT, "app", "templates"))

router = APIRouter()


# ══════════════════════════════════════════════════════════════════
# Pydantic 响应模型
# ══════════════════════════════════════════════════════════════════

class KbResponse(BaseModel):
    """知识库响应"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str] = None
    created_at: datetime
    document_count: int = 0


class DocumentResponse(BaseModel):
    """文档概要响应"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    doc_type: str
    source_path: Optional[str] = None
    kb_id: Optional[int] = None
    chunk_count: int = 0
    created_at: datetime
    tags: list[str] = []


class ChunkItem(BaseModel):
    """分块内容项"""
    id: int
    chunk_index: int
    content: str


class DocumentDetailResponse(BaseModel):
    """文档详情响应（含分块列表）"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    doc_type: str
    source_path: Optional[str] = None
    kb_id: Optional[int] = None
    chunk_count: int = 0
    created_at: datetime
    tags: list[str] = []
    chunks: list[ChunkItem] = []


class SearchResult(BaseModel):
    """搜索结果项"""
    content: str
    document_id: int
    document_title: str
    score: float
    chunk_index: int
    kb_id: Optional[int] = None


class TagResponse(BaseModel):
    """标签响应"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class KnowledgeHomeResponse(BaseModel):
    """知识库首页响应"""
    knowledge_bases: list[KbResponse]
    total_documents: int


# ══════════════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════════════

def _get_file_type(filename: str) -> str:
    """
    根据文件扩展名判断文档类型

    参数:
        filename: 文件名（含扩展名）

    返回:
        内部文件类型标识（pdf / word / txt / markdown / xmind）
    """
    ext = os.path.splitext(filename)[1].lower()
    type_map = {
        ".pdf": "pdf",
        ".docx": "word",
        ".doc": "word",
        ".txt": "txt",
        ".md": "markdown",
        ".markdown": "markdown",
        ".xmind": "xmind",
    }
    return type_map.get(ext, "txt")


def _get_doc_type_for_db(file_type: str) -> str:
    """
    将内部文件类型转为数据库存储的标准类型名

    参数:
        file_type: 内部文件类型标识

    返回:
        数据库 doc_type 字段值
    """
    type_map = {
        "pdf": "pdf",
        "word": "word",
        "docx": "word",
        "txt": "txt",
        "text": "txt",
        "markdown": "markdown",
        "md": "markdown",
        "xmind": "xmind",
    }
    return type_map.get(file_type, "txt")


def _process_tags(db: Session, document_id: int, tags_str: Optional[str]) -> list[str]:
    """
    解析标签字符串，创建 Tag 记录和 DocumentTag 关联

    参数:
        db: 数据库会话
        document_id: 文档 ID
        tags_str: 逗号分隔的标签字符串（如 "Python, FastAPI, 后端"）

    返回:
        标签名称列表
    """
    if not tags_str:
        return []

    tag_names = [t.strip() for t in tags_str.split(",") if t.strip()]
    result_tags = []

    for tag_name in tag_names:
        # 查找已有标签，不存在则创建
        tag = db.query(Tag).filter(Tag.name == tag_name).first()
        if not tag:
            tag = Tag(name=tag_name)
            db.add(tag)
            db.flush()  # 获取 tag.id

        # 创建文档-标签关联（含去重检查）
        existing = db.query(DocumentTag).filter(
            DocumentTag.document_id == document_id,
            DocumentTag.tag_id == tag.id,
        ).first()
        if not existing:
            doc_tag = DocumentTag(document_id=document_id, tag_id=tag.id)
            db.add(doc_tag)

        result_tags.append(tag_name)

    db.commit()
    return result_tags


def _get_tags_for_document(db: Session, document_id: int) -> list[str]:
    """
    获取文档的所有标签名称

    参数:
        db: 数据库会话
        document_id: 文档 ID

    返回:
        标签名称列表
    """
    doc_tags = db.query(DocumentTag).filter(DocumentTag.document_id == document_id).all()
    if not doc_tags:
        return []
    tag_ids = [dt.tag_id for dt in doc_tags]
    tags = db.query(Tag).filter(Tag.id.in_(tag_ids)).all()
    return [t.name for t in tags]


# ══════════════════════════════════════════════════════════════════
# 知识库首页
# ══════════════════════════════════════════════════════════════════

@router.get("/", response_class=HTMLResponse)
def knowledge_home(request: Request, db: Session = Depends(get_db)):
    """
    知识库首页：渲染知识管理页面

    列出所有知识库及其文档，支持搜索和筛选。
    """
    kbs = db.query(KnowledgeBase).order_by(KnowledgeBase.created_at.desc()).all()

    kb_list = []
    total_docs = 0
    for kb in kbs:
        doc_count = db.query(Document).filter(Document.kb_id == kb.id).count()
        total_docs += doc_count
        kb_list.append({
            "id": kb.id,
            "name": kb.name,
            "description": kb.description,
            "created_at": kb.created_at,
            "document_count": doc_count,
        })

    # 获取最近文档
    recent_docs = db.query(Document).order_by(Document.created_at.desc()).limit(20).all()
    doc_list = []
    for doc in recent_docs:
        doc_list.append({
            "id": doc.id,
            "title": doc.title,
            "doc_type": doc.doc_type,
            "kb_id": doc.kb_id,
            "chunk_count": doc.chunk_count,
            "created_at": doc.created_at,
        })

    return templates.TemplateResponse(
        request=request, name="knowledge.html", context={
        "knowledge_bases": kb_list,
        "total_documents": total_docs,
        "documents": doc_list,
    })


# ══════════════════════════════════════════════════════════════════
# 知识库 CRUD
# ══════════════════════════════════════════════════════════════════

@router.get("/kb", response_model=list[KbResponse])
def list_knowledge_bases(db: Session = Depends(get_db)):
    """
    获取所有知识库列表（JSON）

    按创建时间倒序排列，包含每个知识库的文档数量。
    """
    kbs = db.query(KnowledgeBase).order_by(KnowledgeBase.created_at.desc()).all()
    result = []
    for kb in kbs:
        doc_count = db.query(Document).filter(Document.kb_id == kb.id).count()
        result.append(KbResponse(
            id=kb.id,
            name=kb.name,
            description=kb.description,
            created_at=kb.created_at,
            document_count=doc_count,
        ))
    return result


@router.post("/kb", response_model=KbResponse)
def create_knowledge_base(
    name: str = Form(..., description="知识库名称"),
    description: Optional[str] = Form(None, description="知识库描述"),
    db: Session = Depends(get_db),
):
    """
    创建新知识库

    参数（表单）：
    - name: 知识库名称（必填）
    - description: 描述（可选）
    """
    kb = KnowledgeBase(name=name, description=description)
    db.add(kb)
    db.commit()
    db.refresh(kb)
    return KbResponse(
        id=kb.id,
        name=kb.name,
        description=kb.description,
        created_at=kb.created_at,
        document_count=0,
    )


@router.delete("/kb/{kb_id}")
def delete_knowledge_base(kb_id: int, db: Session = Depends(get_db)):
    """
    删除知识库及其下所有文档

    同时清理：
    - ChromaDB 中的向量数据
    - SQLite 中的分块记录和文档记录
    - 上传目录中的源文件
    """
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")

    # 收集所有文档信息（用于后续清理）
    docs = db.query(Document).filter(Document.kb_id == kb_id).all()

    # 删除每个文档的 ChromaDB 向量和分块记录
    embedding_service = get_embedding_service()
    for doc in docs:
        # 删除 ChromaDB 向量 + SQLite 分块记录
        embedding_service.delete_document(db, doc.id)
        # 清理上传的源文件
        if doc.source_path and os.path.exists(doc.source_path):
            try:
                os.remove(doc.source_path)
            except OSError:
                pass

    # 查询并删除所有与这些文档关联的 DocumentTag
    doc_ids = [d.id for d in docs]
    if doc_ids:
        db.query(DocumentTag).filter(DocumentTag.document_id.in_(doc_ids)).delete()

    # 查询并删除所有文档（分块已在 delete_document 中删除）
    db.query(Document).filter(Document.kb_id == kb_id).delete()

    # 删除知识库
    kb_name = kb.name
    db.delete(kb)
    db.commit()

    return {"message": f"知识库 '{kb_name}' 及其所有文档已删除"}


# ══════════════════════════════════════════════════════════════════
# 文档列表（按知识库筛选）
# ══════════════════════════════════════════════════════════════════

@router.get("/documents", response_model=list[DocumentResponse])
def list_documents(
    kb_id: Optional[int] = Query(None, description="知识库 ID，不传则返回全部"),
    db: Session = Depends(get_db),
):
    """
    获取文档列表（支持按知识库筛选）

    参数：
    - kb_id: 可选，知识库 ID。不传则返回所有文档。
    """
    query = db.query(Document)
    if kb_id is not None:
        query = query.filter(Document.kb_id == kb_id)
    docs = query.order_by(Document.created_at.desc()).all()

    # 手动构建响应对象，避免 Pydantic 从 ORM 对象中读取 tags 关系时触发懒加载
    result = []
    for doc in docs:
        result.append(DocumentResponse(
            id=doc.id,
            title=doc.title,
            doc_type=doc.doc_type,
            source_path=doc.source_path,
            kb_id=doc.kb_id,
            chunk_count=doc.chunk_count,
            created_at=doc.created_at,
            tags=[],  # 列表接口不加载标签详情
        ))
    return result


# ══════════════════════════════════════════════════════════════════
# 文档上传
# ══════════════════════════════════════════════════════════════════

@router.post("/upload", response_model=DocumentResponse)
async def upload_document(
    file: UploadFile = File(..., description="上传的文件"),
    kb_id: int = Form(..., description="目标知识库 ID"),
    tags: Optional[str] = Form(None, description="标签，逗号分隔"),
    db: Session = Depends(get_db),
):
    """
    上传文档并自动解析、分块、向量化

    处理流程：
    1. 验证知识库存在性
    2. 保存文件到 uploads/ 目录
    3. 根据文件类型解析文本内容
    4. 文本分块（500 字/块，50 字重叠）
    5. BGE Embedding 向量化并存入 ChromaDB
    6. 记录文档元数据和分块信息到 SQLite
    7. 处理标签关联

    参数（multipart/form-data）：
    - file: 上传的文件（支持 pdf/docx/txt/md/xmind）
    - kb_id: 目标知识库 ID
    - tags: 可选，逗号分隔的标签
    """
    # 验证知识库存在
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")

    # 判断文件类型
    file_type = _get_file_type(file.filename)

    # 保存文件到 uploads/ 目录（UUID 命名避免冲突）
    upload_dir = os.path.join(PROJECT_ROOT, "uploads")
    os.makedirs(upload_dir, exist_ok=True)

    ext = os.path.splitext(file.filename)[1]
    unique_name = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(upload_dir, unique_name)

    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    try:
        # 解析文档文本
        raw_text = DocumentParser.parse(file_path, file_type)

        if not raw_text or not raw_text.strip():
            # 清理空文件
            if os.path.exists(file_path):
                os.remove(file_path)
            raise HTTPException(status_code=400, detail="文档内容为空，无法解析")

        # 文本分块：按段落/句子切分为语义块，便于向量检索和知识点提取
        chunks = TextChunker.chunk(raw_text, chunk_size=500, overlap=50)
        if not chunks:
            chunks = [raw_text.strip()]  # 兜底：极短文本不拆分

        if not chunks:
            if os.path.exists(file_path):
                os.remove(file_path)
            raise HTTPException(status_code=400, detail="文档内容无法分块，可能过短")

        # 创建文档记录（标题使用不含扩展名的原始文件名）
        doc_type = _get_doc_type_for_db(file_type)
        title = os.path.splitext(file.filename)[0]

        doc = Document(
            title=title,
            doc_type=doc_type,
            source_path=file_path,
            kb_id=kb_id,
        )
        db.add(doc)
        db.flush()  # 获取 doc.id 用于后续操作

        # 向量化并存储分块到 ChromaDB
        embedding_service = get_embedding_service()
        embedding_service.add_chunks(db, doc.id, chunks)

        # 处理标签
        tag_list = _process_tags(db, doc.id, tags)

        db.commit()
        db.refresh(doc)

        return DocumentResponse(
            id=doc.id,
            title=doc.title,
            doc_type=doc.doc_type,
            source_path=doc.source_path,
            kb_id=doc.kb_id,
            chunk_count=doc.chunk_count,
            created_at=doc.created_at,
            tags=tag_list,
        )

    except HTTPException:
        raise
    except Exception as e:
        # 发生异常时清理已保存的文件
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=500, detail=f"文档处理失败: {str(e)}")


# ══════════════════════════════════════════════════════════════════
# 笔记创建
# ══════════════════════════════════════════════════════════════════

@router.post("/note", response_model=DocumentResponse)
def create_note(
    title: str = Form(..., description="笔记标题"),
    content: str = Form(..., description="笔记内容（支持 Markdown）"),
    kb_id: int = Form(..., description="目标知识库 ID"),
    tags: Optional[str] = Form(None, description="标签，逗号分隔"),
    db: Session = Depends(get_db),
):
    """
    手动创建文本笔记

    处理流程：
    1. 验证知识库存在性
    2. 文本内容分块（500 字/块，50 字重叠）
    3. BGE Embedding 向量化并存入 ChromaDB
    4. 记录文档元数据和分块信息到 SQLite
    5. 处理标签关联

    参数（表单）：
    - title: 笔记标题（必填）
    - content: 笔记正文，支持 Markdown 格式（必填）
    - kb_id: 目标知识库 ID（必填）
    - tags: 逗号分隔的标签（可选）
    """
    # 验证知识库存在
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")

    if not content or not content.strip():
        raise HTTPException(status_code=400, detail="笔记内容不能为空")

    # 文本分块：按段落/句子切分为语义块
    chunks = TextChunker.chunk(content, chunk_size=500, overlap=50)
    if not chunks:
        chunks = [content.strip()]  # 兜底：极短文本不拆分

    # 创建文档记录（doc_type 为 "note"，source_path 为空）
    doc = Document(
        title=title,
        doc_type="note",
        source_path=None,
        kb_id=kb_id,
    )
    db.add(doc)
    db.flush()  # 获取 doc.id

    # 向量化并存储分块
    embedding_service = get_embedding_service()
    embedding_service.add_chunks(db, doc.id, chunks)

    # 处理标签
    tag_list = _process_tags(db, doc.id, tags)

    db.commit()
    db.refresh(doc)

    return DocumentResponse(
        id=doc.id,
        title=doc.title,
        doc_type=doc.doc_type,
        source_path=doc.source_path,
        kb_id=doc.kb_id,
        chunk_count=doc.chunk_count,
        created_at=doc.created_at,
        tags=tag_list,
    )


# ══════════════════════════════════════════════════════════════════
# 文档操作
# ══════════════════════════════════════════════════════════════════

@router.get("/document/{doc_id}", response_model=DocumentDetailResponse)
def get_document(doc_id: int, db: Session = Depends(get_db)):
    """
    查看文档详情及其所有分块内容

    返回文档的完整信息，包括所有分块（按 chunk_index 排序）和标签列表。

    参数:
    - doc_id: 文档 ID
    """
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    # 获取标签
    tag_names = _get_tags_for_document(db, doc_id)

    # 获取分块（按序号排序）
    chunks = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id == doc_id)
        .order_by(DocumentChunk.chunk_index)
        .all()
    )

    chunk_list = [
        ChunkItem(id=c.id, chunk_index=c.chunk_index, content=c.content)
        for c in chunks
    ]

    return DocumentDetailResponse(
        id=doc.id,
        title=doc.title,
        doc_type=doc.doc_type,
        source_path=doc.source_path,
        kb_id=doc.kb_id,
        chunk_count=doc.chunk_count,
        created_at=doc.created_at,
        tags=tag_names,
        chunks=chunk_list,
    )


@router.delete("/document/{doc_id}")
def delete_document(doc_id: int, db: Session = Depends(get_db)):
    """
    删除文档及其所有关联数据

    同时清理：
    - ChromaDB 中的向量数据
    - SQLite 中的分块记录
    - SQLite 中的标签关联
    - uploads/ 目录中的源文件（如有）

    参数:
    - doc_id: 文档 ID
    """
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    doc_title = doc.title
    source_path = doc.source_path

    # 删除 ChromaDB 向量和 SQLite 分块记录
    embedding_service = get_embedding_service()
    embedding_service.delete_document(db, doc_id)

    # 删除标签关联
    db.query(DocumentTag).filter(DocumentTag.document_id == doc_id).delete()

    # 删除文档记录
    db.delete(doc)
    db.commit()

    # 清理上传的源文件
    if source_path and os.path.exists(source_path):
        try:
            os.remove(source_path)
        except OSError:
            pass

    return {"message": f"文档 '{doc_title}' 已删除"}


# ══════════════════════════════════════════════════════════════════
# 语义检索
# ══════════════════════════════════════════════════════════════════

@router.get("/search", response_model=list[SearchResult])
def search_knowledge(
    q: str = Query(..., description="搜索查询文本"),
    kb_id: Optional[int] = Query(None, description="限定知识库 ID"),
    top_k: int = Query(5, ge=1, le=50, description="返回结果数量"),
    db: Session = Depends(get_db),
):
    """
    语义搜索知识库中的文档内容

    使用 BGE Embedding 将查询文本向量化，在 ChromaDB 中进行余弦相似度检索，
    返回最相关的 top_k 个结果。可选通过 kb_id 限定搜索范围。

    查询参数:
    - q: 搜索关键词或查询文本（必填）
    - kb_id: 限定搜索的知识库 ID（可选，不传则全局搜索）
    - top_k: 返回结果数，1~50，默认 5
    """
    if not q.strip():
        raise HTTPException(status_code=400, detail="搜索关键词不能为空")

    embedding_service = get_embedding_service()
    results = embedding_service.search(db, q, top_k=top_k, kb_id=kb_id)

    return [
        SearchResult(
            content=r["content"],
            document_id=r["document_id"],
            document_title=r["document_title"],
            score=r["score"],
            chunk_index=r["chunk_index"],
            kb_id=r["kb_id"],
        )
        for r in results
    ]


# ══════════════════════════════════════════════════════════════════
# 标签管理
# ══════════════════════════════════════════════════════════════════

@router.get("/tags", response_model=list[TagResponse])
def list_tags(db: Session = Depends(get_db)):
    """
    获取所有标签列表

    按名称字母顺序排列。
    """
    tags = db.query(Tag).order_by(Tag.name).all()
    return [TagResponse(id=t.id, name=t.name) for t in tags]


@router.post("/tags", response_model=TagResponse)
def create_tag(
    name: str = Form(..., description="标签名称"),
    db: Session = Depends(get_db),
):
    """
    创建新标签

    参数（表单）：
    - name: 标签名称（必填，不可重复）
    """
    existing = db.query(Tag).filter(Tag.name == name).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"标签 '{name}' 已存在")

    tag = Tag(name=name)
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return TagResponse(id=tag.id, name=tag.name)
