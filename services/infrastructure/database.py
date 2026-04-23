"""
数据库连接管理模块

使用SQLAlchemy管理数据库连接，提供：
1. 数据库连接池
2. 会话管理
3. 数据库初始化
"""
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session as DBSession, scoped_session
from sqlalchemy.pool import QueuePool

from config import Config
from models.database import Base

# 注册 pgvector 类型适配器
try:
    from services.pgvector_adapter import register_vector_adapter
    register_vector_adapter()
except ImportError:
    pass


class DatabaseManager:
    """数据库管理器"""
    
    def __init__(self, database_url: str = None):
        """
        初始化数据库管理器
        
        Args:
            database_url: 数据库连接URL，默认从配置读取
        """
        self.database_url = database_url or Config.DATABASE_URL
        
        # 创建引擎，配置连接池
        self.engine = create_engine(
            self.database_url,
            poolclass=QueuePool,
            pool_size=5,           # 连接池大小
            max_overflow=10,       # 最大溢出连接数
            pool_timeout=30,       # 获取连接超时时间
            pool_recycle=3600,     # 连接回收时间（秒）
            echo=Config.DEBUG      # 是否输出SQL日志
        )
        
        # 创建会话工厂（线程安全）
        self.session_factory = sessionmaker(
            bind=self.engine,
            autocommit=False,
            autoflush=False
        )
        
        # 创建scoped_session，确保每个线程有自己的session
        self.scoped_session = scoped_session(self.session_factory)
    
    def init_db(self):
        """初始化数据库（创建所有表）"""
        Base.metadata.create_all(self.engine)
        print("数据库表创建成功")
    
    def drop_db(self):
        """删除所有表（谨慎使用）"""
        Base.metadata.drop_all(self.engine)
        print("[警告] 数据库表已删除")
    
    @contextmanager
    def get_session(self) -> Generator[DBSession, None, None]:
        """
        获取数据库会话（上下文管理器）
        
        使用示例:
            with db_manager.get_session() as session:
                session.add(obj)
                session.commit()
        
        Yields:
            SQLAlchemy Session对象
        """
        session = self.scoped_session()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()
    
    def get_new_session(self) -> DBSession:
        """
        获取新的数据库会话（手动管理）
        
        注意：使用后需要手动关闭
        
        Returns:
            SQLAlchemy Session对象
        """
        return self.session_factory()
    
    def close(self):
        """关闭数据库连接池"""
        self.scoped_session.remove()
        self.engine.dispose()


# 创建全局实例
db_manager = DatabaseManager()


# 导出
__all__ = ['DatabaseManager', 'db_manager']
