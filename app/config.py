"""
配置管理模块

功能：
- 读取项目根目录的 config.yaml 配置文件
- 自动加载 .env 文件中的环境变量
- 支持环境变量覆盖（如 DEEPSEEK_API_KEY 覆盖 yaml 中的 api_key）
- 自动创建必要的目录（data/、uploads/）
"""

import os
import yaml

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 配置文件路径
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.yaml")

# 缓存已加载的配置
_config_cache = None


def _load_raw_config() -> dict:
    """从 YAML 文件加载原始配置，若文件不存在则返回空字典"""
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f"配置文件不存在: {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_config() -> dict:
    """
    获取完整配置（含环境变量覆盖）

    环境变量覆盖规则：
    - DEEPSEEK_API_KEY   → deepseek.api_key
    - DEEPSEEK_BASE_URL  → deepseek.base_url
    - DEEPSEEK_CHAT_MODEL → deepseek.chat_model

    返回:
        dict: 完整配置字典，所有路径均为基于项目根目录的绝对路径
    """
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    config = _load_raw_config()

    # 环境变量覆盖
    if os.environ.get("DEEPSEEK_API_KEY"):
        config.setdefault("deepseek", {})["api_key"] = os.environ["DEEPSEEK_API_KEY"]
    if os.environ.get("DEEPSEEK_BASE_URL"):
        config.setdefault("deepseek", {})["base_url"] = os.environ["DEEPSEEK_BASE_URL"]
    if os.environ.get("DEEPSEEK_CHAT_MODEL"):
        config.setdefault("deepseek", {})["chat_model"] = os.environ["DEEPSEEK_CHAT_MODEL"]

    # 将相对路径转为基于项目根目录的绝对路径
    db_config = config.setdefault("database", {})
    db_config["sqlite_path"] = os.path.join(PROJECT_ROOT, db_config.get("sqlite_path", "data/knowledge.db"))
    db_config["chromadb_path"] = os.path.join(PROJECT_ROOT, db_config.get("chromadb_path", "data/chroma"))

    _config_cache = config
    return config


def ensure_directories() -> None:
    """确保必要的目录存在：data/、uploads/"""
    config = get_config()

    # data 目录（数据库文件和 ChromaDB 数据）
    data_dir = os.path.dirname(config["database"]["sqlite_path"])
    os.makedirs(data_dir, exist_ok=True)

    # ChromaDB 目录
    chroma_dir = config["database"]["chromadb_path"]
    os.makedirs(chroma_dir, exist_ok=True)

    # uploads 目录
    uploads_dir = os.path.join(PROJECT_ROOT, "uploads")
    os.makedirs(uploads_dir, exist_ok=True)
