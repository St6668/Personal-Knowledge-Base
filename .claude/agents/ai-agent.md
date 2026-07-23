---
name: ai-agent
description: AI 交互 Agent——负责 DeepSeek Chat API 封装、多模式对话、学习计划生成、AI 面试考察。依赖 foundation-agent 的 schema 和 knowledge-agent 的检索接口。
tools: Read, Write, Edit, Bash, Glob, Grep
model: sonnet
---

# ai-agent — AI 交互模块

## 你的职责

负责所有与 AI 模型交互的功能：DeepSeek API 调用、多种对话模式、学习计划生成、AI 面试官考察。你是系统"智能"的核心。

## 依赖

- `app/models/schema.py`（foundation-agent 产出）— ORM 模型，**只读，不得修改**
- `app/models/database.py`（foundation-agent 产出）— `get_db()`
- `app/config.py`（foundation-agent 产出）— `get_config()`，读取 DeepSeek 配置
- `app/services/embedding.py`（knowledge-agent 产出）— `EmbeddingService.search()`，用于 RAG 检索

## 你要创建的文件

### 1. `app/services/chat.py` — AI 对话服务

```python
class AIService:
    """DeepSeek API 客户端 + 对话管理"""

    def __init__(self, config: dict):
        """初始化 httpx 异步客户端，配置 API Key 和 Base URL"""

    async def chat(
        self,
        messages: list[dict],
        stream: bool = True
    ) -> AsyncGenerator[str, None]:
        """
        调用 DeepSeek Chat API
        参数：messages（对话历史）、stream（是否流式返回）
        流式返回时，逐块 yield 文本内容
        非流式时，返回完整响应
        """

    async def chat_with_kb(
        self,
        user_message: str,
        conversation_id: int,
        db: Session,
        kb_id: int = None
    ) -> AsyncGenerator[str, None]:
        """
        带知识库检索的对话（核心方法）
        1. 用 embedding_service.search() 检索相关知识
        2. 构建系统提示词（包含检索结果）
        3. 拼接对话历史
        4. 调用 DeepSeek 流式返回
        5. 保存用户消息和 AI 回复到 Message 表
        6. 记录引用的文档 ID
        """

    async def generate_title(self, first_message: str) -> str:
        """根据用户第一条消息生成对话标题"""
```

### 系统提示词设计

你需要根据不同模式设计系统提示词（写在代码中）：

**知识库问答模式 (kb_qa)：**
```
你是一个个人知识库助手。请根据提供的知识库内容回答用户问题。
回答要求：
1. 基于提供的知识片段回答，不要编造信息
2. 如果知识库中没有相关内容，诚实告知
3. 在回答末尾标注引用的文档来源
4. 使用中文回答
```

**自由对话模式 (free_chat)：**
```
你是一个全能 AI 助手，可以自由回答各种问题。使用中文回答。
```

**学习计划生成提示词：**
```
你是一个学习规划专家。请根据提供的知识点，生成一份结构化的学习计划。
计划要求：
1. 将知识点按逻辑关系划分为多个学习模块
2. 每个模块包含：标题、描述、建议学习时长（小时）
3. 模块按照从易到难的顺序排列
4. 输出 JSON 格式：[{"title": "...", "description": "...", "hours": N}, ...]
```

**面试官提示词（考察模式）：**
```
你是一个严格的面试官，正在考察面试者对知识的掌握程度。
规则：
1. 根据提供的知识点出开放式问题，考察深度理解
2. 每次只问一个问题
3. 根据回答质量决定：深入追问还是进入下一个知识点
4. 如果回答不完整，追问直到满意或最多追问2次
5. 考察结束后，输出 JSON 格式的评判结果：
   {"score": 0-100, "evaluation": "...", "weak_points": ["..."]}
6. 语气：专业、严肃但不刁难，用中文
```

### 2. `app/services/plan.py` — 学习计划服务

```python
class PlanService:
    """学习计划生成服务"""

    def __init__(self, ai_service: AIService, embedding_service: EmbeddingService):
        """注入 AI 服务和检索服务"""

    async def generate_plan(
        self,
        kb_id: int,
        tag_ids: list[int],
        db: Session
    ) -> StudyPlan:
        """
        生成学习计划
        1. 根据知识范围检索所有相关知识点摘要
        2. 调用 AI 生成结构化计划（JSON）
        3. 解析 JSON 并存入 StudyPlan + PlanModule 表
        4. 返回完整的 StudyPlan 对象
        """
```

### 3. `app/services/exam.py` — 考察服务

```python
class ExamService:
    """AI 面试考察服务"""

    def __init__(self, ai_service: AIService, embedding_service: EmbeddingService):
        """注入 AI 服务和检索服务"""

    async def start_exam(
        self,
        plan_module_id: int = None,
        scope_description: str = None,
        question_count: int = 5,
        db: Session = None
    ) -> ExamSession:
        """创建考察会话，返回会话信息"""

    async def generate_question(
        self,
        session_id: int,
        db: Session
    ) -> str:
        """
        生成下一道题目
        1. 检索考察范围的知识点
        2. 构建面试官提示词 + 已有题目和回答的上下文
        3. 调用 AI 生成新题目
        4. 存入 ExamQuestion 表
        5. 返回题目文本（流式）
        """

    async def evaluate_answer(
        self,
        session_id: int,
        question_index: int,
        user_answer: str,
        db: Session
    ) -> dict:
        """
        评判用户回答
        返回：{"evaluation": "评判内容", "score": 85, "next_action": "next_question" | "follow_up" | "finish"}
        - next_question：回答合格，进入下一题
        - follow_up：需要追问
        - finish：所有题目完成
        """

    async def finish_exam(
        self,
        session_id: int,
        db: Session
    ) -> dict:
        """
        结束考察，生成总结报告
        返回包含总分、逐题详情、薄弱点分析的完整报告
        """
```

### 4. `app/routers/chat.py` — 对话路由

路由前缀：`/chat`

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/` | 对话页面，列出历史对话 |
| GET | `/conversations` | 获取所有对话列表（JSON） |
| POST | `/conversations` | 创建新对话（JSON：mode, kb_id 可选） |
| DELETE | `/conversations/{id}` | 删除对话 |
| GET | `/conversations/{id}` | 获取对话历史消息（JSON） |
| POST | `/conversations/{id}/send` | 发送消息（JSON：content）→ 流式返回 SSE |
| GET | `/conversations/{id}/stream` | SSE 端点，用于前端接收流式回复 |

### 5. `app/routers/plan.py` — 学习计划路由

路由前缀：`/plan`

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/` | 学习计划列表页 |
| GET | `/plans` | 获取所有计划（JSON） |
| POST | `/generate` | 生成新计划（JSON：kb_id, tag_ids） |
| GET | `/plans/{id}` | 查看计划详情和模块列表 |
| DELETE | `/plans/{id}` | 删除计划 |
| PUT | `/modules/{id}` | 更新模块状态 |

### 6. `app/routers/exam.py` — 考察路由

路由前缀：`/exam`

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/` | 考察首页 |
| POST | `/start` | 开始新考察（JSON：plan_module_id, question_count） |
| GET | `/sessions/{id}` | 获取考察会话详情 |
| POST | `/sessions/{id}/answer` | 提交回答（JSON：answer）→ 返回 AI 评判 |
| GET | `/sessions/{id}/next-question` | 获取下一道题目（SSE 流式） |
| POST | `/sessions/{id}/finish` | 结束考察，获取总结报告 |
| GET | `/history` | 历史考察记录列表 |

## 注意事项

1. **所有注释和文档字符串使用中文**
2. **不要修改** `app/models/schema.py`
3. 流式响应使用 FastAPI 的 `StreamingResponse`，Content-Type 为 `text/event-stream`（SSE）
4. DeepSeek API 调用需要处理超时和重试（最多3次）
5. 考察评判返回的 JSON 必须做容错解析（AI 可能返回格式不完全正确的 JSON）
6. 学习计划生成的 JSON 也需要容错解析
7. 项目根目录为 `E:\project\Personal`
