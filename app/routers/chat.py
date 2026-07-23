"""
对话路由 —— AI 对话功能模块

路由前缀：/chat

提供完整的对话管理 API：
- 获取/创建/删除对话
- 发送消息（SSE 流式返回）
- 查看对话历史消息
"""

import json
import os
import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from app.config import PROJECT_ROOT

templates = Jinja2Templates(directory=os.path.join(PROJECT_ROOT, "app", "templates"))
from sqlalchemy.orm import Session

from app.models.database import get_db
from app.models.schema import Conversation, Message
from app.services.chat import AIService, get_ai_service

# ──────────────────────────────────────────────
# 路由
# ──────────────────────────────────────────────

router = APIRouter()


# ──────────────────────────────────────────────
# 请求模型
# ──────────────────────────────────────────────

class CreateConversationRequest(BaseModel):
    """创建对话请求"""
    mode: str = Field(default="kb_qa", description="对话模式：kb_qa / free_chat / scope_locked")
    kb_id: Optional[int] = Field(default=None, description="锁定范围的知识库 ID（scope_locked 模式必填）")
    scope_description: Optional[str] = Field(default=None, description="知识范围描述（可选）")

    class Config:
        json_schema_extra = {
            "example": {
                "mode": "kb_qa",
                "kb_id": 1,
                "scope_description": None,
            }
        }


class SendMessageRequest(BaseModel):
    """发送消息请求"""
    content: str = Field(..., description="消息内容")

    class Config:
        json_schema_extra = {
            "example": {"content": "请介绍一下数据库索引的原理"}
        }


# ──────────────────────────────────────────────
# 页面路由
# ──────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
def chat_page(request: Request):
    """
    对话页面 —— 使用 chat.html 模板渲染

    列出所有历史对话，支持新建、切换和删除。
    """
    db = next(get_db())
    try:
        conversations = (
            db.query(Conversation)
            .order_by(Conversation.created_at.desc())
            .limit(50)
            .all()
        )

        conv_list = []
        for conv in conversations:
            msg_count = (
                db.query(Message)
                .filter(Message.conversation_id == conv.id)
                .count()
            )
            conv_list.append({
                "id": conv.id,
                "title": conv.title or "新对话",
                "mode": conv.mode,
                "msg_count": msg_count,
                "created_at": conv.created_at,
            })

        return templates.TemplateResponse(
            request=request, name="chat.html", context={
            "conversations": conv_list,
        })
    finally:
        db.close()


# ──────────────────────────────────────────────
# API 路由
# ──────────────────────────────────────────────

@router.get("/conversations")
def get_conversations(
    db: Session = Depends(get_db),
):
    """
    获取所有对话列表（JSON）

    返回:
        list[dict]: 对话列表，按时间倒序排列
    """
    conversations = (
        db.query(Conversation)
        .order_by(Conversation.created_at.desc())
        .all()
    )
    return [
        {
            "id": c.id,
            "title": c.title,
            "mode": c.mode,
            "scope_kb_id": c.scope_kb_id,
            "message_count": db.query(Message).filter(Message.conversation_id == c.id).count(),
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in conversations
    ]


@router.post("/conversations")
def create_conversation(
    req: CreateConversationRequest,
    db: Session = Depends(get_db),
):
    """
    创建新对话

    请求体:
        mode: 对话模式（kb_qa / free_chat / scope_locked）
        kb_id: 可选的知识库 ID

    返回:
        dict: 新创建的对话信息
    """
    # 验证 mode
    valid_modes = {"kb_qa", "free_chat", "scope_locked"}
    if req.mode not in valid_modes:
        raise HTTPException(status_code=400, detail=f"无效的对话模式，可选：{valid_modes}")

    # scope_locked 模式必须提供 kb_id
    if req.mode == "scope_locked" and not req.kb_id:
        raise HTTPException(status_code=400, detail="scope_locked 模式必须提供 kb_id")

    conversation = Conversation(
        title="新对话",
        mode=req.mode,
        scope_kb_id=req.kb_id,
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)

    return {
        "id": conversation.id,
        "title": conversation.title,
        "mode": conversation.mode,
        "scope_kb_id": conversation.scope_kb_id,
        "created_at": conversation.created_at.isoformat() if conversation.created_at else None,
    }


@router.delete("/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
):
    """
    删除对话及其所有消息

    参数:
        conversation_id: 对话 ID

    返回:
        dict: 操作结果
    """
    conversation = (
        db.query(Conversation)
        .filter(Conversation.id == conversation_id)
        .first()
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="对话不存在")

    db.delete(conversation)
    db.commit()
    return {"success": True, "message": f"对话 {conversation_id} 已删除"}


@router.get("/conversations/{conversation_id}")
def get_conversation_messages(
    conversation_id: int,
    db: Session = Depends(get_db),
):
    """
    获取对话历史消息（JSON）

    参数:
        conversation_id: 对话 ID

    返回:
        dict: 包含对话信息及消息列表
    """
    conversation = (
        db.query(Conversation)
        .filter(Conversation.id == conversation_id)
        .first()
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="对话不存在")

    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
        .all()
    )

    return {
        "id": conversation.id,
        "title": conversation.title,
        "mode": conversation.mode,
        "scope_kb_id": conversation.scope_kb_id,
        "created_at": conversation.created_at.isoformat() if conversation.created_at else None,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "referenced_docs": m.referenced_docs,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
    }


@router.post("/conversations/{conversation_id}/send")
async def send_message(
    conversation_id: int,
    req: SendMessageRequest,
    db: Session = Depends(get_db),
    ai_service: AIService = Depends(get_ai_service),
):
    """
    发送消息 —— 流式返回 AI 回复（SSE）

    请求体:
        content: 用户消息文本

    返回:
        SSE 流: text/event-stream 格式的 AI 回复
    """
    # 验证对话存在
    conversation = (
        db.query(Conversation)
        .filter(Conversation.id == conversation_id)
        .first()
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="对话不存在")

    async def generate_sse():
        """生成 SSE 流式响应"""
        # 如果是对话的第一条消息，自动生成标题
        message_count = (
            db.query(Message)
            .filter(Message.conversation_id == conversation_id)
            .count()
        )

        if message_count == 0 and conversation.title == "新对话":
            try:
                title = await ai_service.generate_title(req.content)
                if title:
                    conversation.title = title
                    db.commit()
            except Exception:
                pass  # 标题生成失败不影响对话

        # 流式调用 AI 并输出 SSE
        try:
            async for chunk in ai_service.chat_with_kb(
                user_message=req.content,
                conversation_id=conversation_id,
                db=db,
                kb_id=conversation.scope_kb_id,
            ):
                # SSE 格式: data: <json>\n\n
                event_data = json.dumps({"type": "chunk", "content": chunk}, ensure_ascii=False)
                yield f"data: {event_data}\n\n"

            # 发送完成事件
            yield f"data: {json.dumps({'type': 'done', 'content': ''})}\n\n"
        except Exception as e:
            error_data = json.dumps({"type": "error", "content": str(e)}, ensure_ascii=False)
            yield f"data: {error_data}\n\n"

    return StreamingResponse(
        generate_sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲
        },
    )


@router.get("/conversations/{conversation_id}/stream")
async def conversation_stream(
    conversation_id: int,
    db: Session = Depends(get_db),
):
    """
    SSE 端点 —— 供前端 EventSource 接收实时流式回复

    此端点作为一个持久连接等待新的 AI 回复。
    注意：当前实现中，SSE 流通过 /send 端点实时返回，
    此端点作为兼容性预留。

    参数:
        conversation_id: 对话 ID
    """
    conversation = (
        db.query(Conversation)
        .filter(Conversation.id == conversation_id)
        .first()
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="对话不存在")

    async def keep_alive():
        """保持连接，定期发送心跳"""
        while True:
            yield f"data: {json.dumps({'type': 'heartbeat', 'content': ''})}\n\n"
            await asyncio.sleep(15)

    return StreamingResponse(
        keep_alive(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
