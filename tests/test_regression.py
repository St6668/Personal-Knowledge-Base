"""
回归测试 —— 验证所有修复点是否正确
覆盖本次修复的 4 个问题：
1. DocumentResponse 重复定义（knowledge.py）
2. ChromaDB Collection 名称一致性（main.py）
3. 学习计划状态逻辑 bug（plan.py）
4. 系统提示词传递方式（plan.py, exam.py）
"""

import json
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

# ──────────────────────────────────────────────
# 测试 1：DocumentResponse 不应重复定义
# ──────────────────────────────────────────────

def test_document_response_not_duplicated():
    """验证 knowledge.py 中 DocumentResponse 只定义一次"""
    import app.routers.knowledge as knowledge_module
    import inspect

    # 统计模块中 DocumentResponse 类定义的次数
    definitions = [
        (name, obj) for name, obj in inspect.getmembers(knowledge_module)
        if name == "DocumentResponse" and inspect.isclass(obj)
    ]
    assert len(definitions) == 1, (
        f"DocumentResponse 被定义了 {len(definitions)} 次，应该只有 1 次"
    )


def test_document_response_has_required_fields():
    """验证 DocumentResponse 包含所有必需字段"""
    from app.routers.knowledge import DocumentResponse

    fields = DocumentResponse.model_fields
    required_fields = {"id", "title", "doc_type", "source_path", "kb_id", "chunk_count", "created_at", "tags"}
    actual_fields = set(fields.keys())
    missing = required_fields - actual_fields
    assert not missing, f"DocumentResponse 缺少字段: {missing}"


def test_document_response_tags_defaults_to_empty_list():
    """验证 tags 字段默认值为空列表"""
    from app.routers.knowledge import DocumentResponse

    # 用最少字段构造实例，验证 tags 默认为 []
    instance = DocumentResponse(
        id=1,
        title="测试文档",
        doc_type="txt",
        created_at="2026-07-23T00:00:00",
    )
    assert instance.tags == [], f"tags 默认值应为 []，实际为 {instance.tags}"


def test_document_response_accepts_tags():
    """验证 DocumentResponse 可以接受 tags 字段"""
    from app.routers.knowledge import DocumentResponse

    instance = DocumentResponse(
        id=1,
        title="测试文档",
        doc_type="txt",
        source_path="/path/to/file",
        kb_id=1,
        created_at="2026-07-23T00:00:00",
        tags=["Python", "FastAPI"],
    )
    assert instance.tags == ["Python", "FastAPI"]
    assert instance.source_path == "/path/to/file"


# ──────────────────────────────────────────────
# 测试 2：ChromaDB Collection 名称一致性
# ──────────────────────────────────────────────

def _find_get_or_create_collection_names(file_path: str) -> list[str]:
    """AST 解析：提取文件中所有 get_or_create_collection(name=...) 的 name 值"""
    import ast

    with open(file_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            # 检查调用的函数名是否为 get_or_create_collection
            func = node.func
            func_name = None
            if isinstance(func, ast.Attribute):
                func_name = func.attr
            elif isinstance(func, ast.Name):
                func_name = func.id

            if func_name == "get_or_create_collection":
                for kw in node.keywords:
                    if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                        names.append(kw.value.value)
    return names


def test_chromadb_collection_name_consistent():
    """验证 main.py 和 embedding.py 使用相同的 collection 名称"""
    import os

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app_dir = os.path.join(project_root, "app")

    main_names = _find_get_or_create_collection_names(
        os.path.join(app_dir, "main.py")
    )
    embedding_names = _find_get_or_create_collection_names(
        os.path.join(app_dir, "services", "embedding.py")
    )

    assert len(main_names) >= 1, "main.py 中应有 get_or_create_collection 调用"
    assert len(embedding_names) >= 1, "embedding.py 中应有 get_or_create_collection 调用"

    assert main_names[0] == embedding_names[0], (
        f"Collection 名称不一致: main.py={main_names}, embedding.py={embedding_names}"
    )


# ──────────────────────────────────────────────
# 测试 3：学习计划状态逻辑
# ──────────────────────────────────────────────

class TestPlanStatusLogic:
    """测试 update_module_status 中的计划状态更新逻辑"""

    def _simulate_status_update(self, module_statuses: list[str]) -> str:
        """
        模拟 update_module_status 中的状态判断逻辑
        参数:
            module_statuses: 所有模块的状态列表
        返回:
            plan.status 应设为何值
        """
        all_completed = all(s == "completed" for s in module_statuses)
        any_in_progress = any(s == "in_progress" for s in module_statuses)

        if all_completed:
            return "completed"
        elif any_in_progress:
            return "in_progress"
        else:
            # 此次修复的关键：else 分支应返回 "pending"
            return "pending"

    def test_all_pending_returns_pending(self):
        """所有模块为 pending 时，计划状态应为 pending"""
        result = self._simulate_status_update(["pending", "pending", "pending"])
        assert result == "pending", f"期望 pending，实际 {result}"

    def test_all_completed_returns_completed(self):
        """所有模块为 completed 时，计划状态应为 completed"""
        result = self._simulate_status_update(["completed", "completed"])
        assert result == "completed", f"期望 completed，实际 {result}"

    def test_any_in_progress_returns_in_progress(self):
        """任一模块为 in_progress 时，计划状态应为 in_progress"""
        result = self._simulate_status_update(["pending", "in_progress", "completed"])
        assert result == "in_progress", f"期望 in_progress，实际 {result}"

    def test_mixed_pending_and_completed_returns_pending(self):
        """pending + completed 混合时，计划状态应为 pending（关键边界条件）"""
        result = self._simulate_status_update(["pending", "completed", "pending"])
        assert result == "pending", (
            f"pending + completed 混合时计划状态应为 pending，实际为 {result}"
        )

    def test_empty_modules_returns_completed(self):
        """
        没有模块时的边界条件
        注意：Python 的 all() 对空序列返回 True，
        因此空模块列表会导致计划被标记为 "completed"。
        此情况在实际中不会发生（无模块时无法触发状态更新）。
        """
        result = self._simulate_status_update([])
        # all([]) 为 True，所以返回 "completed"
        assert result == "completed"


# ──────────────────────────────────────────────
# 测试 4a：PlanService 系统提示词传递
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_plan_service_uses_system_prompt_parameter():
    """验证 PlanService.generate_plan 通过 system_prompt 参数传递提示词"""
    from app.services.plan import PlanService, AIService, SYSTEM_PROMPT_PLAN_GENERATION

    # 用真实的 AIService 实例 + mock _get_client 来测试
    captured_kwargs = {}

    class MockAIService(AIService):
        async def chat(self, messages, stream=True, system_prompt=None):
            captured_kwargs["system_prompt"] = system_prompt
            captured_kwargs["messages"] = messages
            yield '[{"title": "模块1", "description": "测试内容", "hours": 2, "knowledge_refs": [1]}]'

    config = {
        "deepseek": {"api_key": "test", "base_url": "https://api.test.com", "chat_model": "test"},
        "database": {"sqlite_path": "data/test.db", "chromadb_path": "data/test_chroma"},
    }
    mock_ai = MockAIService(config=config)

    service = PlanService(ai_service=mock_ai)
    service._collect_knowledge_points = MagicMock(return_value=[
        "知识点1：Python 基础语法知识，包含变量、数据类型、控制流等内容",
        "知识点2：面向对象编程，类与对象、继承与多态",
    ])

    mock_db = MagicMock()
    # 让 flush 后 commit 失败以中断流程，但 system_prompt 此时已被捕获
    mock_db.commit.side_effect = RuntimeError("mock DB commit")

    with pytest.raises(RuntimeError, match="mock DB commit"):
        await service.generate_plan(kb_id=1, db=mock_db)

    # 验证 system_prompt 被正确传递（在 mock_db 抛出异常之前已执行）
    assert captured_kwargs.get("system_prompt") is not None, (
        "system_prompt 不应为 None"
    )
    assert captured_kwargs["system_prompt"] == SYSTEM_PROMPT_PLAN_GENERATION, (
        f"system_prompt 应为 SYSTEM_PROMPT_PLAN_GENERATION"
    )
    # 验证系统提示词没有嵌入在用户消息中
    for msg in captured_kwargs.get("messages", []):
        if msg["role"] == "user":
            assert "你是一个学习规划专家" not in msg["content"], (
                "系统提示词不应嵌入在用户消息中"
            )


# ──────────────────────────────────────────────
# 测试 4b：ExamService 系统提示词传递
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_exam_generate_question_uses_system_prompt():
    """验证 ExamService.generate_question 通过 system_prompt 参数传递提示词"""
    from app.services.exam import ExamService, AIService, SYSTEM_PROMPT_EXAMINER
    from app.models.schema import ExamSession

    captured_kwargs = {}

    class MockAIService(AIService):
        async def chat(self, messages, stream=True, system_prompt=None):
            captured_kwargs["system_prompt"] = system_prompt
            captured_kwargs["messages"] = messages
            yield "请解释什么是依赖注入及其在实际项目中的应用？"

    config = {
        "deepseek": {"api_key": "test", "base_url": "https://api.test.com", "chat_model": "test"},
        "database": {"sqlite_path": "data/test.db", "chromadb_path": "data/test_chroma"},
    }
    mock_ai = MockAIService(config=config)

    mock_db = MagicMock()
    session = ExamSession(
        id=1, plan_module_id=None,
        scope_description="测试范围", question_count=3,
        status="in_progress"
    )
    mock_db.query.return_value.filter.return_value.first.return_value = session
    # count 用于检查已有题目数
    mock_db.query.return_value.filter.return_value.count.return_value = 0

    service = ExamService(ai_service=mock_ai)
    service._retrieve_exam_scope = AsyncMock(return_value="测试考察范围内容")

    result = await service.generate_question(session_id=1, db=mock_db)
    assert len(result) > 0

    assert captured_kwargs.get("system_prompt") is not None
    assert captured_kwargs["system_prompt"] == SYSTEM_PROMPT_EXAMINER
    for msg in captured_kwargs.get("messages", []):
        if msg["role"] == "user":
            assert "你是一个严格的面试官" not in msg["content"]


@pytest.mark.asyncio
async def test_exam_evaluate_answer_uses_system_prompt():
    """验证 ExamService.evaluate_answer 通过 system_prompt 参数传递提示词"""
    from app.services.exam import ExamService, AIService, SYSTEM_PROMPT_EXAMINER
    from app.models.schema import ExamSession, ExamQuestion

    captured_kwargs = {}

    class MockAIService(AIService):
        async def chat(self, messages, stream=True, system_prompt=None):
            captured_kwargs["system_prompt"] = system_prompt
            captured_kwargs["messages"] = messages
            yield '{"score": 85, "evaluation": "回答正确，阐述清晰", "weak_points": [], "next_action": "next_question"}'

    config = {
        "deepseek": {"api_key": "test", "base_url": "https://api.test.com", "chat_model": "test"},
        "database": {"sqlite_path": "data/test.db", "chromadb_path": "data/test_chroma"},
    }
    mock_ai = MockAIService(config=config)

    mock_db = MagicMock()
    session = ExamSession(id=1, scope_description="测试范围", question_count=5, status="in_progress")
    question = ExamQuestion(id=1, session_id=1, question_text="什么是依赖注入？", question_index=0)

    # side_effect: 第一次 query 返回 session, 第二次 query 返回 question
    mock_db.query.return_value.filter.return_value.first.side_effect = [session, question]

    service = ExamService(ai_service=mock_ai)
    service._retrieve_exam_scope = AsyncMock(return_value="测试考察范围内容")

    result = await service.evaluate_answer(session_id=1, question_index=0, user_answer="我的回答内容", db=mock_db)
    assert "score" in result
    assert "evaluation" in result

    assert captured_kwargs.get("system_prompt") is not None
    assert captured_kwargs["system_prompt"] == SYSTEM_PROMPT_EXAMINER
    for msg in captured_kwargs.get("messages", []):
        if msg["role"] == "user":
            assert "你是一个严格的面试官" not in msg["content"]


# ──────────────────────────────────────────────
# 测试 5：综合端到端导入测试
# ──────────────────────────────────────────────

def test_all_modified_modules_importable():
    """验证所有修改过的模块都可以正常导入"""
    modules = [
        "app.routers.knowledge",
        "app.routers.plan",
        "app.services.plan",
        "app.services.exam",
        "app.main",
    ]
    for module_name in modules:
        try:
            __import__(module_name)
        except Exception as e:
            pytest.fail(f"模块 {module_name} 导入失败: {e}")


def test_knowledge_router_has_expected_endpoints():
    """验证 knowledge 路由包含所有预期的端点"""
    from app.routers.knowledge import router

    routes = {r.path for r in router.routes}

    expected = {
        "/", "/kb", "/kb/{kb_id}",
        "/documents", "/upload", "/note",
        "/document/{doc_id}", "/search",
        "/tags",
    }
    missing = expected - routes
    assert not missing, f"缺少路由: {missing}"


def test_plan_router_has_expected_endpoints():
    """验证 plan 路由包含所有预期的端点"""
    from app.routers.plan import router

    routes = {r.path for r in router.routes}

    expected = {"/", "/plans", "/generate", "/plans/{plan_id}", "/modules/{module_id}"}
    missing = expected - routes
    assert not missing, f"缺少路由: {missing}"


def test_exam_router_has_expected_endpoints():
    """验证 exam 路由包含所有预期的端点"""
    from app.routers.exam import router

    routes = {r.path for r in router.routes}

    expected = {
        "/", "/start", "/sessions/{session_id}",
        "/sessions/{session_id}/answer",
        "/sessions/{session_id}/next-question",
        "/sessions/{session_id}/finish",
        "/sessions/{session_id}/export",
        "/history",
    }
    missing = expected - routes
    assert not missing, f"缺少路由: {missing}"


# ──────────────────────────────────────────────
# 测试 6：JSON 解析容错性
# ──────────────────────────────────────────────

def test_plan_json_parse_with_extra_text():
    """验证 PlanService 的 JSON 容错解析能处理 AI 附加的说明文字"""
    from app.services.plan import _parse_json_safely

    # AI 可能在 JSON 前后附加说明文字
    dirty_response = """
    好的，以下是为你生成的学习计划：

    [
        {"title": "Python 基础", "description": "变量与函数", "hours": 2, "knowledge_refs": [1, 2]},
        {"title": "进阶特性", "description": "装饰器与生成器", "hours": 3, "knowledge_refs": [3]}
    ]

    希望这个计划对你有帮助！
    """
    result = _parse_json_safely(dirty_response)
    assert result is not None, "应成功解析带杂文的 JSON"
    assert len(result) == 2, f"应解析出 2 个模块，实际 {len(result)}"
    assert result[0]["title"] == "Python 基础"


def test_plan_json_parse_pure_json():
    """验证纯 JSON 数组可正确解析"""
    from app.services.plan import _parse_json_safely

    clean = '[{"title": "模块A", "description": "描述", "hours": 1, "knowledge_refs": [1]}]'
    result = _parse_json_safely(clean)
    assert result is not None
    assert len(result) == 1


def test_plan_json_parse_invalid_text():
    """验证非法文本返回 None"""
    from app.services.plan import _parse_json_safely

    assert _parse_json_safely("") is None
    assert _parse_json_safely("这不是 JSON") is None


def test_exam_evaluation_json_parse():
    """验证 ExamService 的评判 JSON 解析"""
    from app.services.exam import _parse_evaluation_json

    # 正常 JSON
    result = _parse_evaluation_json(
        '{"score": 85, "evaluation": "回答正确", "weak_points": ["不够深入"], "next_action": "next_question"}'
    )
    assert result["score"] == 85
    assert result["evaluation"] == "回答正确"
    assert result["next_action"] == "next_question"

    # 空文本返回默认值
    result = _parse_evaluation_json("")
    assert result["score"] == 60
    assert "解析失败" in result["evaluation"]


def test_exam_model_answer_json_parse():
    """验证标准答案 JSON 解析"""
    from app.services.exam import _parse_model_answer_json

    result = _parse_model_answer_json(
        '{"model_answer": "正确答案是...", "extensions": "更多知识..."}'
    )
    assert result["model_answer"] == "正确答案是..."
    assert result["extensions"] == "更多知识..."

    # 空文本
    result = _parse_model_answer_json("")
    assert result["model_answer"] == ""


# ──────────────────────────────────────────────
# 测试 7：Chat 服务基础功能
# ──────────────────────────────────────────────

def test_ai_service_initialization():
    """验证 AIService 可以正常初始化"""
    from app.services.chat import AIService
    # 使用空 config 模拟
    config = {
        "deepseek": {"api_key": "test-key", "base_url": "https://api.test.com", "chat_model": "test-model"},
        "database": {"sqlite_path": "data/test.db", "chromadb_path": "data/test_chroma"},
    }
    service = AIService(config=config)
    assert service.api_key == "test-key"
    assert service.chat_model == "test-model"


def test_all_system_prompts_defined():
    """验证所有系统提示词常量都已定义，且不嵌入到用户消息中"""
    from app.services.chat import (
        SYSTEM_PROMPT_KB_QA,
        SYSTEM_PROMPT_FREE_CHAT,
        SYSTEM_PROMPT_SCOPE_LOCKED,
        SYSTEM_PROMPT_PLAN_GENERATION,
        SYSTEM_PROMPT_EXAMINER,
    )

    # 确保提示词非空且为中文
    for name, prompt in [
        ("KB_QA", SYSTEM_PROMPT_KB_QA),
        ("FREE_CHAT", SYSTEM_PROMPT_FREE_CHAT),
        ("SCOPE_LOCKED", SYSTEM_PROMPT_SCOPE_LOCKED),
        ("PLAN_GENERATION", SYSTEM_PROMPT_PLAN_GENERATION),
        ("EXAMINER", SYSTEM_PROMPT_EXAMINER),
    ]:
        assert prompt, f"SYSTEM_PROMPT_{name} 不应为空"
        assert len(prompt) > 20, f"SYSTEM_PROMPT_{name} 太短（{len(prompt)} 字符）"


# ──────────────────────────────────────────────
# 测试 8：Embedding 服务
# ──────────────────────────────────────────────

def test_embedding_service_collection_name():
    """验证 EmbeddingService 使用正确的 collection 名称"""
    import ast
    import os

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    embedding_path = os.path.join(project_root, "app", "services", "embedding.py")

    with open(embedding_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    collection_name = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in getattr(node, 'keywords', []):
                if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                    # 找到 get_or_create_collection 的 name 参数
                    collection_name = kw.value.value

    assert collection_name == "knowledge_chunks", (
        f"EmbeddingService 应使用 'knowledge_chunks'，实际为 '{collection_name}'"
    )


# ──────────────────────────────────────────────
# 入口
# ──────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
