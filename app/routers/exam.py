"""
考察路由 —— AI 面试考察模块

路由前缀：/exam

提供完整的 AI 考察功能：
- 创建考察会话
- 获取/提交/评判题目
- 结束考察并获取报告
- 历史考察记录
"""

import json
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import PROJECT_ROOT

templates = Jinja2Templates(directory=os.path.join(PROJECT_ROOT, "app", "templates"))

from app.models.database import get_db
from app.models.schema import ExamSession, ExamQuestion
from app.services.exam import ExamService, get_exam_service

# ──────────────────────────────────────────────
# 路由
# ──────────────────────────────────────────────

router = APIRouter()


# ──────────────────────────────────────────────
# 请求模型
# ──────────────────────────────────────────────

class StartExamRequest(BaseModel):
    """开始考察请求"""
    plan_module_id: Optional[int] = Field(default=None, description="关联的计划模块 ID")
    scope_description: Optional[str] = Field(default=None, description="考察范围描述")
    question_count: int = Field(default=5, ge=1, le=20, description="题目数量（1-20）")

    class Config:
        json_schema_extra = {
            "example": {
                "plan_module_id": 1,
                "question_count": 5,
            }
        }


class SubmitAnswerRequest(BaseModel):
    """提交回答请求"""
    question_index: int = Field(..., ge=0, description="题目序号（从0开始）")
    answer: str = Field(..., description="用户回答文本")

    class Config:
        json_schema_extra = {
            "example": {
                "question_index": 0,
                "answer": "数据库索引是一种数据结构...",
            }
        }


# ──────────────────────────────────────────────
# 页面路由
# ──────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
def exam_page(request: Request):
    """
    考察首页 —— 使用 exam.html 模板渲染

    展示考察功能入口和历史记录。
    """
    return templates.TemplateResponse(
        request=request, name="exam.html", context={})


# ──────────────────────────────────────────────
# API 路由
# ──────────────────────────────────────────────

@router.post("/start")
async def start_exam(
    req: StartExamRequest,
    db: Session = Depends(get_db),
    exam_service: ExamService = Depends(get_exam_service),
):
    """
    开始新考察，创建考察会话

    请求体:
        plan_module_id: 可选，关联的学习计划模块 ID
        scope_description: 可选，自由考察范围描述
        question_count: 题目数量（默认5，范围1-20）

    返回:
        dict: 新创建的考察会话信息
    """
    # 至少需要一个范围
    if not req.plan_module_id and not req.scope_description:
        req.scope_description = "综合知识考察"

    session = await exam_service.start_exam(
        plan_module_id=req.plan_module_id,
        scope_description=req.scope_description,
        question_count=req.question_count,
        db=db,
    )
    return {
        "id": session.id,
        "plan_module_id": session.plan_module_id,
        "scope_description": session.scope_description,
        "question_count": session.question_count,
        "status": session.status,
        "created_at": session.created_at.isoformat() if session.created_at else None,
    }


@router.get("/sessions/{session_id}")
def get_session_detail(
    session_id: int,
    db: Session = Depends(get_db),
):
    """
    获取考察会话详情（含题目列表）

    参数:
        session_id: 考察会话 ID

    返回:
        dict: 会话详情及题目列表
    """
    session = db.query(ExamSession).filter(ExamSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="考察会话不存在")

    questions = (
        db.query(ExamQuestion)
        .filter(ExamQuestion.session_id == session_id)
        .order_by(ExamQuestion.question_index)
        .all()
    )

    return {
        "id": session.id,
        "plan_module_id": session.plan_module_id,
        "scope_description": session.scope_description,
        "question_count": session.question_count,
        "status": session.status,
        "score": session.score,
        "feedback": session.feedback,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "finished_at": session.finished_at.isoformat() if session.finished_at else None,
        "questions": [
            {
                "id": q.id,
                "question_index": q.question_index,
                "question_text": q.question_text,
                "user_answer": q.user_answer,
                "ai_evaluation": q.ai_evaluation,
                "score": q.score,
                "model_answer": q.model_answer,
                "extensions": q.extensions,
            }
            for q in questions
        ],
    }


@router.post("/sessions/{session_id}/answer")
async def submit_answer(
    session_id: int,
    req: SubmitAnswerRequest,
    db: Session = Depends(get_db),
    exam_service: ExamService = Depends(get_exam_service),
):
    """
    提交回答 —— 获取 AI 实时评判

    请求体:
        question_index: 题目序号
        answer: 用户回答文本

    返回:
        dict: AI 评判结果，含 score、evaluation、next_action
    """
    try:
        evaluation = await exam_service.evaluate_answer(
            session_id=session_id,
            question_index=req.question_index,
            user_answer=req.answer,
            db=db,
        )
        return evaluation
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"评判失败: {str(e)}")


@router.get("/sessions/{session_id}/next-question")
async def get_next_question(
    session_id: int,
    db: Session = Depends(get_db),
    exam_service: ExamService = Depends(get_exam_service),
):
    """
    获取下一道题目（SSE 流式返回）

    参数:
        session_id: 考察会话 ID

    返回:
        SSE 流: 流式返回题目文本
    """
    async def generate():
        try:
            question = await exam_service.generate_question(
                session_id=session_id,
                db=db,
            )
            # 逐字符发送以模拟流式效果
            for i in range(0, len(question), 5):
                chunk = question[i:i + 5]
                yield f"data: {json.dumps({'type': 'chunk', 'content': chunk}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'content': question}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"

    # 验证会话存在
    session = db.query(ExamSession).filter(ExamSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="考察会话不存在")

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/sessions/{session_id}/finish")
async def finish_exam(
    session_id: int,
    db: Session = Depends(get_db),
    exam_service: ExamService = Depends(get_exam_service),
):
    """
    结束考察，获取总结报告

    参数:
        session_id: 考察会话 ID

    返回:
        dict: 完整考察报告，含总分、逐题详情、薄弱点分析
    """
    try:
        report = await exam_service.finish_exam(
            session_id=session_id,
            db=db,
        )
        return report
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"结束考察失败: {str(e)}")


@router.get("/sessions/{session_id}/export")
def export_exam_report(
    session_id: int,
    db: Session = Depends(get_db),
):
    """
    导出考察报告为 Markdown 文件（可下载）

    参数:
        session_id: 考察会话 ID

    返回:
        StreamingResponse: Markdown 文件下载
    """
    from datetime import datetime
    from urllib.parse import quote

    session = db.query(ExamSession).filter(ExamSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="考察会话不存在")

    questions = (
        db.query(ExamQuestion)
        .filter(ExamQuestion.session_id == session_id)
        .order_by(ExamQuestion.question_index)
        .all()
    )

    # ── 解析 feedback（可能是 AI 返回的 JSON 字符串） ──
    feedback_display = session.feedback or "暂无评价"
    try:
        fb_data = json.loads(feedback_display)
        if isinstance(fb_data, dict):
            # 提取主要评价文本
            feedback_display = fb_data.get("feedback") or fb_data.get("evaluation") or fb_data.get("summary") or session.feedback
            # 如果有薄弱点，追加到评价后面
            weak_pts = fb_data.get("weak_points") or fb_data.get("weaknesses") or []
            if isinstance(weak_pts, list) and weak_pts:
                feedback_display += "\n\n**薄弱环节**：" + "、".join(str(w) for w in weak_pts)
    except (json.JSONDecodeError, TypeError, AttributeError):
        # 不是 JSON，直接使用原文本
        pass

    # 构建 Markdown 报告
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    md = f"""# 📝 AI 考察报告

**考察范围**：{session.scope_description or '综合考察'}
**题目数量**：{session.question_count}
**得分**：{session.score if session.score is not None else '-'} / 100
**生成时间**：{now}

---

## 📊 总体评价

{feedback_display}

---

## 📋 逐题详情

"""

    for q in questions:
        # 评判内容 —— 兼容 JSON 和纯文本两种格式
        eval_text = q.ai_evaluation or ""
        eval_display = eval_text
        try:
            eval_data = json.loads(eval_text) if eval_text else {}
            if isinstance(eval_data, dict):
                eval_display = eval_data.get("evaluation", eval_text)
        except (json.JSONDecodeError, TypeError):
            pass  # 非 JSON，直接使用原文本

        md += f"""### 第 {q.question_index + 1} 题（得分：{q.score if q.score is not None else '未评'}）

**🤖 题目**

{q.question_text}

**📝 你的回答**

{q.user_answer or '（未回答）'}

**📊 AI 评判**

{eval_display or '（未评判）'}

"""

        if q.model_answer:
            md += f"""**✅ 标准答案**

{q.model_answer}

"""

        if q.extensions:
            md += f"""**🔍 知识延伸**

{q.extensions}

"""

        md += "---\n\n"

    md += "\n> 由个人知识库系统 AI 自动生成\n"

    # ── 返回可下载文件 ──
    # HTTP 头部只支持 ASCII，中文文件名需用 RFC 5987 编码
    ascii_filename = f"exam_report_{session.id}_{datetime.now().strftime('%Y%m%d')}.md"
    utf8_filename = f"考察报告_{session.id}_{datetime.now().strftime('%Y%m%d')}.md"
    encoded_filename = quote(utf8_filename, safe="")

    return StreamingResponse(
        iter([md.encode("utf-8")]),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"{ascii_filename}\"; "
                f"filename*=UTF-8''{encoded_filename}"
            ),
        },
    )


@router.get("/history")
def get_exam_history(
    db: Session = Depends(get_db),
):
    """
    获取历史考察记录列表

    返回:
        list[dict]: 考察会话列表，按时间倒序
    """
    sessions = (
        db.query(ExamSession)
        .order_by(ExamSession.created_at.desc())
        .limit(50)
        .all()
    )
    return [
        {
            "id": s.id,
            "plan_module_id": s.plan_module_id,
            "scope_description": s.scope_description,
            "question_count": s.question_count,
            "status": s.status,
            "score": s.score,
            "feedback": s.feedback,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "finished_at": s.finished_at.isoformat() if s.finished_at else None,
        }
        for s in sessions
    ]
