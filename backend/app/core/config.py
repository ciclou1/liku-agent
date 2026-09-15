from functools import lru_cache
import json
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# cc-switch 等 Claude Code 代理工具注入的占位令牌（命中则回退读 .env 文件真实值）
_PROXY_TOKEN_PLACEHOLDERS = {"", "PROXY_MANAGED", "sk-xxx", "change-me"}


class Settings(BaseSettings):
    app_name: str = "平衡利库智能体"
    app_env: str = "development"
    app_secret_key: str = "development-only-secret"
    database_url: str = "sqlite+aiosqlite:///./storage/liku.db"
    database_config_path: str = "./storage/database-profile.json"
    redis_url: str = "redis://localhost:6379/0"
    storage_path: str = "./storage"
    llm_provider: str = "stub"
    anthropic_base_url: str = "https://www.ai.atyou.cn"
    anthropic_auth_token: str = ""
    anthropic_model: str = "glm-5.3-flash"
    llm_timeout_seconds: int = Field(default=30, ge=1, le=120)
    open_api_app_key: str = "demo-app"
    open_api_app_secret: str = "change-me"
    # 生产默认不生成模拟库存；测试夹具可显式打开。
    demo_seed: bool = False
    wecom_webhook_url: str = ""
    dingtalk_webhook_url: str = ""
    feishu_webhook_url: str = ""
    oidc_issuer_url: str = ""
    oidc_audience: str = ""
    oidc_jwks_url: str = ""
    ldap_url: str = ""
    ldap_base_dn: str = ""
    ldap_bind_dn: str = ""
    ldap_bind_password: str = ""
    cas_validate_url: str = ""
    # 积木 ERP（Maximo 底层）只读直连配置
    erp_db_host: str = "172.20.0.114"
    erp_db_port: int = 3306
    erp_db_user: str = "php_saas"
    erp_db_password: str = ""
    erp_db_name: str = "php_saas"
    erp_site_id: str = "PHP"
    erp_connect_timeout_seconds: int = 5
    erp_query_timeout_seconds: int = 30
    erp_analysis_cache_ttl_seconds: int = 300
    # 允许 iframe 嵌入的来源（积木 ERP 页面嵌入时填其 origin，如 http://172.20.0.125:8080；空 = 禁止嵌入）
    frame_ancestors: str = "http://172.20.0.125:8080"
    # 允许跨域访问 API 的额外来源（嵌入页前端直连后端时需要）
    cors_origins: str = "http://localhost:5173,http://172.20.0.125:8080"
    # 是否允许嵌入页公开换取 ERP 只读 token（默认关闭；上线应接 ERP SSO 或服务端签发）
    # 开发联调时在 .env 显式置 ERP_PUBLIC_READ=true
    erp_public_read: bool = False

    # 兼容两种运行位置：backend/ 就近 .env 优先，其次仓库根 .env（本地直跑 uvicorn 场景）
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore")

    @model_validator(mode="before")
    @classmethod
    def _ignore_proxy_injected_llm_env(cls, values):
        """cc-switch 等 Claude Code 代理工具会向子进程注入 ANTHROPIC_BASE_URL/AUTH_TOKEN
        （如 AUTH_TOKEN=PROXY_MANAGED、BASE_URL=127.0.0.1:端口），覆盖 .env 的真实配置，
        导致 LLM 请求打到代理网关而偶发空回复。检测到占位令牌时，回退读取 .env 文件中的值。"""
        token = str(values.get("anthropic_auth_token") or "")
        if token not in _PROXY_TOKEN_PLACEHOLDERS:
            return values
        for env_file in cls.model_config.get("env_file") or ():
            path = Path(env_file)
            if not path.exists():
                continue
            file_vals: dict[str, str] = {}
            for line in path.read_text(encoding="utf-8-sig").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    file_vals[key.strip()] = val.strip()
            real_token = file_vals.get("ANTHROPIC_AUTH_TOKEN", "")
            if real_token and real_token not in _PROXY_TOKEN_PLACEHOLDERS:
                values["anthropic_auth_token"] = real_token
                injected_url = str(values.get("anthropic_base_url") or "")
                file_url = file_vals.get("ANTHROPIC_BASE_URL", "")
                if file_url and injected_url.startswith(("http://127.0.0.1", "http://localhost")):
                    values["anthropic_base_url"] = file_url
                break
        return values


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def get_active_database_profile(settings: Settings | None = None) -> dict[str, str]:
    settings = settings or get_settings()
    profile = {"database_type": infer_database_type(settings.database_url), "database_url": settings.database_url}
    if settings.app_env == "test":
        return profile
    path = Path(settings.database_config_path)
    if not path.exists():
        return profile
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return profile
    if isinstance(stored, dict) and stored.get("database_url"):
        return {"database_type": str(stored.get("database_type") or infer_database_type(str(stored["database_url"]))), "database_url": str(stored["database_url"])}
    return profile


def infer_database_type(database_url: str) -> str:
    scheme = database_url.split(":", 1)[0].lower()
    if scheme.startswith("mysql"):
        return "mysql"
    if scheme.startswith("postgres"):
        return "postgresql"
    if scheme.startswith("sqlite"):
        return "sqlite"
    if scheme.startswith("dm") or "dameng" in scheme:
        return "dameng"
    return "custom"
