"""
FastAPI 应用入口 —— 个人知识库系统

启动时初始化数据库和 ChromaDB，注册各功能模块路由。
关闭时自动清理 AI 服务 HTTP 连接和 ChromaDB 资源。
（信号处理由 Uvicorn 自身管理，不在此处拦截，避免阻止正常退出）
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
import chromadb

from app.config import get_config, PROJECT_ROOT
from app.models.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理器

    启动：初始化 SQLite、ChromaDB
    关闭：清理 httpx 客户端、释放 ChromaDB 引用

    重要：不注册自定义信号处理器 —— Uvicorn 自行处理 SIGINT/SIGTERM，
    并自动触发 lifespan 的 yield 后清理代码。自行注册 handler 会拦截信号
    导致 Uvicorn 无法正常退出，表现为 Ctrl+C 后卡住不动。
    """
    # ═══════════════════════════════════════════════
    # 启动阶段
    # ═══════════════════════════════════════════════

    # 1. 初始化 SQLite 数据库表
    init_db()
    print("[启动] 数据库表初始化完成")

    # 2. 初始化 ChromaDB 持久化客户端及集合
    config = get_config()
    chroma_path = config["database"]["chromadb_path"]
    os.makedirs(chroma_path, exist_ok=True)

    chroma_client = chromadb.PersistentClient(path=chroma_path)
    chroma_client.get_or_create_collection(
        name="knowledge_chunks",
        metadata={"description": "知识库文档分块向量集合，用于语义检索"}
    )
    app.state.chroma_client = chroma_client
    print(f"[启动] ChromaDB 初始化完成，路径: {chroma_path}")

    server_info = config.get("server", {})
    host = server_info.get("host", "127.0.0.1")
    port = server_info.get("port", 8000)
    print(f"[启动] 个人知识库系统已就绪 → http://{host}:{port}")
    print("[提示] 按 Ctrl+C 停止服务器")

    # ── 将控制权交给应用 ──
    yield

    # ═══════════════════════════════════════════════
    # 关闭阶段（Uvicorn 收到 SIGINT 后自动执行）
    # ═══════════════════════════════════════════════
    print("\n[关闭] 正在清理资源...")

    # 1. 关闭 AI 服务的 httpx 客户端（防止连接泄漏）
    try:
        from app.services.chat import _ai_service_instance
        if _ai_service_instance is not None:
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(_ai_service_instance.close())
                else:
                    loop.run_until_complete(_ai_service_instance.close())
            except Exception:
                pass
            print("[关闭] AI 服务 HTTP 客户端已关闭")
    except Exception:
        pass

    # 2. ChromaDB 客户端由 PersistentClient 自身管理持久化，清理引用即可
    if hasattr(app.state, "chroma_client"):
        del app.state.chroma_client
        print("[关闭] ChromaDB 客户端引用已释放")

    print("[关闭] 清理完成，服务已安全退出")


# 创建 FastAPI 应用实例（使用 lifespan 替代已弃用的 on_event）
app = FastAPI(title="个人知识库系统", version="0.1.0", lifespan=lifespan)


# ──────────────────────────────────────────────
# 根路径 —— 重定向到知识库首页
# ──────────────────────────────────────────────
@app.get("/")
def root():
    """根路径重定向到知识库首页"""
    return RedirectResponse(url="/knowledge")


# ──────────────────────────────────────────────
# 注册各功能模块路由
# ──────────────────────────────────────────────
# 路由规划：
#   /knowledge  — 知识管理（文档上传、分块、检索）
#   /chat       — AI 对话（基于知识库的问答、自由对话）
#   /plan       — 学习计划（计划生成与管理）
#   /exam       — 考察（出题、答题、评分）
#
# 各路由模块由对应 Agent 实现，此处预留导入和注册代码。

# 知识管理路由
try:
    from app.routers import knowledge
    app.include_router(knowledge.router, prefix="/knowledge", tags=["知识管理"])
except ImportError:
    pass  # 路由模块尚未实现，跳过注册

# AI 对话路由
try:
    from app.routers import chat
    app.include_router(chat.router, prefix="/chat", tags=["AI 对话"])
    print("[启动] AI 对话路由已注册 → /chat")
except ImportError:
    pass

# 学习计划路由
try:
    from app.routers import plan
    app.include_router(plan.router, prefix="/plan", tags=["学习计划"])
    print("[启动] 学习计划路由已注册 → /plan")
except ImportError:
    pass

# 考察路由
try:
    from app.routers import exam
    app.include_router(exam.router, prefix="/exam", tags=["考察"])
    print("[启动] 考察路由已注册 → /exam")
except ImportError:
    pass


# ──────────────────────────────────────────────
# 挂载静态文件目录
# ──────────────────────────────────────────────
static_dir = os.path.join(PROJECT_ROOT, "app", "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")
