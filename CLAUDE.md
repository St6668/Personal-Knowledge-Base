# CLAUDE.md

此文件为 Claude Code 在此仓库中工作时提供指导。

## 项目概述

个人知识库系统 —— 支持多格式知识上传、AI 智能问答、学习计划生成和面试式考察的 Web 应用。

详细设计文档见：`docs/superpowers/specs/2026-07-23-个人知识库-设计文档.md`

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | FastAPI (Python 3.11+) |
| 数据库 | SQLite + SQLAlchemy |
| 向量库 | ChromaDB（本地持久化） |
| AI 生成 | DeepSeek Chat API |
| AI 嵌入 | BAAI/bge-small-zh-v1.5（本地运行） |
| 前端 | Jinja2 模板 + 原生 CSS/JS |

## 常用命令

```bash
# 安装依赖
pip install -r requirements.txt

# 启动开发服务器
python run.py

# 或直接使用 uvicorn
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

## 项目结构

```
personal-kb/
├── app/
│   ├── main.py              # FastAPI 入口，注册路由
│   ├── config.py            # 配置管理（读取 config.yaml）
│   ├── routers/             # API 路由层
│   │   ├── knowledge.py     #   知识管理 /knowledge
│   │   ├── chat.py          #   AI 对话   /chat
│   │   ├── plan.py          #   学习计划  /plan
│   │   └── exam.py          #   考察     /exam
│   ├── services/            # 业务逻辑层
│   │   ├── document.py      #   文档解析 + 分块
│   │   ├── embedding.py     #   BGE 向量化 + ChromaDB 操作
│   │   ├── chat.py          #   DeepSeek API + 对话管理
│   │   ├── plan.py          #   学习计划生成
│   │   └── exam.py          #   面试考察逻辑
│   ├── models/
│   │   ├── database.py      #   SQLAlchemy 连接
│   │   └── schema.py        #   数据表 ORM 模型（契约文件）
│   ├── templates/           # Jinja2 模板
│   └── static/              # CSS/JS 静态资源
├── data/                    # SQLite + ChromaDB 数据文件
├── uploads/                 # 上传文件存储
├── config.yaml              # 用户配置（API Key 等）
├── requirements.txt
└── run.py                   # 启动脚本
```

## 架构要点

### 职责分离

- **路由层** (`routers/`)：处理 HTTP 请求/响应，参数校验，**不包含业务逻辑**
- **服务层** (`services/`)：业务逻辑实现，**不处理 HTTP 细节**
- **模型层** (`models/`)：`schema.py` 是契约文件，定义所有数据表，同时被 knowledge-agent 和 ai-agent 使用

### AI 分工

```
DeepSeek Chat API（云端）── 生成答案、出题、评判
BGE Embedding（本地）────── 文本向量化、语义检索
```

- `EmbeddingService.search()` 是 knowledge-agent 提供给 ai-agent 的**核心检索接口**
- ai-agent 通过此接口获取相关文档片段，拼接后发给 DeepSeek

### RAG 数据流

```
文档上传 → 解析 → 分块 → BGE向量化 → ChromaDB存储
用户提问 → BGE向量化 → ChromaDB检索 → 拼接→ DeepSeek生成 → 返回
```

### 路由前缀

| 模块 | 前缀 | 负责 Agent |
|------|------|------------|
| 知识管理 | `/knowledge` | knowledge-agent |
| AI 对话 | `/chat` | ai-agent |
| 学习计划 | `/plan` | ai-agent |
| 考察 | `/exam` | ai-agent |

## 多 Agent 协作

本项目定义 4 个专用 Agent（定义文件在 `.claude/agents/`），按顺序执行：

| 顺序 | Agent | 职责 |
|------|-------|------|
| 第1步 | `foundation-agent` | 项目骨架、配置、数据库模型 |
| 第2步 | `knowledge-agent` + `ai-agent` | 并行：知识管理+A I交互 |
| 第3步 | `frontend-agent` | 前端界面（必须使用 frontend-design 技能） |

## 开发约定

- **所有注释、文档字符串、变量名、界面文本必须使用中文**
- `app/models/schema.py` 是契约文件，不得被 knowledge-agent 和 ai-agent 修改
- 前端开发**必须调用 frontend-design 技能**进行视觉设计
- 配置文件 `config.yaml` 是模板，不可写入真实 API Key
- API 响应使用 Pydantic 模型序列化
- 流式响应使用 SSE（Server-Sent Events）
- 数据库操作通过 `get_db()` 依赖注入

## MVP 边界

以下功能明确不作为 MVP 范围：
- 用户认证/多用户
- 前后端分离
- 图片 OCR、网页抓取
- 定时提醒/邮件通知
- 移动端适配
- 自动间隔重复算法
