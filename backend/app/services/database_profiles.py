import json
import re
import asyncio
from pathlib import Path
from sqlalchemy import URL, text
from sqlalchemy.ext.asyncio import create_async_engine
from app.schemas.operations import DatabaseSourceRequest

from app.core.config import Settings, get_active_database_profile, infer_database_type


DATABASE_PROFILES = {
    "sqlite": {"label": "SQLite", "example": "sqlite+aiosqlite:///./storage/liku.db", "runtime": True},
    "mysql": {"label": "MySQL 8", "example": "mysql+aiomysql://user:password@host:3306/database", "runtime": True},
    "postgresql": {"label": "PostgreSQL", "example": "postgresql+asyncpg://user:password@host:5432/database", "runtime": True},
    "dameng": {"label": "达梦 DM", "example": "dm+dmPython://user:password@host:5236?schema=SYSDBA", "runtime": True},
}


def validate_database_profile(database_type: str, database_url: str) -> None:
    if database_type not in DATABASE_PROFILES:
        raise ValueError(f"不支持的数据库类型: {database_type}")
    url = database_url.strip().lower()
    valid_prefixes = {
        "sqlite": ("sqlite+aiosqlite://", "sqlite://"),
        "mysql": ("mysql+aiomysql://", "mysql://"),
        "postgresql": ("postgresql+asyncpg://", "postgresql://", "postgres://"),
        "dameng": ("dm+", "dm://", "dameng://"),
    }
    if not url.startswith(valid_prefixes[database_type]):
        raise ValueError(f"{database_type} 的连接串格式不匹配")
    if database_type == "dameng" and "dmpython" not in url and "asyncdm" not in url:
        raise ValueError("达梦需要 dmPython 或 asyncdm SQLAlchemy 驱动连接串")


def masked_database_url(database_url: str) -> str:
    return re.sub(r"(://[^:/?#]+:)[^@]+(@)", r"\1******\2", database_url)


def current_database_config(settings: Settings) -> dict[str, object]:
    profile = get_active_database_profile(settings)
    return {"database_type": profile["database_type"], "database_url": masked_database_url(profile["database_url"]), "profiles": DATABASE_PROFILES, "restart_required": False}


def persist_database_profile(settings: Settings, database_type: str, database_url: str) -> dict[str, object]:
    validate_database_profile(database_type, database_url)
    path = Path(settings.database_config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"database_type": database_type, "database_url": database_url}, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"database_type": database_type, "database_url": masked_database_url(database_url), "restart_required": True, "message": "数据库配置已保存，重启 API/worker/beat 后生效"}


def source_url(source: DatabaseSourceRequest) -> str:
    if source.database_type == "sqlite":
        # Relative paths stay in application storage; no arbitrary file probing.
        if not re.fullmatch(r"[A-Za-z0-9_-]+\.db", source.database):
            raise ValueError("SQLite 数据库名应为 example.db，不允许目录路径")
        return URL.create("sqlite+aiosqlite", database=f"./storage/{source.database}").render_as_string(hide_password=False)
    if not source.host.strip() or not source.username.strip() or not source.password.get_secret_value():
        raise ValueError("请填写主机、用户名和密码")
    drivers = {"mysql": "mysql+aiomysql", "postgresql": "postgresql+asyncpg", "dameng": "dm+dmPython"}
    return URL.create(drivers[source.database_type], username=source.username, password=source.password.get_secret_value(), host=source.host.strip(), port=source.port, database=source.database).render_as_string(hide_password=False)


async def test_source(source: DatabaseSourceRequest) -> dict:
    url = source_url(source)
    if source.database_type == "dameng":
        raise ValueError("当前异步运行环境尚未适配达梦 dmPython，暂不能测试或启用；请先部署兼容驱动适配层")
    candidate = None
    try:
        async with asyncio.timeout(8):
            candidate = create_async_engine(url, hide_parameters=True)
            async with candidate.connect() as connection:
                await connection.execute(text("SELECT 1"))
    except (ImportError, ModuleNotFoundError):
        raise ValueError("当前服务未安装此数据库所需驱动") from None
    except Exception:
        raise ValueError("连接测试失败，请检查主机、端口、数据库名、账号权限和网络") from None
    finally:
        if candidate is not None:
            await candidate.dispose()
    return {"database_url": masked_database_url(url), "message": "连接测试成功", "tested": True}
