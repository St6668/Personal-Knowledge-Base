# 个人知识库系统

一个面向个人使用的知识库管理系统，支持多格式知识上传、AI 驱动的智能问答、学习计划生成和面试式考察。

## 功能模块

| 模块 | 说明 |
|------|------|
| **知识管理** | 支持 PDF / Word / TXT / Markdown / XMind 上传，在线编写笔记，知识库分组 + 标签分类 |
| **AI 对话** | 基于知识库的 RAG 问答（标注引用来源），自由对话，一键保存对话为笔记 |
| **学习计划** | 选定知识范围后 AI 自动生成结构化学习计划，支持模块展开和顺序调整 |
| **AI 考察** | 基于知识点智能出题，模拟面试式问答，AI 评判并给出反馈 |

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | FastAPI (Python 3.11+) |
| 数据库 | SQLite + SQLAlchemy |
| 向量库 | ChromaDB（本地持久化） |
| AI 生成 | DeepSeek Chat API |
| AI 嵌入 | BAAI/bge-small-zh-v1.5（本地运行） |
| 前端 | Jinja2 模板 + 原生 CSS/JS |

## 快速开始

### 环境要求

- Python 3.11+
- pip

### 安装

```bash
# 克隆仓库
git clone <repo-url>
cd Personal

# 安装依赖
pip install -r requirements.txt

# 配置 API Key —— 编辑 config.yaml，填入你的 DeepSeek API Key
# deepseek:
#   api_key: "your-api-key-here"
```

### 启动

```bash
# 开发模式（热重载）
python run.py

# 生产模式（单进程）
python run.py --no-reload
```

浏览器访问 `http://127.0.0.1:8000`

## 项目结构

```
├── app/
│   ├── main.py              # FastAPI 入口
│   ├── config.py            # 配置管理
│   ├── routers/             # 路由层 —— /knowledge, /chat, /plan, /exam
│   ├── services/            # 业务逻辑层 —— 文档解析、向量化、对话、计划、考察
│   ├── models/              # SQLAlchemy 数据模型
│   ├── templates/           # Jinja2 模板
│   └── static/              # CSS/JS 静态资源
├── data/                    # SQLite + ChromaDB 数据文件
├── uploads/                 # 上传文件存储
├── config.yaml              # 用户配置
├── requirements.txt
├── run.py                   # 启动脚本
└── README.md
```

## 配置说明

编辑 `config.yaml`：

```yaml
deepseek:
  api_key: "your-api-key-here"       # DeepSeek API Key
  chat_model: "deepseek-v4-flash"    # 对话模型

embedding:
  model_name: "BAAI/bge-small-zh-v1.5"
  hf_endpoint: "https://hf-mirror.com"  # 国内用户使用 HuggingFace 镜像

server:
  host: "127.0.0.1"
  port: 8000
```

## RAG 数据流

```
文档上传 → 解析 → 分块 → BGE 向量化 → ChromaDB 存储
用户提问 → BGE 向量化 → ChromaDB 检索 → 拼接上下文 → DeepSeek 生成 → 流式返回
```

## MVP 边界

以下功能不作为 MVP 范围：
- 用户认证 / 多用户
- 前后端分离
- 图片 OCR、网页抓取
- 定时提醒 / 邮件通知
- 移动端适配
- 自动间隔重复算法
