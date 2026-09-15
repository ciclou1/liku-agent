"""ERP MySQL 只读客户端。

安全约束：
- 仅执行 SELECT（statement 拦截校验），不提供任何写路径；
- 连接参数来自 Settings（erp_db_*），密码不入库不入日志；
- 每次查询独立短连接，避免跨事件循环共享连接。
"""

from __future__ import annotations

import logging
import re
from typing import Any

import pymysql

from app.core.config import get_settings
from app.exceptions import BusinessError

logger = logging.getLogger(__name__)


class ErpQueryError(BusinessError):
    def __init__(self, message: str) -> None:
        super().__init__(code="ERP_QUERY_FAILED", message=message)


def _assert_readonly(sql: str) -> None:
    stripped = sql.strip().rstrip(";").lower()
    if not stripped.startswith("select"):
        raise ErpQueryError("ERP 通道仅允许 SELECT 查询")
    for keyword in ("insert", "update", "delete", "drop", "alter", "create", "truncate", "grant", "call", "set"):
        # 只拦截语句头与子句注入式写操作；列名/字符串中出现关键字的正常查询不受影响
        if f";{keyword}" in stripped or stripped.startswith(keyword):
            raise ErpQueryError(f"ERP 通道检测到非只读语句: {keyword}")


class ErpClient:
    """同步短连接客户端；FastAPI 同步路由会自动在线程池中执行。"""

    def fetch_all(self, sql: str, params: tuple | list | None = None, limit: int = 500) -> list[dict[str, Any]]:
        _assert_readonly(sql)
        settings = get_settings()
        body = sql.strip().rstrip(";")
        # SQL 已带 LIMIT 时沿用原值，否则追加兜底 LIMIT
        if not re.search(r"\blimit\s+\d+\s*$", body, flags=re.IGNORECASE):
            body = f"{body} LIMIT {int(limit)}"
        final_sql = body
        try:
            conn = pymysql.connect(
                host=settings.erp_db_host,
                port=settings.erp_db_port,
                user=settings.erp_db_user,
                password=settings.erp_db_password,
                database=settings.erp_db_name,
                charset="utf8mb4",
                connect_timeout=settings.erp_connect_timeout_seconds,
                read_timeout=settings.erp_query_timeout_seconds,
                cursorclass=pymysql.cursors.DictCursor,
            )
        except pymysql.MySQLError as exc:
            logger.error("ERP 连接失败: %s", exc)
            raise ErpQueryError("ERP 数据库连接失败，请检查网络与账号配置") from exc
        try:
            with conn.cursor() as cursor:
                cursor.execute(final_sql, params or ())
                rows = cursor.fetchall()
                return list(rows)
        except pymysql.MySQLError as exc:
            logger.error("ERP 查询失败: %s", exc)
            raise ErpQueryError("ERP 查询执行失败") from exc
        finally:
            conn.close()

    def ping(self) -> bool:
        try:
            self.fetch_all("SELECT 1 AS ok", limit=1)
            return True
        except BusinessError:
            return False
