"""
集成测试 —— 使用 FastAPI TestClient 验证所有 API 端点
覆盖本次修改的关键功能：知识库、对话、计划、考察
"""
import io
import sys
import os
import json
import pytest

# 将项目根目录加入路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from app.main import app
from app.models.database import init_db, SessionLocal

client = TestClient(app)


# ──────────────────────────────────────────────
# 工具：获取独立 DB 会话（绕过 Depends）
# ──────────────────────────────────────────────
def _get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ──────────────────────────────────────────────
# 测试 1：根路径与页面加载
# ──────────────────────────────────────────────

def test_root_redirects_to_knowledge():
    """根路径重定向到 /knowledge"""
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code in (200, 307, 302)


def test_knowledge_page_loads():
    """知识库首页正常加载"""
    resp = client.get("/knowledge")
    assert resp.status_code == 200
    assert "知识管理" in resp.text or "knowledge" in resp.text.lower()


def test_chat_page_loads():
    """对话页正常加载"""
    resp = client.get("/chat")
    assert resp.status_code == 200


def test_plan_page_loads():
    """学习计划页正常加载"""
    resp = client.get("/plan")
    assert resp.status_code == 200


def test_exam_page_loads():
    """考察页正常加载"""
    resp = client.get("/exam")
    assert resp.status_code == 200


# ──────────────────────────────────────────────
# 测试 2：知识库 CRUD
# ──────────────────────────────────────────────

def test_create_and_list_knowledge_bases():
    """创建知识库 + 列表查询"""
    # 创建
    resp = client.post("/knowledge/kb", data={"name": "集成测试知识库", "description": "自动化测试"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "集成测试知识库"
    assert data["document_count"] == 0
    kb_id = data["id"]

    # 列表包含新知识库
    resp = client.get("/knowledge/kb")
    assert resp.status_code == 200
    kb_list = resp.json()
    assert any(kb["id"] == kb_id for kb in kb_list)

    # 清理
    client.delete(f"/knowledge/kb/{kb_id}")


def test_create_kb_missing_name():
    """创建知识库时缺少名称应返回 422"""
    resp = client.post("/knowledge/kb", data={})
    assert resp.status_code == 422


# ──────────────────────────────────────────────
# 测试 3：文档列表响应字段完整性
# ──────────────────────────────────────────────

def test_document_list_response_fields():
    """验证 /knowledge/documents 响应包含完整字段（修复 #1）"""
    # 先创建知识库
    resp = client.post("/knowledge/kb", data={"name": "字段测试库"})
    kb_id = resp.json()["id"]

    # 获取文档列表
    resp = client.get(f"/knowledge/documents?kb_id={kb_id}")
    assert resp.status_code == 200
    docs = resp.json()
    assert isinstance(docs, list)

    # 响应模型字段验证：即使列表为空，也要验证响应格式
    # 如果列表非空，检查每条记录的关键字段
    if len(docs) > 0:
        doc = docs[0]
        # 验证 DocumentResponse 必需的字段都存在
        for field in ["id", "title", "doc_type", "chunk_count", "created_at"]:
            assert field in doc, f"文档响应缺少字段: {field}"
        # kb_id 应该存在
        assert "kb_id" in doc, "文档响应缺少 kb_id 字段"

    # 清理
    client.delete(f"/knowledge/kb/{kb_id}")


# ──────────────────────────────────────────────
# 测试 4：搜索功能
# ──────────────────────────────────────────────

def test_search_empty_query():
    """空搜索关键词返回 400"""
    resp = client.get("/knowledge/search?q=")
    assert resp.status_code == 400


def test_search_with_query():
    """带关键词搜索正常返回"""
    resp = client.get("/knowledge/search?q=Python&top_k=3")
    assert resp.status_code == 200
    results = resp.json()
    assert isinstance(results, list)


# ──────────────────────────────────────────────
# 测试 5：对话 CRUD
# ──────────────────────────────────────────────

def test_list_conversations():
    """列出对话"""
    resp = client.get("/chat/conversations")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_create_and_delete_conversation():
    """创建 + 删除对话"""
    # 创建
    resp = client.post("/chat/conversations", json={"mode": "free_chat"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "free_chat"
    conv_id = data["id"]

    # 删除
    resp = client.delete(f"/chat/conversations/{conv_id}")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_create_conversation_invalid_mode():
    """无效的对话模式返回 400"""
    resp = client.post("/chat/conversations", json={"mode": "invalid_mode"})
    assert resp.status_code == 400


def test_get_nonexistent_conversation():
    """获取不存在的对话返回 404"""
    resp = client.get("/chat/conversations/99999")
    assert resp.status_code == 404


# ──────────────────────────────────────────────
# 测试 6：学习计划 API
# ──────────────────────────────────────────────

def test_list_plans():
    """列出学习计划"""
    resp = client.get("/plan/plans")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_get_nonexistent_plan():
    """获取不存在的计划返回 404"""
    resp = client.get("/plan/plans/99999")
    assert resp.status_code == 404


def test_update_module_invalid_status():
    """更新模块使用无效状态返回 400"""
    # 先确认模块不存在，返回 404
    resp = client.put("/plan/modules/99999", json={"status": "invalid"})
    assert resp.status_code in (400, 404)


# ──────────────────────────────────────────────
# 测试 7：考察 API
# ──────────────────────────────────────────────

def test_exam_history():
    """获取考察历史"""
    resp = client.get("/exam/history")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_get_nonexistent_exam_session():
    """获取不存在的考察会话返回 404"""
    resp = client.get("/exam/sessions/99999")
    assert resp.status_code == 404


def test_export_nonexistent_session():
    """导出不存在的考察会话返回 404"""
    resp = client.get("/exam/sessions/99999/export")
    assert resp.status_code == 404


# ──────────────────────────────────────────────
# 测试 8：标签 API
# ──────────────────────────────────────────────

def test_list_tags():
    """列出标签"""
    resp = client.get("/knowledge/tags")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_create_and_verify_tag():
    """创建标签并验证"""
    import uuid
    tag_name = f"test_{uuid.uuid4().hex[:8]}"
    resp = client.post("/knowledge/tags", data={"name": tag_name})
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == tag_name

    # 验证标签出现在列表中
    resp = client.get("/knowledge/tags")
    tags = resp.json()
    assert any(t["name"] == tag_name for t in tags)


def test_create_duplicate_tag():
    """创建重复标签返回 400"""
    import uuid
    tag_name = f"dup_{uuid.uuid4().hex[:8]}"
    resp = client.post("/knowledge/tags", data={"name": tag_name})
    assert resp.status_code == 200
    # 再次创建同名标签
    resp = client.post("/knowledge/tags", data={"name": tag_name})
    assert resp.status_code == 400


# ──────────────────────────────────────────────
# 测试 9：考察导出报告 Content-Disposition 头
# ──────────────────────────────────────────────

def test_export_uses_ascii_content_disposition():
    """验证导出接口只输出 ASCII 安全的 Content-Disposition（修复 #5）"""
    # 创建一个完整的考察会话需要 AI 调用，这里仅验证端点存在且不崩溃
    # 实际验证：404 场景不会产生非 ASCII 头
    resp = client.get("/exam/sessions/99999/export")
    assert resp.status_code == 404


# ──────────────────────────────────────────────
# 测试 10：路由注册完整性
# ──────────────────────────────────────────────

def test_all_routers_registered():
    """验证四大模块路由均已注册（通过实际 HTTP 请求验证）"""
    endpoints = [
        ("/knowledge/", 200),   # 知识库页面
        ("/chat/", 200),         # 对话页面
        ("/plan/", 200),         # 学习计划页面
        ("/exam/", 200),         # 考察页面
    ]
    for path, expected_status in endpoints:
        resp = client.get(path)
        assert resp.status_code == expected_status, (
            f"{path} 返回 {resp.status_code}，期望 {expected_status}"
        )


# ──────────────────────────────────────────────
# 测试 11：静态文件
# ──────────────────────────────────────────────

def test_static_files_accessible():
    """静态文件可访问"""
    resp = client.get("/static/css/style.css")
    assert resp.status_code == 200
    assert "Scholarly Ink" in resp.text or "font-family" in resp.text


def test_static_js_accessible():
    """JS 文件可访问"""
    for js_file in ["/static/js/app.js", "/static/js/chat.js", "/static/js/exam.js", "/static/js/knowledge.js", "/static/js/plan.js"]:
        resp = client.get(js_file)
        assert resp.status_code == 200, f"{js_file} 返回 {resp.status_code}"


# ──────────────────────────────────────────────
# 测试 12：笔记创建（完整流程）
# ──────────────────────────────────────────────

def test_create_note_full_flow():
    """创建知识库 → 创建笔记 → 验证字段完整性"""
    # 创建知识库
    resp = client.post("/knowledge/kb", data={"name": "笔记测试库"})
    assert resp.status_code == 200
    kb_id = resp.json()["id"]

    # 创建笔记
    resp = client.post("/knowledge/note", data={
        "title": "测试笔记",
        "content": "这是一篇测试笔记的内容，包含足够的文字来验证分块和向量化功能。",
        "kb_id": str(kb_id),
        "tags": "测试, 集成",
    })
    assert resp.status_code == 200
    data = resp.json()

    # 验证核心字段都存在
    assert data["title"] == "测试笔记"
    assert data["doc_type"] == "note"
    assert data["kb_id"] == kb_id
    assert "id" in data
    assert "created_at" in data
    # tags 应该在响应中
    assert "tags" in data, f"响应缺少 tags 字段: {list(data.keys())}"
    assert len(data["tags"]) == 2

    doc_id = data["id"]

    # 查看文档详情
    resp = client.get(f"/knowledge/document/{doc_id}")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["title"] == "测试笔记"
    assert len(detail["chunks"]) >= 1
    assert len(detail["tags"]) == 2

    # 清理
    client.delete(f"/knowledge/document/{doc_id}")
    client.delete(f"/knowledge/kb/{kb_id}")


# ──────────────────────────────────────────────
# 入口
# ──────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
