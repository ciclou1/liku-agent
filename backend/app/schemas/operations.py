from pydantic import BaseModel, Field
from pydantic import SecretStr
from typing import Literal


class SafetyStockPayload(BaseModel):
    category: str = Field(min_length=1, max_length=80)
    quantity: float = Field(ge=0)
    service_level: float = Field(default=0.95, gt=0, le=1)


class WarningRulePayload(BaseModel):
    warning_type: str = Field(min_length=1, max_length=30)
    threshold: float = Field(ge=0)
    level: str = Field(min_length=1, max_length=20)
    scope: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True


class PriceTargetPayload(BaseModel):
    sku: str = Field(min_length=1, max_length=80)
    enabled: bool = True


class RecommendationStatusPayload(BaseModel):
    status: str | None = Field(default=None, pattern="^(reviewed|exported|pushed)$")
    purchase_quantity: float | None = Field(default=None, ge=0)


class SyncRequest(BaseModel):
    adapter_name: str = Field(min_length=1, max_length=80)
    mode: str = Field(default="incremental", pattern="^(incremental|full)$")


class DatabaseSwitchRequest(BaseModel):
    database_type: str = Field(min_length=1, max_length=30)
    database_url: str = Field(min_length=8, max_length=500)


class DatabaseSourceRequest(BaseModel):
    database_type: Literal["mysql", "postgresql", "dameng", "sqlite"]
    name: str = Field(default="", max_length=100)
    host: str = Field(default="", max_length=253)
    port: int = Field(default=3306, ge=1, le=65535)
    username: str = Field(default="", max_length=128)
    password: SecretStr = SecretStr("")
    database: str = Field(min_length=1, max_length=200)
