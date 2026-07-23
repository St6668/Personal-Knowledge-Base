"""
学习计划生成服务

功能：
- 根据知识库知识点自动生成结构化学习计划
- 将计划拆分为多个模块（章节），按从易到难排序
- 支持按知识库和标签筛选知识范围
- 容错解析 AI 返回的 JSON
"""

import json
import re
from typing import Optional

from sqlalchemy.orm import Session

from app.models.schema import StudyPlan, PlanModule, Document, DocumentChunk
from app.services.chat import AIService, SYSTEM_PROMPT_PLAN_GENERATION, get_ai_service

# ──────────────────────────────────────────────
# 尝试导入 EmbeddingService（用于检索知识点）
# ──────────────────────────────────────────────
try:
    from app.services.embedding import EmbeddingService
    _embedding_available = True
except ImportError:
    _embedding_available = False
    EmbeddingService = None  # type: ignore


# ──────────────────────────────────────────────
# 容错 JSON 解析工具
# ──────────────────────────────────────────────

def _parse_json_safely(text: str) -> Optional[list]:
    """
    容错解析 AI 返回的 JSON 数组

    AI 可能在 JSON 前后附加说明文字或使用不规范的格式，
    此函数尝试多种策略提取并解析 JSON。

    参数:
        text: AI 返回的原始文本

    返回:
        Optional[list]: 解析成功返回列表，失败返回 None
    """
    if not text:
        return None

    # 策略1：查找 JSON 数组块 [...]
    array_pattern = r"\[\s*\{.*?\}\s*\]"
    matches = re.findall(array_pattern, text, re.DOTALL)
    for match in matches:
        try:
            result = json.loads(match)
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            continue

    # 策略2：提取 { ... } 对象，逐个解析后组装为数组
    items = []
    object_pattern = r"\{[^{}]*\}"
    obj_matches = re.findall(object_pattern, text, re.DOTALL)
    for obj_str in obj_matches:
        try:
            # 尝试修复常见格式问题
            fixed = obj_str
            # 修复单引号
            fixed = re.sub(r"(?<!\\)'", '"', fixed)
            item = json.loads(fixed)
            if isinstance(item, dict) and "title" in item:
                items.append(item)
        except json.JSONDecodeError:
            continue

    if items:
        return items

    # 策略3：去除首尾空白和非 JSON 前缀/后缀后再尝试
    try:
        # 查找第一个 [ 和最后一个 ]
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and end > start:
            json_block = text[start:end + 1]
            result = json.loads(json_block)
            if isinstance(result, list):
                return result
    except json.JSONDecodeError:
        pass

    return None


# ──────────────────────────────────────────────
# 学习计划服务类
# ──────────────────────────────────────────────

class PlanService:
    """学习计划生成服务"""

    def __init__(
        self,
        ai_service: Optional[AIService] = None,
        embedding_service: Optional["EmbeddingService"] = None,
    ):
        """
        初始化 PlanService

        参数:
            ai_service: AIService 实例，若为 None 则使用全局单例
            embedding_service: EmbeddingService 实例，用于知识检索
        """
        self.ai_service = ai_service or get_ai_service()
        self.embedding_service = embedding_service

        # 如果未传入 embedding_service，尝试自动初始化
        if self.embedding_service is None and _embedding_available:
            try:
                self.embedding_service = EmbeddingService()
            except Exception:
                self.embedding_service = None

    async def generate_plan(
        self,
        kb_id: int,
        tag_ids: Optional[list[int]] = None,
        db: Optional[Session] = None,
    ) -> StudyPlan:
        """
        生成学习计划

        处理流程：
        1. 根据知识范围和标签筛选知识点
        2. 收集所有相关文档的文本摘要
        3. 调用 AI 根据知识点生成结构化学习计划（JSON）
        4. 容错解析 JSON，写入 StudyPlan + PlanModule 表
        5. 返回完整的 StudyPlan 对象

        参数:
            kb_id: 知识库 ID
            tag_ids: 可选的标签 ID 列表，用于进一步筛选知识点
            db: 数据库会话

        返回:
            StudyPlan: 生成的学习计划对象（含模块列表）
        """
        if db is None:
            raise ValueError("数据库会话 (db) 不能为空")

        # ── 1. 收集知识点 ──
        knowledge_points = self._collect_knowledge_points(db, kb_id, tag_ids)

        if not knowledge_points:
            raise ValueError("未找到相关知识内容，无法生成学习计划")

        # ── 2. 构建提示词并调用 AI ──
        knowledge_text = "\n\n".join(
            f"### 知识点 {i + 1}\n{kp}"
            for i, kp in enumerate(knowledge_points[:30])  # 限制数量避免超出 token 限制
        )

        prompt = (
            f"以下是要学习的知识点内容（共 {len(knowledge_points)} 个知识片段）：\n\n"
            f"{knowledge_text}\n\n"
            "请仔细阅读以上全部内容，从中提炼出至少 4-8 个独立的学习模块。"
            "每个模块聚焦一个具体的主题，覆盖不同方面的知识。"
            "绝对不要将全部内容合并到一个模块中。"
        )
        messages = [{"role": "user", "content": prompt}]

        ai_response = ""
        async for chunk in self.ai_service.chat(
            messages, stream=True, system_prompt=SYSTEM_PROMPT_PLAN_GENERATION
        ):
            ai_response += chunk

        # ── 3. 解析 AI 返回的 JSON ──
        modules_data = _parse_json_safely(ai_response)

        if not modules_data:
            raise ValueError(f"AI 返回的学习计划无法解析。原始响应: {ai_response[:200]}...")

        # ── 4. 写入数据库 ──
        # 生成计划标题：取第一个模块标题或使用默认
        plan_title = (
            modules_data[0].get("title", "学习计划")
            if modules_data
            else "学习计划"
        )
        # 补充描述
        scope_desc = f"知识库 ID {kb_id}"
        if tag_ids:
            scope_desc += f"，标签 IDs: {tag_ids}"

        study_plan = StudyPlan(
            title=plan_title,
            scope_description=scope_desc,
            total_modules=len(modules_data),
            status="in_progress",
        )
        db.add(study_plan)
        db.flush()  # 获取 plan.id

        for index, module_data in enumerate(modules_data):
            # 将 knowledge_refs 编号映射为实际知识点文本
            refs_texts = []
            raw_refs = module_data.get("knowledge_refs", [])
            if isinstance(raw_refs, list):
                for ref_idx in raw_refs:
                    try:
                        # AI 返回的编号从 1 开始，转换为 0-based 索引
                        kp_index = int(ref_idx) - 1
                        if 0 <= kp_index < len(knowledge_points):
                            refs_texts.append(knowledge_points[kp_index])
                    except (ValueError, TypeError):
                        continue
            knowledge_refs_json = json.dumps(refs_texts, ensure_ascii=False) if refs_texts else None

            module = PlanModule(
                plan_id=study_plan.id,
                title=module_data.get("title", f"模块 {index + 1}"),
                description=module_data.get("description", ""),
                knowledge_refs=knowledge_refs_json,
                suggested_hours=float(module_data.get("hours", 1.0)),
                order_index=index,
                status="pending",
            )
            db.add(module)

        db.commit()
        db.refresh(study_plan)
        return study_plan

    def _collect_knowledge_points(
        self,
        db: Session,
        kb_id: int,
        tag_ids: Optional[list[int]] = None,
    ) -> list[str]:
        """
        收集指定知识库中的知识点文本

        优先从数据库按文档顺序查询分块，确保知识点覆盖知识库全貌，
        避免语义检索只返回相似主题的局限。若 DB 查询无结果，
        则回退到 EmbeddingService 语义检索。

        参数:
            db: 数据库会话
            kb_id: 知识库 ID
            tag_ids: 可选的标签筛选

        返回:
            list[str]: 知识点文本列表
        """
        knowledge_points = []

        # 主方案：按文档顺序查询分块，保证知识点多样性
        query = (
            db.query(DocumentChunk)
            .join(Document, DocumentChunk.document_id == Document.id)
            .filter(Document.kb_id == kb_id)
            .order_by(DocumentChunk.chunk_index)
            .limit(30)
        )
        chunks = query.all()
        for chunk in chunks:
            if chunk.content and len(chunk.content) > 20:
                # 对超大块进行二次拆分（兼容旧数据中未正确分块的情况）
                if len(chunk.content) > 800:
                    sub_chunks = self._split_large_chunk(chunk.content)
                    knowledge_points.extend(sub_chunks)
                else:
                    knowledge_points.append(chunk.content)

        # 若知识点过多，均匀采样以避免 token 溢出，同时保持覆盖广度
        max_kps = 25
        if len(knowledge_points) > max_kps:
            step = len(knowledge_points) / max_kps
            knowledge_points = [
                knowledge_points[int(i * step)]
                for i in range(max_kps)
            ]

        if knowledge_points:
            return knowledge_points

        # 后备方案：EmbeddingService 语义检索
        if self.embedding_service is not None:
            try:
                results = self.embedding_service.search(
                    db=db,
                    query="知识点 学习内容 概念 定义 原理",
                    top_k=20,
                    kb_id=kb_id,
                )
                for item in results:
                    content = item.get("content", "")
                    if content and len(content) > 20:
                        knowledge_points.append(content)
                if knowledge_points:
                    return knowledge_points
            except Exception:
                pass

        return knowledge_points

    @staticmethod
    def _split_large_chunk(text: str, max_size: int = 500, min_size: int = 30) -> list[str]:
        """
        将超大文本块二次拆分为更小的知识点片段

        用于兼容旧数据中未正确分块的情况（整个文档存为一个块）。
        按段落和句子边界切分，避免在词语中间截断。

        参数:
            text: 原始大块文本
            max_size: 每个子块的最大字符数（默认 500）
            min_size: 每个子块的最小字符数（默认 30），过短的碎片会被合并或丢弃

        返回:
            list[str]: 拆分后的子块列表
        """
        import re

        # 先按段落切分
        paragraphs = re.split(r'\n\s*\n', text.strip())
        result = []

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            if len(para) <= max_size:
                if len(para) >= min_size:
                    result.append(para)
                continue

            # 按句子切分长段落
            sentences = re.split(r'(?<=[。！？!?.\n])', para)
            current = ""
            for sent in sentences:
                sent = sent.strip()
                if not sent:
                    continue
                if len(current) + len(sent) <= max_size:
                    current = current + "\n" + sent if current else sent
                else:
                    if current and len(current) >= min_size:
                        result.append(current)
                    current = sent
            if current and len(current) >= min_size:
                result.append(current)

        return result


# ──────────────────────────────────────────────
# 全局单例
# ──────────────────────────────────────────────

_plan_service_instance: Optional[PlanService] = None


def get_plan_service() -> PlanService:
    """
    获取 PlanService 全局单例

    返回:
        PlanService: 学习计划服务实例
    """
    global _plan_service_instance
    if _plan_service_instance is None:
        _plan_service_instance = PlanService()
    return _plan_service_instance
