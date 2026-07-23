"""
学习计划路由 —— 计划生成与管理模块

路由前缀：/plan

提供完整的学习计划管理 API：
- 列出/生成/查看/删除学习计划
- 更新计划模块的学习状态
"""

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import PROJECT_ROOT
from app.models.database import get_db
from app.models.schema import StudyPlan, PlanModule
from app.services.plan import PlanService, get_plan_service

templates = Jinja2Templates(directory=os.path.join(PROJECT_ROOT, "app", "templates"))

# ──────────────────────────────────────────────
# 路由
# ──────────────────────────────────────────────

router = APIRouter()


# ──────────────────────────────────────────────
# 请求模型
# ──────────────────────────────────────────────

class GeneratePlanRequest(BaseModel):
    """生成学习计划请求"""
    kb_id: int = Field(..., description="知识库 ID")
    tag_ids: Optional[list[int]] = Field(default=None, description="标签 ID 列表，用于筛选知识点")

    class Config:
        json_schema_extra = {
            "example": {
                "kb_id": 1,
                "tag_ids": [1, 2],
            }
        }


class UpdateModuleStatusRequest(BaseModel):
    """更新模块状态请求"""
    status: str = Field(..., description="模块状态：pending / in_progress / completed")

    class Config:
        json_schema_extra = {
            "example": {"status": "in_progress"}
        }


# ──────────────────────────────────────────────
# 页面路由
# ──────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
def plan_page(request: Request):
    """
    学习计划列表页 —— 使用 plan.html 模板渲染

    显示所有学习计划及其模块。
    """
    db = next(get_db())
    try:
        plans = (
            db.query(StudyPlan)
            .order_by(StudyPlan.created_at.desc())
            .all()
        )

        plan_list = []
        for p in plans:
            modules = (
                db.query(PlanModule)
                .filter(PlanModule.plan_id == p.id)
                .order_by(PlanModule.order_index)
                .all()
            )
            plan_list.append({
                "id": p.id,
                "title": p.title,
                "scope_description": p.scope_description,
                "total_modules": p.total_modules,
                "status": p.status,
                "created_at": p.created_at,
                "modules": [{
                    "id": m.id,
                    "title": m.title,
                    "description": m.description,
                    "knowledge_refs": m.knowledge_refs,
                    "suggested_hours": m.suggested_hours,
                    "order_index": m.order_index,
                    "status": m.status,
                } for m in modules],
            })

        return templates.TemplateResponse(
            request=request, name="plan.html", context={
            "plans": plan_list,
        })
    finally:
        db.close()


# ──────────────────────────────────────────────
# API 路由
# ──────────────────────────────────────────────

@router.get("/plans")
def get_plans(db: Session = Depends(get_db)):
    """
    获取所有学习计划（JSON）

    返回:
        list[dict]: 计划列表，按创建时间倒序排列
    """
    plans = (
        db.query(StudyPlan)
        .order_by(StudyPlan.created_at.desc())
        .all()
    )
    return [
        {
            "id": p.id,
            "title": p.title,
            "scope_description": p.scope_description,
            "total_modules": p.total_modules,
            "status": p.status,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in plans
    ]


@router.post("/generate")
async def generate_plan(
    req: GeneratePlanRequest,
    db: Session = Depends(get_db),
    plan_service: PlanService = Depends(get_plan_service),
):
    """
    生成新学习计划

    请求体:
        kb_id: 知识库 ID
        tag_ids: 可选的标签 ID 列表

    返回:
        dict: 生成的计划详情（含模块列表）
    """
    try:
        plan = await plan_service.generate_plan(
            kb_id=req.kb_id,
            tag_ids=req.tag_ids,
            db=db,
        )

        # 获取模块列表
        modules = (
            db.query(PlanModule)
            .filter(PlanModule.plan_id == plan.id)
            .order_by(PlanModule.order_index)
            .all()
        )

        return {
            "id": plan.id,
            "title": plan.title,
            "scope_description": plan.scope_description,
            "total_modules": plan.total_modules,
            "status": plan.status,
            "created_at": plan.created_at.isoformat() if plan.created_at else None,
            "modules": [
                {
                    "id": m.id,
                    "title": m.title,
                    "description": m.description,
                    "knowledge_refs": m.knowledge_refs,
                    "suggested_hours": m.suggested_hours,
                    "order_index": m.order_index,
                    "status": m.status,
                }
                for m in modules
            ],
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"计划生成失败: {str(e)}")


@router.get("/plans/{plan_id}")
def get_plan_detail(
    plan_id: int,
    db: Session = Depends(get_db),
):
    """
    查看计划详情和模块列表

    参数:
        plan_id: 计划 ID

    返回:
        dict: 计划详情及所有模块
    """
    plan = db.query(StudyPlan).filter(StudyPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="计划不存在")

    modules = (
        db.query(PlanModule)
        .filter(PlanModule.plan_id == plan.id)
        .order_by(PlanModule.order_index)
        .all()
    )

    return {
        "id": plan.id,
        "title": plan.title,
        "scope_description": plan.scope_description,
        "total_modules": plan.total_modules,
        "status": plan.status,
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
        "modules": [
            {
                "id": m.id,
                "title": m.title,
                "description": m.description,
                "knowledge_refs": m.knowledge_refs,
                "suggested_hours": m.suggested_hours,
                "order_index": m.order_index,
                "status": m.status,
            }
            for m in modules
        ],
    }


@router.delete("/plans/{plan_id}")
def delete_plan(
    plan_id: int,
    db: Session = Depends(get_db),
):
    """
    删除学习计划（级联删除所有模块）

    参数:
        plan_id: 计划 ID

    返回:
        dict: 操作结果
    """
    plan = db.query(StudyPlan).filter(StudyPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="计划不存在")

    db.delete(plan)
    db.commit()
    return {"success": True, "message": f"计划 {plan_id} 及其所有模块已删除"}


@router.put("/modules/{module_id}")
def update_module_status(
    module_id: int,
    req: UpdateModuleStatusRequest,
    db: Session = Depends(get_db),
):
    """
    更新模块学习状态

    参数:
        module_id: 模块 ID

    请求体:
        status: 新状态（pending / in_progress / completed）

    返回:
        dict: 更新后的模块信息
    """
    valid_statuses = {"pending", "in_progress", "completed"}
    if req.status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"无效状态，可选：{valid_statuses}")

    module = db.query(PlanModule).filter(PlanModule.id == module_id).first()
    if not module:
        raise HTTPException(status_code=404, detail="模块不存在")

    module.status = req.status
    db.commit()
    db.refresh(module)

    # 更新关联计划的 total_modules 和 status
    plan = db.query(StudyPlan).filter(StudyPlan.id == module.plan_id).first()
    if plan:
        all_modules = (
            db.query(PlanModule)
            .filter(PlanModule.plan_id == plan.id)
            .all()
        )
        plan.total_modules = len(all_modules)
        if all(m.status == "completed" for m in all_modules):
            plan.status = "completed"
        elif any(m.status == "in_progress" for m in all_modules):
            plan.status = "in_progress"
        else:
            plan.status = "pending"
        db.commit()

    return {
        "id": module.id,
        "title": module.title,
        "status": module.status,
        "suggested_hours": module.suggested_hours,
        "order_index": module.order_index,
    }
