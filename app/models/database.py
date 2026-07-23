"""
SQLAlchemy 数据库连接模块

功能：
- 创建 SQLite 数据库引擎
- 提供会话工厂和依赖注入函数（FastAPI 风格）
- 提供声明式基类和数据库初始化函数
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import get_config, ensure_directories

# 确保目录存在
ensure_directories()

# 获取数据库路径
config = get_config()
DATABASE_URL = f"sqlite:///{config['database']['sqlite_path']}"

# 创建引擎（check_same_thread=False 是 SQLite 异步/多线程访问所必需的）
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,  # 生产环境不输出 SQL 日志
)

# 创建会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 声明式基类——所有 ORM 模型继承自此类
Base = declarative_base()


def get_db():
    """
    FastAPI 依赖注入——获取数据库会话

    用法:
        @app.get("/items")
        def read_items(db: Session = Depends(get_db)):
            ...

    自动在请求结束后关闭会话，确保连接不泄漏。
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """
    初始化数据库——根据所有导入的 ORM 模型自动创建表

    应在应用启动时调用一次。使用 create_all 会根据 Base.metadata
    中已注册的所有模型创建对应的数据库表（若表已存在则跳过）。
    """
    # 导入所有模型，确保它们注册到 Base.metadata
    import app.models.schema  # noqa: F401

    # 创建所有表
    Base.metadata.create_all(bind=engine)

    # SQLite 迁移：为已有表添加新列（若不存在则添加）
    _migrate_sqlite_columns()


def _migrate_sqlite_columns() -> None:
    """
    SQLite 列迁移 —— 为已存在的表安全添加新列

    SQLite 的 ALTER TABLE 只支持 ADD COLUMN，且仅在列不存在时才执行。
    """
    import sqlite3
    from app.config import get_config as _get_config

    cfg = _get_config()
    db_path = cfg["database"]["sqlite_path"]

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 获取 exam_questions 表的已有列
    cursor.execute("PRAGMA table_info(exam_questions)")
    existing_cols = {row[1] for row in cursor.fetchall()}

    migrations = [
        ("model_answer", "TEXT"),
        ("extensions", "TEXT"),
    ]

    for col_name, col_type in migrations:
        if col_name not in existing_cols:
            cursor.execute(
                f"ALTER TABLE exam_questions ADD COLUMN {col_name} {col_type}"
            )
            print(f"[Migration] 已添加列 exam_questions.{col_name}")

    conn.commit()
    conn.close()
