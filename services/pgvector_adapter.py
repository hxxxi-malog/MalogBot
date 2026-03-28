"""
注册 pgvector 类型适配器

解决 psycopg2 无法识别 vector 类型的问题
"""
import psycopg2
from psycopg2 import sql
from psycopg2.extensions import register_adapter, adapt, AsIs


def register_vector_adapter():
    """注册 pgvector 的 vector 类型适配器"""
    try:
        # 尝试注册 vector 类型的适配器
        import numpy as np
        
        def adapt_vector(value):
            """将 vector 类型转换为 PostgreSQL 格式"""
            if hasattr(value, '__iter__'):
                # 如果是列表或数组，转换为字符串格式
                return AsIs(f"'[{','.join(map(str, value))}]'::vector")
            return AsIs(f"'{value}'::vector")
        
        # 注册 numpy 数组的适配器
        register_adapter(np.ndarray, adapt_vector)
        
        print("[pgvector] 类型适配器注册成功")
    except ImportError:
        print("[pgvector] numpy 未安装，跳过适配器注册")
    except Exception as e:
        print(f"[pgvector] 适配器注册失败: {e}")


def register_vector_oid(conn):
    """
    注册 vector 类型的 OID
    
    这需要在连接建立后调用
    """
    try:
        with conn.cursor() as cur:
            # 获取 vector 类型的 OID
            cur.execute("SELECT oid FROM pg_type WHERE typname = 'vector'")
            result = cur.fetchone()
            if result:
                vector_oid = result[0]
                
                # 获取 vector 数组类型的 OID
                cur.execute("SELECT oid FROM pg_type WHERE typname = '_vector'")
                array_result = cur.fetchone()
                
                print(f"[pgvector] vector OID: {vector_oid}")
                if array_result:
                    print(f"[pgvector] _vector OID: {array_result[0]}")
                
                return vector_oid
    except Exception as e:
        print(f"[pgvector] 获取 OID 失败: {e}")
    
    return None


# 自动注册
register_vector_adapter()
