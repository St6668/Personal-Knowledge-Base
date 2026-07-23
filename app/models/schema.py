"""
数据库 ORM 模型定义 —— 核心契约文件

所有 Agent 共享此文件中定义的模型。
所有类名和字段名均附中文注释，字段类型与约束必须精确。
"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Float, DateTime, ForeignKey, UniqueConstraint
)
from sqlalchemy.orm import relationship
from app.models.database import Base


class KnowledgeBase(Base):
    """知识库分组——用户可按主题或项目组织文档"""
    __tablename__ = "knowledge_bases"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    name = Column(String(200), nullable=False, comment="知识库名称")
    description = Column(Text, nullable=True, comment="描述")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")

    # 关系：一个知识库下有多个文档
    documents = relationship("Document", back_populates="knowledge_base", cascade="all, delete-orphan")


class Document(Base):
    """文档/笔记——知识库中的具体条目，可来自上传文件或手动创建"""
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    title = Column(String(500), nullable=False, comment="标题")
    doc_type = Column(String(50), nullable=False, comment="类型：pdf/word/txt/markdown/xmind/note")
    source_path = Column(String(1000), nullable=True, comment="原始文件路径（手动笔记为空）")
    kb_id = Column(Integer, ForeignKey("knowledge_bases.id"), nullable=True, comment="所属知识库")
    chunk_count = Column(Integer, default=0, comment="分块数量")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")

    # 关系
    knowledge_base = relationship("KnowledgeBase", back_populates="documents")
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")
    tags = relationship("DocumentTag", back_populates="document", cascade="all, delete-orphan")


class DocumentChunk(Base):
    """文本分块——文档被切分后的最小检索单元，已向量化存储于 ChromaDB"""
    __tablename__ = "document_chunks"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, comment="所属文档")
    chunk_index = Column(Integer, nullable=False, comment="分块序号（从0开始）")
    content = Column(Text, nullable=False, comment="原文内容")
    chroma_id = Column(String(200), nullable=True, comment="ChromaDB 中的向量 ID（用于关联）")

    # 关系
    document = relationship("Document", back_populates="chunks")


class Tag(Base):
    """标签——用于给文档打标签，方便分类检索"""
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    name = Column(String(100), unique=True, nullable=False, comment="标签名")

    # 关系
    documents = relationship("DocumentTag", back_populates="tag", cascade="all, delete-orphan")


class DocumentTag(Base):
    """文档-标签关联——多对多中间表"""
    __tablename__ = "document_tags"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, comment="文档ID")
    tag_id = Column(Integer, ForeignKey("tags.id"), nullable=False, comment="标签ID")

    # 关系
    document = relationship("Document", back_populates="tags")
    tag = relationship("Tag", back_populates="documents")

    # 联合唯一约束：同一文档不能重复添加同一标签
    __table_args__ = (
        UniqueConstraint("document_id", "tag_id", name="uq_document_tag"),
    )


class Conversation(Base):
    """对话会话——用户与 AI 的一次完整对话"""
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    title = Column(String(500), default="新对话", comment="对话标题")
    mode = Column(String(50), default="kb_qa", comment="模式：kb_qa / free_chat / scope_locked")
    scope_kb_id = Column(Integer, ForeignKey("knowledge_bases.id"), nullable=True, comment="锁定范围的知识库ID")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")

    # 关系
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    """对话消息——单轮对话中的一条消息"""
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False, comment="所属对话")
    role = Column(String(20), nullable=False, comment="角色：user / assistant")
    content = Column(Text, nullable=False, comment="消息内容")
    referenced_docs = Column(Text, nullable=True, comment="引用的文档ID列表（JSON数组字符串）")
    created_at = Column(DateTime, default=datetime.now, comment="时间戳")

    # 关系
    conversation = relationship("Conversation", back_populates="messages")


class StudyPlan(Base):
    """学习计划——AI 生成的系统化学习方案"""
    __tablename__ = "study_plans"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    title = Column(String(500), nullable=False, comment="计划标题")
    scope_description = Column(Text, nullable=True, comment="知识范围描述")
    total_modules = Column(Integer, default=0, comment="模块总数")
    status = Column(String(50), default="in_progress", comment="状态：in_progress / completed")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")

    # 关系：一个学习计划下有多个模块
    modules = relationship("PlanModule", back_populates="study_plan", cascade="all, delete-orphan")


class PlanModule(Base):
    """计划模块——学习计划中的单个学习单元"""
    __tablename__ = "plan_modules"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    plan_id = Column(Integer, ForeignKey("study_plans.id"), nullable=False, comment="所属计划")
    title = Column(String(500), nullable=False, comment="模块标题")
    description = Column(Text, nullable=True, comment="模块描述")
    knowledge_refs = Column(Text, nullable=True, comment="知识点引用（JSON数组）")
    suggested_hours = Column(Float, default=0, comment="建议学习时长（小时）")
    order_index = Column(Integer, nullable=False, comment="序号")
    status = Column(String(50), default="pending", comment="状态：pending / in_progress / completed")

    # 关系
    study_plan = relationship("StudyPlan", back_populates="modules")
    exam_sessions = relationship("ExamSession", back_populates="plan_module", cascade="all, delete-orphan")


class ExamSession(Base):
    """考察会话——一次 AI 出题的测验过程"""
    __tablename__ = "exam_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    plan_module_id = Column(Integer, ForeignKey("plan_modules.id"), nullable=True, comment="关联的计划模块")
    scope_description = Column(Text, nullable=True, comment="考察的知识范围描述")
    question_count = Column(Integer, default=5, comment="题目数量")
    status = Column(String(50), default="in_progress", comment="状态：in_progress / completed / aborted")
    score = Column(Float, nullable=True, comment="总分（AI 评分）")
    feedback = Column(Text, nullable=True, comment="AI 总体评价")
    created_at = Column(DateTime, default=datetime.now, comment="开始时间")
    finished_at = Column(DateTime, nullable=True, comment="结束时间")

    # 关系
    plan_module = relationship("PlanModule", back_populates="exam_sessions")
    questions = relationship("ExamQuestion", back_populates="exam_session", cascade="all, delete-orphan")


class ExamQuestion(Base):
    """考察题目——单道 AI 出的题目及其回答"""
    __tablename__ = "exam_questions"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    session_id = Column(Integer, ForeignKey("exam_sessions.id"), nullable=False, comment="所属考察")
    question_text = Column(Text, nullable=False, comment="AI 出的题目")
    user_answer = Column(Text, nullable=True, comment="用户的回答")
    ai_evaluation = Column(Text, nullable=True, comment="AI 评判结果")
    score = Column(Float, nullable=True, comment="本题得分")
    model_answer = Column(Text, nullable=True, comment="AI 生成的标准答案")
    extensions = Column(Text, nullable=True, comment="AI 生成的知识延伸")
    question_index = Column(Integer, nullable=False, comment="题目序号")

    # 关系
    exam_session = relationship("ExamSession", back_populates="questions")
