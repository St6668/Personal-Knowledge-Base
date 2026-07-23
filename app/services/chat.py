"""
AI 对话服务 —— DeepSeek API 客户端与对话管理

功能：
- 封装 DeepSeek Chat API 异步调用
- 支持流式 (SSE) 和非流式响应
- 集成知识库检索 (RAG) 的多模式对话
- 自动保存对话消息到数据库
- 自动生成对话标题
"""

import json
import asyncio
from typing import AsyncGenerator, Optional

import httpx
from sqlalchemy.orm import Session

from app.config import get_config
from app.models.schema import Conversation, Message

# ──────────────────────────────────────────────
# 尝试导入 knowledge-agent 的 EmbeddingService
# 如果 knowledge-agent 尚未完成，则 embedding_service 为 None
# ──────────────────────────────────────────────
try:
    from app.services.embedding import EmbeddingService
    _embedding_available = True
except ImportError:
    _embedding_available = False
    EmbeddingService = None  # type: ignore


# ──────────────────────────────────────────────
# 系统提示词定义
# ──────────────────────────────────────────────

SYSTEM_PROMPT_KB_QA = """
你是一个个人知识库助手。请根据提供的知识库内容回答用户问题。
回答要求：
1. 基于提供的知识片段回答，不要编造信息
2. 如果知识库中没有相关内容，诚实告知
3. 在回答末尾标注引用的文档来源
4. 使用中文回答
""".strip()

SYSTEM_PROMPT_FREE_CHAT = """
你是一个全能 AI 助手，可以自由回答各种问题。使用中文回答。
""".strip()

SYSTEM_PROMPT_SCOPE_LOCKED = """
你是一个个人知识库助手，当前对话已锁定在特定知识范围内。
请严格按照知识库锁定的内容回答问题，不要超出该范围。
如果问题超出锁定范围，请友好地提醒用户切换对话模式。
使用中文回答。
""".strip()

SYSTEM_PROMPT_PLAN_GENERATION = """
你是一个学习规划专家。请根据提供的知识点，生成一份结构化的学习计划。

严格要求：
1. 仔细分析知识点内容，识别出其中包含的不同主题、概念和技能
2. 将知识点拆分为至少 4-8 个独立的学习模块，每个模块聚焦一个具体的主题
3. 绝对禁止：不要将所有内容合并到一个或两个模块中
4. 每个模块必须包含：
   - title: 简洁具体的模块标题（如"变量与数据类型"，不要用"基础知识"这类笼统标题）
   - description: 该模块涵盖的具体知识点列表（2-4句话）
   - hours: 建议学习时长（小时，可以带小数）
   - knowledge_refs: 该模块引用的知识点编号列表（数组，如 [1, 3, 5]），对应输入中的"知识点 N"编号。每个模块至少引用 1 个知识点
5. 模块按照从基础到进阶的顺序排列
6. 输出 JSON 格式：[{"title": "...", "description": "...", "hours": N, "knowledge_refs": [1, 3]}, ...]
7. 只输出 JSON 数组，不要包含任何其他文字说明
""".strip()

SYSTEM_PROMPT_EXAMINER = """
你是一个严格的面试官，正在考察面试者对知识的掌握程度。
规则：
1. 根据提供的知识点出开放式问题，考察深度理解
2. 每次只问一个问题
3. 根据回答质量决定：深入追问还是进入下一个知识点
4. 如果回答不完整，追问直到满意或最多追问2次
5. 考察结束后，输出 JSON 格式的评判结果：
   {"score": 0-100, "evaluation": "...", "weak_points": ["..."]}
6. 语气：专业、严肃但不刁难，用中文
7. 只输出上述 JSON，不要包含任何其他文字说明
""".strip()


# ──────────────────────────────────────────────
# AI 对话服务类
# ──────────────────────────────────────────────

class AIService:
    """DeepSeek API 客户端 + 对话管理"""

    # 最大重试次数
    MAX_RETRIES = 3
    # 重试间隔基数（秒）
    RETRY_BASE_DELAY = 1.0

    def __init__(self, config: Optional[dict] = None):
        """
        初始化 AIService

        参数:
            config: 配置字典，若为 None 则自动从 config.yaml 加载
        """
        if config is None:
            config = get_config()

        deepseek_config = config.get("deepseek", {})
        self.api_key = deepseek_config.get("api_key", "")
        self.base_url = deepseek_config.get("base_url", "https://api.deepseek.com")
        self.chat_model = deepseek_config.get("chat_model", "deepseek-chat")

        # 构建 API 端点 URL
        self._api_url = f"{self.base_url.rstrip('/')}/v1/chat/completions"

        # 创建可复用的 httpx 异步客户端
        self._client: Optional[httpx.AsyncClient] = None

        # 初始化 EmbeddingService（如果可用）
        self.embedding_service = None
        if _embedding_available and EmbeddingService is not None:
            try:
                self.embedding_service = EmbeddingService()
            except Exception:
                self.embedding_service = None

    async def _get_client(self) -> httpx.AsyncClient:
        """
        获取或创建 httpx 异步客户端（惰性初始化）

        返回:
            httpx.AsyncClient: 已配置的异步 HTTP 客户端
        """
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(60.0),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def close(self):
        """关闭 HTTP 客户端，释放连接资源"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ──────────────────────────────────────────
    # 核心 API 调用
    # ──────────────────────────────────────────

    async def chat(
        self,
        messages: list[dict],
        stream: bool = True,
        system_prompt: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """
        调用 DeepSeek Chat API

        参数:
            messages: 对话历史，格式 [{"role": "user/assistant", "content": "..."}]
            stream: 是否流式返回
            system_prompt: 可选的系统提示词，会插入到 messages 最前面

        生成:
            str: 流式模式时逐块 yield 文本内容；非流式时 yield 完整响应

        异常:
            httpx.HTTPError: 网络请求错误
        """
        # 构建完整的消息列表
        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        payload = {
            "model": self.chat_model,
            "messages": full_messages,
            "stream": stream,
        }

        last_error = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                client = await self._get_client()
                async with client.stream("POST", self._api_url, json=payload) as response:
                    response.raise_for_status()

                    if stream:
                        async for line in response.aiter_lines():
                            if line and line.startswith("data: "):
                                data_str = line[len("data: "):]
                                if data_str.strip() == "[DONE]":
                                    break
                                try:
                                    data = json.loads(data_str)
                                    delta = data.get("choices", [{}])[0].get("delta", {})
                                    content = delta.get("content", "")
                                    if content:
                                        yield content
                                except (json.JSONDecodeError, KeyError, IndexError):
                                    continue
                    else:
                        # 非流式——收集全部文本后一次性 yield
                        full_text = ""
                        async for line in response.aiter_lines():
                            if line and line.startswith("data: "):
                                data_str = line[len("data: "):]
                                if data_str.strip() == "[DONE]":
                                    break
                                try:
                                    data = json.loads(data_str)
                                    delta = data.get("choices", [{}])[0].get("delta", {})
                                    content = delta.get("content", "")
                                    if content:
                                        full_text += content
                                except (json.JSONDecodeError, KeyError, IndexError):
                                    continue
                        yield full_text
                return  # 成功，退出重试循环

            except (httpx.HTTPError, httpx.TimeoutException) as e:
                last_error = e
                if attempt < self.MAX_RETRIES:
                    delay = self.RETRY_BASE_DELAY * (2 ** (attempt - 1))
                    await asyncio.sleep(delay)
                else:
                    raise RuntimeError(
                        f"DeepSeek API 调用失败（已重试 {self.MAX_RETRIES} 次）: {last_error}"
                    ) from last_error

    async def chat_sync(
        self,
        messages: list[dict],
        system_prompt: Optional[str] = None,
    ) -> str:
        """
        非流式对话——收集完整响应后返回字符串

        参数:
            messages: 对话历史
            system_prompt: 可选的系统提示词

        返回:
            str: AI 完整回复
        """
        result = ""
        async for chunk in self.chat(messages, stream=True, system_prompt=system_prompt):
            result += chunk
        return result

    # ──────────────────────────────────────────
    # 带知识库检索的对话（核心方法）
    # ──────────────────────────────────────────

    async def chat_with_kb(
        self,
        user_message: str,
        conversation_id: int,
        db: Session,
        kb_id: Optional[int] = None,
    ) -> AsyncGenerator[str, None]:
        """
        带知识库检索的对话（核心方法）

        处理流程：
        1. 用 embedding_service.search() 检索相关知识
        2. 构建系统提示词（包含检索结果）
        3. 拼接对话历史
        4. 调用 DeepSeek 流式返回
        5. 保存用户消息和 AI 回复到 Message 表
        6. 记录引用的文档 ID

        参数:
            user_message: 用户最新消息
            conversation_id: 对话 ID
            db: 数据库会话
            kb_id: 可选的知识库 ID，限定检索范围

        生成:
            str: 流式逐块返回 AI 回复文本
        """
        # ── 1. 获取对话信息 ──
        conversation = db.query(Conversation).filter(
            Conversation.id == conversation_id
        ).first()
        if not conversation:
            yield "错误：对话不存在。"
            return

        # ── 2. 知识库检索 ──
        retrieved_docs = []
        retrieved_chunks = []

        if self.embedding_service is not None:
            try:
                # 调用 knowledge-agent 的检索接口
                # embedding_service.search(query, top_k=5, kb_id=None) -> list[dict]
                effective_kb_id = kb_id or conversation.scope_kb_id
                results = self.embedding_service.search(
                    db=db,
                    query=user_message,
                    top_k=5,
                    kb_id=effective_kb_id,
                )
                if results:
                    retrieved_docs = results
                    retrieved_chunks = [item.get("content", "") for item in results]
            except Exception as e:
                # 检索失败时不中断对话，仅记录为无检索结果
                print(f"[RAG] 知识库检索失败: {e}")
        else:
            # TODO: knowledge-agent 尚未完成 EmbeddingService，
            #       此处暂时跳过检索，直接使用对话历史进行回复。
            #       待 knowledge-agent 完成后，移除本 else 分支。
            pass

        # ── 3. 构建系统提示词 ──
        mode = conversation.mode or "kb_qa"

        if mode == "free_chat":
            system_prompt = SYSTEM_PROMPT_FREE_CHAT
        elif mode == "scope_locked":
            system_prompt = SYSTEM_PROMPT_SCOPE_LOCKED
        else:
            # 默认 kb_qa 模式
            if retrieved_chunks:
                parts = []
                for i, doc in enumerate(retrieved_docs):
                    header = f"【知识库：{doc.get('kb_name') or '未知'}】" \
                             f"【文档：{doc.get('document_title') or '未知'}】" \
                             f"【相关度：{doc.get('score', 0):.0%}】"
                    parts.append(f"{header}\n{doc.get('content', '')}")
                kb_context = "\n\n---\n\n".join(parts)
                system_prompt = (
                    SYSTEM_PROMPT_KB_QA
                    + "\n\n--- 以下是知识库检索结果，请基于此回答 ---\n\n"
                    + kb_context
                )
            else:
                system_prompt = SYSTEM_PROMPT_KB_QA + "\n\n（注意：本次未检索到相关知识库内容，请如实告知用户）"

        # ── 4. 获取对话历史 ──
        history_messages = (
            db.query(Message)
            .filter(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
            .all()
        )
        messages_for_api = [
            {"role": msg.role, "content": msg.content}
            for msg in history_messages
        ]
        messages_for_api.append({"role": "user", "content": user_message})

        # ── 5. 保存用户消息 ──
        user_msg = Message(
            conversation_id=conversation_id,
            role="user",
            content=user_message,
        )
        db.add(user_msg)
        db.commit()

        # ── 6. 调用 AI 并流式返回 ──
        full_response = ""
        try:
            async for chunk in self.chat(
                messages=messages_for_api,
                stream=True,
                system_prompt=system_prompt,
            ):
                full_response += chunk
                yield chunk
        except Exception as e:
            error_msg = f"AI 服务暂时不可用：{str(e)}"
            yield error_msg
            full_response = error_msg

        # ── 7. 保存 AI 回复 ──
        # 提取引用的文档 ID
        referenced_doc_ids = None
        if retrieved_docs:
            doc_ids = list(set(
                item.get("document_id") for item in retrieved_docs if item.get("document_id")
            ))
            if doc_ids:
                referenced_doc_ids = json.dumps(doc_ids, ensure_ascii=False)

        assistant_msg = Message(
            conversation_id=conversation_id,
            role="assistant",
            content=full_response,
            referenced_docs=referenced_doc_ids,
        )
        db.add(assistant_msg)
        db.commit()

    # ──────────────────────────────────────────
    # 对话标题生成
    # ──────────────────────────────────────────

    async def generate_title(self, first_message: str) -> str:
        """
        根据用户第一条消息生成对话标题

        参数:
            first_message: 用户的第一条消息内容

        返回:
            str: 生成的对话标题（不超过30字）
        """
        title_prompt = (
            "请根据以下用户消息，生成一个简洁的对话标题（不超过30字）。"
            "只输出标题文本，不要加引号或其他修饰。\n\n"
            f"用户消息：{first_message}"
        )
        messages = [{"role": "user", "content": title_prompt}]
        title = await self.chat_sync(messages)
        return title.strip()[:50]  # 截断防止过长


# ──────────────────────────────────────────────
# 全局单例
# ──────────────────────────────────────────────

_ai_service_instance: Optional[AIService] = None


def get_ai_service() -> AIService:
    """
    获取 AIService 全局单例

    返回:
        AIService: AI 服务实例
    """
    global _ai_service_instance
    if _ai_service_instance is None:
        _ai_service_instance = AIService()
    return _ai_service_instance
