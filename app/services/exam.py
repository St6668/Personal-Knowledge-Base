"""
AI 面试考察服务

功能：
- 创建考察会话，根据知识点自动出题
- 实时评判用户回答并给出反馈
- 支持追问机制（最多追问2次）
- 生成完整的考察总结报告（总分、逐题详情、薄弱点分析）
"""

import json
import re
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models.schema import (
    ExamSession,
    ExamQuestion,
    PlanModule,
    Document,
    DocumentChunk,
)
from app.services.chat import AIService, SYSTEM_PROMPT_EXAMINER, get_ai_service

# ──────────────────────────────────────────────
# 尝试导入 EmbeddingService（用于检索考察内容）
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

def _parse_evaluation_json(text: str) -> dict:
    """
    容错解析 AI 返回的评判 JSON

    AI 可能不严格遵守 JSON 格式，此函数处理各种边界情况。

    参数:
        text: AI 返回的原始文本

    返回:
        dict: 解析后的字典，至少包含 score、evaluation、weak_points 键，
              若解析失败则为默认值
    """
    default = {
        "score": 60,
        "evaluation": "AI 评判结果解析失败",
        "weak_points": ["未识别到薄弱点"],
        "next_action": "next_question",
    }

    if not text:
        return default

    cleaned = text.strip()

    # 策略1：查找 {...} JSON 对象
    object_pattern = r"\{[^{}]*\}"
    match = re.search(object_pattern, cleaned, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, dict):
                return {**default, **result}
        except json.JSONDecodeError:
            pass

    # 策略2：尝试修复常见的 JSON 格式问题
    # 修复单引号
    try:
        fixed = re.sub(r"(?<!\\)'", '"', cleaned)
        fixed = re.sub(r"True|true", "true", fixed)
        fixed = re.sub(r"False|false", "false", fixed)
        # 查找 JSON 对象块
        start = fixed.find("{")
        end = fixed.rfind("}")
        if start != -1 and end != -1:
            result = json.loads(fixed[start:end + 1])
            if isinstance(result, dict):
                return {**default, **result}
    except json.JSONDecodeError:
        pass

    # 策略3：用正则提取关键字段
    result = dict(default)
    # 提取 score
    score_match = re.search(r'"score"\s*:\s*(\d+(?:\.\d+)?)', cleaned)
    if score_match:
        result["score"] = float(score_match.group(1))
    # 提取 evaluation
    eval_match = re.search(r'"evaluation"\s*:\s*"([^"]*)"', cleaned, re.DOTALL)
    if eval_match:
        result["evaluation"] = eval_match.group(1)
    # 提取 weak_points
    wp_match = re.search(r'"weak_points"\s*:\s*\[(.*?)\]', cleaned, re.DOTALL)
    if wp_match:
        points_text = wp_match.group(1)
        points = re.findall(r'"([^"]*)"', points_text)
        if points:
            result["weak_points"] = points
    # 提取 next_action
    na_match = re.search(r'"next_action"\s*:\s*"([^"]*)"', cleaned)
    if na_match:
        result["next_action"] = na_match.group(1)

    return result


def _parse_model_answer_json(text: str) -> dict:
    """
    解析 AI 返回的标准答案 JSON（支持内容中的嵌套花括号）

    参数:
        text: AI 返回的原始文本

    返回:
        dict: 至少包含 model_answer、extensions 键
    """
    default = {"model_answer": "", "extensions": ""}

    if not text:
        return default

    cleaned = text.strip()

    # 策略1：尝试直接 json.loads（最可靠）
    try:
        result = json.loads(cleaned)
        if isinstance(result, dict):
            return {**default, **result}
    except json.JSONDecodeError:
        pass

    # 策略2：查找最外层 {...} —— 匹配第一个 { 和最后一个 }
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            result = json.loads(cleaned[start:end + 1])
            if isinstance(result, dict):
                return {**default, **result}
        except json.JSONDecodeError:
            pass

    # 策略3：用正则提取 model_answer 和 extensions 字段值
    ma_match = re.search(r'"model_answer"\s*:\s*"((?:[^"\\]|\\.)*)"', cleaned, re.DOTALL)
    if ma_match:
        default["model_answer"] = ma_match.group(1)

    ext_match = re.search(r'"extensions"\s*:\s*"((?:[^"\\]|\\.)*)"', cleaned, re.DOTALL)
    if ext_match:
        default["extensions"] = ext_match.group(1)

    return default


# ──────────────────────────────────────────────
# 考察服务类
# ──────────────────────────────────────────────

class ExamService:
    """AI 面试考察服务"""

    # 每个知识点最多追问次数
    MAX_FOLLOW_UPS = 2

    def __init__(
        self,
        ai_service: Optional[AIService] = None,
        embedding_service: Optional["EmbeddingService"] = None,
    ):
        """
        初始化 ExamService

        参数:
            ai_service: AIService 实例，若为 None 则使用全局单例
            embedding_service: EmbeddingService 实例，用于知识检索
        """
        self.ai_service = ai_service or get_ai_service()
        self.embedding_service = embedding_service

        if self.embedding_service is None and _embedding_available:
            try:
                self.embedding_service = EmbeddingService()
            except Exception:
                self.embedding_service = None

    async def start_exam(
        self,
        plan_module_id: Optional[int] = None,
        scope_description: Optional[str] = None,
        question_count: int = 5,
        db: Optional[Session] = None,
    ) -> ExamSession:
        """
        创建考察会话

        参数:
            plan_module_id: 关联的学习计划模块 ID
            scope_description: 考察范围描述（若未关联计划模块则使用此描述）
            question_count: 题目数量
            db: 数据库会话

        返回:
            ExamSession: 新创建的考察会话对象
        """
        if db is None:
            raise ValueError("数据库会话 (db) 不能为空")

        # 如果是关联模块的考察，获取模块描述
        if plan_module_id and not scope_description:
            module = db.query(PlanModule).filter(PlanModule.id == plan_module_id).first()
            if module:
                scope_description = (
                    f"模块：{module.title}\n描述：{module.description or '无描述'}"
                )

        session = ExamSession(
            plan_module_id=plan_module_id,
            scope_description=scope_description or "综合考察",
            question_count=question_count,
            status="in_progress",
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        return session

    async def generate_question(
        self,
        session_id: int,
        db: Session,
    ) -> str:
        """
        生成下一道题目

        处理流程：
        1. 获取考察会话信息
        2. 检索考察范围的知识点
        3. 构建面试官提示词 + 已有题目和回答的上下文
        4. 调用 AI 生成新题目
        5. 存入 ExamQuestion 表
        6. 返回题目文本

        参数:
            session_id: 考察会话 ID
            db: 数据库会话

        返回:
            str: AI 生成的题目文本
        """
        # ── 1. 获取会话 ──
        session = db.query(ExamSession).filter(ExamSession.id == session_id).first()
        if not session:
            raise ValueError(f"考察会话 {session_id} 不存在")

        if session.status != "in_progress":
            raise ValueError("考察已结束或已取消")

        # ── 2. 确定下一题序号 ──
        existing_count = (
            db.query(ExamQuestion)
            .filter(ExamQuestion.session_id == session_id)
            .count()
        )
        if existing_count >= session.question_count:
            raise ValueError("已达到预设的题目数量")

        next_index = existing_count  # 从0开始

        # ── 3. 检索考察范围的知识点 ──
        knowledge_context = await self._retrieve_exam_scope(session, db)

        # ── 4. 获取已有题目的上下文 ──
        existing_questions = (
            db.query(ExamQuestion)
            .filter(ExamQuestion.session_id == session_id)
            .order_by(ExamQuestion.question_index)
            .all()
        )

        history_context = ""
        if existing_questions:
            history_context = "\n\n--- 已出题目和回答 ---\n"
            for q in existing_questions:
                history_context += (
                    f"第{q.question_index + 1}题：{q.question_text}\n"
                    f"回答：{q.user_answer or '未回答'}\n"
                    f"评判：{q.ai_evaluation or '未评判'}\n"
                    f"得分：{q.score or '未评分'}\n\n"
                )

        # ── 5. 构建提示词并调用 AI ──
        prompt = (
            f"--- 考察范围 ---\n{knowledge_context}\n\n"
            f"{history_context}"
            f"--- 现在是第 {next_index + 1} 题（共 {session.question_count} 题）---\n"
            f"请出一道考察深度理解的开放式问题。只输出问题文本，不要输出 JSON 或其他格式。"
        )
        messages = [{"role": "user", "content": prompt}]

        question_text = ""
        async for chunk in self.ai_service.chat(
            messages, stream=True, system_prompt=SYSTEM_PROMPT_EXAMINER
        ):
            question_text += chunk

        question_text = question_text.strip()

        # ── 6. 存入数据库 ──
        exam_question = ExamQuestion(
            session_id=session_id,
            question_text=question_text,
            question_index=next_index,
        )
        db.add(exam_question)
        db.commit()

        return question_text

    async def evaluate_answer(
        self,
        session_id: int,
        question_index: int,
        user_answer: str,
        db: Session,
    ) -> dict:
        """
        评判用户回答

        处理流程：
        1. 获取考察会话和目标题目
        2. 调用 AI 评判回答质量
        3. 更新 ExamQuestion 的评判和分数
        4. 返回评判结果

        参数:
            session_id: 考察会话 ID
            question_index: 题目序号（从0开始）
            user_answer: 用户回答文本
            db: 数据库会话

        返回:
            dict: {
                "evaluation": "评判内容",
                "score": 85,
                "next_action": "next_question" | "follow_up" | "finish"
            }
        """
        # ── 1. 获取会话和题目 ──
        session = db.query(ExamSession).filter(ExamSession.id == session_id).first()
        if not session:
            raise ValueError(f"考察会话 {session_id} 不存在")

        question = (
            db.query(ExamQuestion)
            .filter(
                ExamQuestion.session_id == session_id,
                ExamQuestion.question_index == question_index,
            )
            .first()
        )
        if not question:
            raise ValueError(f"题目 {question_index} 不存在")

        # ── 2. 统计对该知识点的追问次数 ──
        # 检查是否为追问（同一 question_index 已有评判记录）
        # 注意：追问会更新同一条 ExamQuestion
        # 我们用 user_answer 的 "previous_evaluations" 计数来判断追问次数
        # 简化设计：每条 ExamQuestion 最多被评判一次（含追问的最终评判）
        # 如果需要追问，在前端重新调用 evaluate_answer 即可

        # ── 3. 检索考察范围 ──
        knowledge_context = await self._retrieve_exam_scope(session, db)

        # ── 4. 构建评判提示词 ──
        # 判断是否是最后一题
        remaining = session.question_count - (question_index + 1)

        prompt = (
            f"--- 考察范围 ---\n{knowledge_context}\n\n"
            f"--- 题目 ---\n{question.question_text}\n\n"
            f"--- 用户回答 ---\n{user_answer}\n\n"
            f"--- 当前进度：第 {question_index + 1}/{session.question_count} 题，剩余 {remaining} 题 ---\n\n"
            "请评判此回答，按以下 JSON 格式输出：\n"
            '{"score": 0-100, "evaluation": "评判内容（包括对/错分析）", '
            '"weak_points": ["薄弱点1", "薄弱点2"], '
            '"next_action": "next_question"}'
        )
        messages = [{"role": "user", "content": prompt}]

        eval_text = ""
        async for chunk in self.ai_service.chat(
            messages, stream=True, system_prompt=SYSTEM_PROMPT_EXAMINER
        ):
            eval_text += chunk

        # ── 5. 解析评判结果 ──
        evaluation = _parse_evaluation_json(eval_text)

        # 如果是最后一题，强制 next_action 为 "finish"
        if remaining <= 0:
            evaluation["next_action"] = "finish"

        # ── 6. 更新数据库 ──
        question.user_answer = user_answer
        question.ai_evaluation = evaluation.get("evaluation", "")
        question.score = evaluation.get("score", 0)
        db.commit()

        return evaluation

    async def finish_exam(
        self,
        session_id: int,
        db: Session,
    ) -> dict:
        """
        结束考察，生成总结报告

        处理流程：
        1. 汇总所有题目和得分
        2. 调用 AI 生成综合评价
        3. 更新 ExamSession 的完成状态
        4. 返回完整报告

        参数:
            session_id: 考察会话 ID
            db: 数据库会话

        返回:
            dict: 完整考察报告，包含：
                - session_id: 会话 ID
                - total_score: 总分（加权平均）
                - question_count: 题目数量
                - answered_count: 已回答数量
                - question_details: 逐题详情列表
                - feedback: AI 总体评价
                - weak_points: 薄弱点汇总
        """
        # ── 1. 获取会话 ──
        session = db.query(ExamSession).filter(ExamSession.id == session_id).first()
        if not session:
            raise ValueError(f"考察会话 {session_id} 不存在")

        # ── 2. 获取所有题目 ──
        questions = (
            db.query(ExamQuestion)
            .filter(ExamQuestion.session_id == session_id)
            .order_by(ExamQuestion.question_index)
            .all()
        )

        # ── 3. 计算基本统计 ──
        answered = [q for q in questions if q.user_answer is not None]
        total_score = 0.0
        for q in questions:
            if q.score is not None:
                total_score += q.score
        if answered:
            total_score = round(total_score / len(answered), 1)

        # ── 4. 生成 AI 综合评价 ──
        questions_summary = "\n".join(
            f"第{q.question_index + 1}题（得分{q.score}）：{q.question_text[:100]}..."
            for q in answered
        )

        FINAL_EVALUATION_PROMPT = (
            "你是一个面试官，负责根据考察记录生成综合评价报告。"
            "请基于考察数据客观评述，指出薄弱点并给予建设性反馈。使用中文。"
        )
        summary_prompt = (
            f"考察范围：{session.scope_description}\n"
            f"题目数量：{session.question_count}\n"
            f"已回答：{len(answered)}\n"
            f"平均分：{total_score}\n\n"
            f"逐题详情：\n{questions_summary}\n\n"
            "请输出 JSON 格式：\n"
            '{"feedback": "综合评价（200字内，用中文）", '
            '"weak_points": ["薄弱点1", "薄弱点2"], "highlights": ["亮点1"]}'
        )
        messages = [{"role": "user", "content": summary_prompt}]

        ai_feedback = ""
        async for chunk in self.ai_service.chat(
            messages, stream=True, system_prompt=FINAL_EVALUATION_PROMPT
        ):
            ai_feedback += chunk

        # 解析 AI 反馈
        feedback_data = _parse_evaluation_json(ai_feedback)
        feedback_text = feedback_data.get("feedback", feedback_data.get("evaluation", "考察完成"))
        weak_points = feedback_data.get("weak_points", [])

        # ── 5. 为每道已答题目生成标准答案和知识延伸 ──
        for q in answered:
            try:
                answer_data = await self._generate_model_answer(
                    question_text=q.question_text,
                    user_answer=q.user_answer or "",
                    scope=session.scope_description or "",
                )
                q.model_answer = answer_data.get("model_answer", "")
                q.extensions = answer_data.get("extensions", "")
            except Exception:
                pass
        db.commit()

        # ── 6. 构建逐题详情（在生成答案之后） ──
        all_weak_points = []
        question_details = []
        for q in questions:
            # 合并薄弱点
            if q.ai_evaluation:
                q_eval = _parse_evaluation_json(q.ai_evaluation)
                wp = q_eval.get("weak_points", [])
                if isinstance(wp, list):
                    all_weak_points.extend(wp)

            question_details.append({
                "index": q.question_index,
                "question": q.question_text,
                "user_answer": q.user_answer or "未回答",
                "evaluation": q.ai_evaluation or "未评判",
                "score": q.score or 0,
                "model_answer": q.model_answer or "",
                "extensions": q.extensions or "",
            })

        all_weak_points = list(set(all_weak_points))

        # ── 7. 更新会话状态 ──
        session.status = "completed"
        session.score = total_score
        session.feedback = feedback_text
        session.finished_at = datetime.now()
        db.commit()

        # ── 8. 返回完整报告 ──
        return {
            "session_id": session_id,
            "total_score": total_score,
            "question_count": session.question_count,
            "answered_count": len(answered),
            "question_details": question_details,
            "feedback": feedback_text,
            "weak_points": all_weak_points or weak_points,
            "finished_at": session.finished_at.isoformat() if session.finished_at else None,
        }

    async def _retrieve_exam_scope(
        self,
        session: ExamSession,
        db: Session,
    ) -> str:
        """
        检索考察范围的知识内容

        优先级：
        1. 模块的 knowledge_refs（学习计划生成时已精准分配的知识点）
        2. 模块描述 + 语义检索（限定同一知识库）

        参数:
            session: 考察会话
            db: 数据库会话

        返回:
            str: 考察范围知识内容文本
        """
        scope_text = session.scope_description or ""

        if session.plan_module_id:
            module = (
                db.query(PlanModule)
                .filter(PlanModule.id == session.plan_module_id)
                .first()
            )
            if not module:
                return scope_text or "综合知识考察"

            # ── 优先使用模块的精准知识点 ──
            if module.knowledge_refs:
                try:
                    kps = json.loads(module.knowledge_refs)
                    if isinstance(kps, list) and len(kps) > 0:
                        kp_text = "\n\n---\n\n".join(
                            f"【知识点 {i + 1}】{kp}"
                            for i, kp in enumerate(kps)
                        )
                        return (
                            f"考察范围：{module.title}\n"
                            f"模块描述：{module.description or '无'}\n\n"
                            f"--- 本模块精准知识点（仅在此范围内出题） ---\n\n"
                            f"{kp_text}"
                        )
                except (json.JSONDecodeError, TypeError):
                    pass

            # ── 回退：模块描述 + kb_id 限定的语义检索 ──
            scope_text = f"模块：{module.title}\n描述：{module.description or ''}"

            if self.embedding_service is not None and module.plan_id:
                try:
                    # 从 study_plan 的 scope_description 推断 kb_id
                    from app.models.schema import StudyPlan
                    plan = db.query(StudyPlan).filter(StudyPlan.id == module.plan_id).first()
                    kb_id = None
                    if plan and plan.scope_description:
                        import re as _re
                        m = _re.search(r'知识库 ID (\d+)', plan.scope_description or '')
                        if m:
                            kb_id = int(m.group(1))

                    results = self.embedding_service.search(
                        db=db,
                        query=f"{module.title} {module.description or ''}",
                        top_k=5,
                        kb_id=kb_id,
                    )
                    chunks = [item.get("content", "") for item in results if item.get("content")]
                    if chunks:
                        scope_text += "\n\n--- 相关知识点片段 ---\n"
                        scope_text += "\n---\n".join(chunks[:5])
                except Exception:
                    pass

        return scope_text or "综合知识考察"

    async def _generate_model_answer(
        self,
        question_text: str,
        user_answer: str,
        scope: str,
    ) -> dict:
        """
        为单道题目生成标准答案和知识延伸

        参数:
            question_text: 题目文本
            user_answer: 用户回答
            scope: 考察范围

        返回:
            dict: {"model_answer": "标准答案", "extensions": "知识延伸"}
        """
        MODEL_ANSWER_PROMPT = (
            "你是一个知识渊博的导师。请为题目提供标准答案和知识延伸。使用中文。"
        )
        prompt = (
            f"考察范围：{scope}\n\n"
            f"题目：{question_text}\n\n"
            f"学生的回答（供参考其理解水平）：{user_answer[:200]}\n\n"
            "请输出 JSON 格式（注意：答案内容中如有代码块请用文字描述代替，避免在 JSON 中使用花括号）：\n"
            '{"model_answer": "标准答案内容", "extensions": "知识延伸内容"}'
        )
        messages = [{"role": "user", "content": prompt}]

        ai_text = ""
        async for chunk in self.ai_service.chat(
            messages, stream=True, system_prompt=MODEL_ANSWER_PROMPT
        ):
            ai_text += chunk

        # 专用解析：直接查找最外层的 JSON 对象
        return _parse_model_answer_json(ai_text)


# ──────────────────────────────────────────────
# 全局单例
# ──────────────────────────────────────────────

_exam_service_instance: Optional[ExamService] = None


def get_exam_service() -> ExamService:
    """
    获取 ExamService 全局单例

    返回:
        ExamService: 考察服务实例
    """
    global _exam_service_instance
    if _exam_service_instance is None:
        _exam_service_instance = ExamService()
    return _exam_service_instance
