import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_access, require_open_rate_limit, require_open_signature, require_role
from app.core.database import get_db
from app.core.config import get_settings
from app.schemas.common import ApiResponse
from app.schemas.domain import ChatRequest, ChatResponse, ForecastCorrection, ForecastResponse, LoginRequest, LoginResponse, PlanningRequest, PriceResponse, PurchaseRequest, PurchaseResponse, TransferPlanningRequest, WarningResponse
from app.schemas.chatbot import SqlPreviewRequest, SqlPreviewResponse
from app.schemas.operations import DatabaseSwitchRequest, PriceTargetPayload, RecommendationStatusPayload, SafetyStockPayload, SyncRequest, WarningRulePayload
from app.core.security import hash_password
from app.services.chatbot import ChatbotService, ControlledSql
from app.services.forecast import ForecastService
from app.services.inventory import InventoryService
from app.services.liku import LikuService
from app.services.price import PriceService
from app.services.warning import WarningService
from app.services.audit import AuditService
from app.services.configuration import ConfigurationService, SafetyStockConfig, WarningRuleConfig
from app.services.integrations import IntegrationService
from app.services.recommendations import RecommendationService
from app.services.tasks import TaskService
from app.im import DingTalkProvider, FeishuProvider, WeComProvider
from app.services.users import UserService
from app.auth.sso import CasProvider, LdapProvider, OidcProvider
from app.core.security import create_access_token
from app.services.access import AccessContext
from app.adapters.excel import ExcelAdapter
from app.data.dictionary import required_fields
from app.services.governance import DataGovernanceService
from app.services.im import ImService
from app.services.domain import DatabaseDomainService
from app.services.narrative import NarrativeService
from app.services.persistence import PersistenceService
from app.services.audit_persistence import AuditPersistenceService
from app.services.database_profiles import current_database_config, persist_database_profile
from app.services.database_profiles import source_url, test_source
from app.services.erp_import import ErpImportService
from app.core.erp_cache import erp_analysis_cache
from app.models import Warehouse
from app.schemas.operations import DatabaseSourceRequest
from app.monitoring.metrics import redis_is_ready

router = APIRouter(prefix="/api/v1")
inventory_service = InventoryService()
forecast_service = ForecastService()
liku_service = LikuService()
price_service = PriceService()
warning_service = WarningService()
chatbot_service = ChatbotService()
audit_service = AuditService()
configuration_service = ConfigurationService()
integration_service = IntegrationService()
recommendation_service = RecommendationService()
task_service = TaskService()
user_service = UserService(hash_password)
governance_service = DataGovernanceService()
im_service = ImService(warning_service, inventory_service)
database_domain_service = DatabaseDomainService()
persistence_service = PersistenceService()
audit_persistence_service = AuditPersistenceService()
narrative_service = NarrativeService()


def readable_purchase_recommendation(recommendation: dict) -> dict:
    basis = recommendation.get("calculation_basis", {})
    timing_labels = {"stock_up": "建议提前备货", "delay": "建议延后采购", "normal": "建议按计划采购"}
    timing = timing_labels.get(str(recommendation.get("timing_signal", "normal")), str(recommendation.get("timing_signal", "normal")))
    if float(recommendation.get("purchase_quantity", 0)) <= 0:
        timing = "当前无需采购"
    warehouse_id = recommendation.get("warehouse_id") or "目标仓库"
    forecast = recommendation.get("forecast_demand", basis.get("forecast_demand", 0))
    summary = f"{recommendation.get('sku', '')} 在 {warehouse_id} 建议采购 {recommendation.get('purchase_quantity', 0)}，预测需求 {forecast}；{timing}。"
    return {
        **recommendation,
        "summary": summary,
        "calculation_basis": {**basis, "summary": summary},
        "calculation_explanation": {
            "forecast_demand": f"预测需求：{forecast}",
            "safety_stock": f"安全库存：{basis.get('safety_stock', 0)}",
            "available_stock": f"可用库存：{basis.get('available_stock', 0)}",
            "in_transit": f"在途库存：{basis.get('in_transit', 0)}",
            "net_gap": f"净缺口 = 预测需求 + 安全库存 - 可用库存 - 在途库存 = {recommendation.get('net_gap', 0)}",
            "package_size": f"最小包装：{basis.get('package_size', 0)}，建议量已按包装取整",
        },
    }


@router.get("/health", response_model=ApiResponse[dict])
async def health() -> ApiResponse[dict]:
    return ApiResponse(data={"status": "ok", "service": "liku-api"})


@router.get("/health/ready", response_model=ApiResponse[dict])
async def readiness(session: AsyncSession = Depends(get_db)) -> ApiResponse[dict]:
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="database is not ready") from exc
    if get_settings().app_env != "test" and not redis_is_ready():
        raise HTTPException(status_code=503, detail="redis is not ready")
    return ApiResponse(data={"status": "ready", "database": "ok"})


@router.get("/materials", response_model=ApiResponse[list[dict]], dependencies=[Depends(current_access)])
async def materials(query: str | None = Query(default=None, max_length=50), limit: int = Query(default=50, ge=1, le=1000), session: AsyncSession = Depends(get_db)) -> ApiResponse[list[dict]]:
    return ApiResponse(data=await database_domain_service.materials(session, query=query, limit=limit))


@router.get("/warehouses", response_model=ApiResponse[list[dict]], dependencies=[Depends(current_access)])
async def warehouses(session: AsyncSession = Depends(get_db)) -> ApiResponse[list[dict]]:
    rows = await session.execute(select(Warehouse).order_by(Warehouse.warehouse_id))
    return ApiResponse(data=[{"warehouse_id": row.warehouse_id, "name": row.name} for row in rows.scalars().all()])


@router.post("/auth/login", response_model=ApiResponse[LoginResponse])
async def login(payload: LoginRequest) -> ApiResponse[LoginResponse]:
    try:
        token, role = user_service.login(payload.username, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return ApiResponse(data=LoginResponse(access_token=token, role=role))


@router.get("/auth/accounts", response_model=ApiResponse[list[dict]], dependencies=[Depends(require_role("admin"))])
async def accounts() -> ApiResponse[list[dict]]:
    return ApiResponse(data=user_service.list_accounts())


@router.get("/admin/database", response_model=ApiResponse[dict], dependencies=[Depends(require_role("admin"))])
async def database_config() -> ApiResponse[dict]:
    return ApiResponse(data=current_database_config(get_settings()))


@router.post("/admin/database/test", response_model=ApiResponse[dict], dependencies=[Depends(require_role("admin"))])
async def test_database_source(payload: DatabaseSourceRequest) -> ApiResponse[dict]:
    try:
        return ApiResponse(data=await test_source(payload))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.post("/admin/database/source", response_model=ApiResponse[dict], dependencies=[Depends(require_role("admin"))])
async def save_database_source(payload: DatabaseSourceRequest) -> ApiResponse[dict]:
    try:
        await test_source(payload)
        result = persist_database_profile(get_settings(), payload.database_type, source_url(payload))
        return ApiResponse(data={**result, "name": payload.name})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.post("/admin/erp/import", response_model=ApiResponse[dict], dependencies=[Depends(require_role("admin"))])
async def import_erp_data(session: AsyncSession = Depends(get_db)) -> ApiResponse[dict]:
    """Replace local demo business records with data extracted from the read-only ERP channel."""
    try:
        imported = await ErpImportService().replace_with_erp_data(session)
    except BusinessError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except Exception:
        raise HTTPException(status_code=502, detail="ERP 导入失败，本地演示数据已保留") from None
    await audit_persistence_service.record(session, "admin", "erp_import", "business_data", imported)
    erp_analysis_cache.clear()
    return ApiResponse(data={"source": "jimu_erp", "replaced_demo_data": True, "imported": imported})


@router.post("/admin/database/switch", response_model=ApiResponse[dict], dependencies=[Depends(require_role("admin"))])
async def switch_database(payload: DatabaseSwitchRequest) -> ApiResponse[dict]:
    try:
        result = persist_database_profile(get_settings(), payload.database_type, payload.database_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiResponse(data=result)


@router.post("/auth/sso/{provider}", response_model=ApiResponse[LoginResponse])
async def sso_login(provider: str, token: str = Query(..., min_length=1)) -> ApiResponse[LoginResponse]:
    providers = {"oidc": OidcProvider(), "oauth2": OidcProvider(), "ldap": LdapProvider(), "cas": CasProvider()}
    identity_provider = providers.get(provider)
    if identity_provider is None:
        raise HTTPException(status_code=404, detail="不支持的认证协议")
    try:
        identity = await identity_provider.authenticate(token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return ApiResponse(data=LoginResponse(access_token=create_access_token(identity.username, identity.roles[0], identity.organization_id), role=identity.roles[0]))


@router.get("/inventory", response_model=ApiResponse[list[dict]])
async def inventory(query: str | None = Query(default=None), warehouse_id: str | None = Query(default=None),
                    limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0),
                    access: AccessContext = Depends(current_access), session: AsyncSession = Depends(get_db)) -> ApiResponse[list[dict]]:
    requested_warehouse = warehouse_id
    if access.warehouse_ids and (warehouse_id is None or warehouse_id not in access.warehouse_ids):
        requested_warehouse = next(iter(access.warehouse_ids)) if warehouse_id is None else warehouse_id
    return ApiResponse(data=await database_domain_service.inventory(session, query, requested_warehouse, limit, offset))


@router.get("/dashboard/health", response_model=ApiResponse[dict], dependencies=[Depends(current_access)])
async def dashboard_health(session: AsyncSession = Depends(get_db)) -> ApiResponse[dict]:
    return ApiResponse(data=await database_domain_service.health(session))


@router.get("/forecast/{sku}", response_model=ApiResponse[ForecastResponse], dependencies=[Depends(current_access)])
async def forecast(sku: str, warehouse_id: str = "W1", session: AsyncSession = Depends(get_db)) -> ApiResponse[ForecastResponse]:
    result = await database_domain_service.forecast(session, sku, warehouse_id)
    # 预测图表为主，不再同步调用 LLM 解读（曾导致 10s+ 卡顿）；解读可由独立端点按需补充
    result["narrative"] = ""
    if result["forecast"]:
        await persistence_service.save_forecast(session, result)
    return ApiResponse(data=ForecastResponse(**result))


@router.post("/forecast/{sku}/correction", response_model=ApiResponse[ForecastResponse], dependencies=[Depends(require_role("planner"))])
async def correct_forecast(sku: str, payload: ForecastCorrection, warehouse_id: str = "W1", session: AsyncSession = Depends(get_db)) -> ApiResponse[ForecastResponse]:
    result = forecast_service.correct(sku, warehouse_id, payload.values)
    result["narrative"] = ""
    await persistence_service.save_forecast(session, result)
    return ApiResponse(data=ForecastResponse(**result))


@router.post("/purchase-recommendations", response_model=ApiResponse[PurchaseResponse], dependencies=[Depends(require_role("planner"))])
async def purchase_recommendation(payload: PurchaseRequest, session: AsyncSession = Depends(get_db)) -> ApiResponse[PurchaseResponse]:
    try:
        recommendation = await database_domain_service.purchase_recommendation(session, payload.sku, payload.warehouse_id)
    except ValueError:
        preliminary = liku_service.recommend(payload.model_dump())
        price_signal = await database_domain_service.prices(session, payload.sku, preliminary["purchase_quantity"])
        recommendation = liku_service.recommend(payload.model_dump() | {"timing_signal": price_signal["signal"], "expected_saving": price_signal["expected_saving"], "reference_price_low": min(price_signal["prices"]) if price_signal["prices"] else None, "reference_price_high": max(price_signal["prices"]) if price_signal["prices"] else None})
    recommendation = readable_purchase_recommendation(recommendation)
    recommendation["narrative"] = await narrative_service.explain("采购建议", recommendation)
    record = await persistence_service.save_recommendation(session, recommendation)
    audit_service.record("demo", "generate", "purchase_recommendation", {"sku": payload.sku})
    await audit_persistence_service.record(session, "demo", "generate", "purchase_recommendation", {"sku": payload.sku})
    return ApiResponse(data=PurchaseResponse(**{**recommendation, "id": record.id}))


@router.post("/purchase-recommendations/generate", response_model=ApiResponse[PurchaseResponse], dependencies=[Depends(require_role("planner"))])
async def generate_purchase_recommendation(payload: PlanningRequest, session: AsyncSession = Depends(get_db)) -> ApiResponse[PurchaseResponse]:
    try:
        recommendation = await database_domain_service.purchase_recommendation(session, payload.sku, payload.warehouse_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    recommendation = readable_purchase_recommendation(recommendation)
    recommendation["narrative"] = await narrative_service.explain("采购建议", recommendation)
    record = await persistence_service.save_recommendation(session, recommendation)
    await audit_persistence_service.record(session, "planner", "generate", "purchase_recommendation", {"sku": payload.sku, "warehouse_id": payload.warehouse_id, "source": "mysql"})
    return ApiResponse(data=PurchaseResponse(**{**recommendation, "id": record.id}))


@router.get("/purchase-recommendations", response_model=ApiResponse[list[dict]], dependencies=[Depends(require_role("planner"))])
async def purchase_recommendations(session: AsyncSession = Depends(get_db)) -> ApiResponse[list[dict]]:
    return ApiResponse(data=await persistence_service.list_recommendations(session))


@router.patch("/purchase-recommendations/{recommendation_id}", response_model=ApiResponse[dict], dependencies=[Depends(require_role("planner"))])
async def update_purchase_recommendation(recommendation_id: str, payload: RecommendationStatusPayload, session: AsyncSession = Depends(get_db)) -> ApiResponse[dict]:
    try:
        if payload.status is None and payload.purchase_quantity is None:
            raise ValueError("审核更新至少需要状态或采购量")
        row = await persistence_service.update_recommendation(session, recommendation_id, payload.status, payload.purchase_quantity)
        if row is None:
            raise ValueError("采购建议不存在")
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit_service.record("demo", payload.status or "adjusted", "purchase_recommendation", {"id": recommendation_id})
    return ApiResponse(data=row)


@router.get("/purchase-recommendations/export", dependencies=[Depends(require_role("planner"))])
async def export_purchase_recommendations(session: AsyncSession = Depends(get_db)) -> Response:
    rows = await persistence_service.list_recommendations(session)
    if any(row["status"] == "generated" for row in rows):
        raise HTTPException(status_code=400, detail="请先审核全部采购建议")
    for row in rows:
        if row["status"] == "reviewed":
            await persistence_service.update_recommendation(session, row["id"], "exported")
    return Response(content=recommendation_service.export_xlsx(await persistence_service.list_recommendations(session)), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment; filename=purchase-recommendations.xlsx"})


@router.post("/purchase-recommendations/{recommendation_id}/push", response_model=ApiResponse[dict], dependencies=[Depends(require_role("planner"))])
async def push_purchase_recommendation(recommendation_id: str, session: AsyncSession = Depends(get_db)) -> ApiResponse[dict]:
    try:
        row = await persistence_service.update_recommendation(session, recommendation_id, "pushed")
        if row is None:
            raise ValueError("采购建议不存在")
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit_service.record("demo", "pushed", "purchase_recommendation", {"id": recommendation_id})
    return ApiResponse(data=row)


@router.get("/transfers", response_model=ApiResponse[list[dict]], dependencies=[Depends(current_access)])
async def transfers(sku: str | None = Query(default=None), target_warehouse_id: str | None = Query(default=None), min_quantity: float = Query(default=0, ge=0), session: AsyncSession = Depends(get_db)) -> ApiResponse[list[dict]]:
    return ApiResponse(data=await database_domain_service.transfers(session, sku, target_warehouse_id, min_quantity))


@router.post("/transfers/generate", response_model=ApiResponse[list[dict]], dependencies=[Depends(current_access)])
async def generate_transfers(payload: TransferPlanningRequest, session: AsyncSession = Depends(get_db)) -> ApiResponse[list[dict]]:
    return ApiResponse(data=await database_domain_service.transfers(session, payload.sku, payload.target_warehouse_id, payload.min_quantity))


@router.get("/prices/{sku}", response_model=ApiResponse[PriceResponse], dependencies=[Depends(current_access)])
async def prices(sku: str, session: AsyncSession = Depends(get_db)) -> ApiResponse[PriceResponse]:
    result = await database_domain_service.prices(session, sku)
    # 价格图表为主，不再同步调用 LLM 解读（曾导致 10s+ 卡顿）
    result["narrative"] = ""
    return ApiResponse(data=PriceResponse(**result))


@router.get("/prices/{sku}/backtest", response_model=ApiResponse[dict], dependencies=[Depends(require_role("planner"))])
async def price_backtest(sku: str) -> ApiResponse[dict]:
    return ApiResponse(data=price_service.backtest(sku))


@router.get("/warnings", response_model=ApiResponse[list[WarningResponse]], dependencies=[Depends(current_access)])
async def warnings(session: AsyncSession = Depends(get_db)) -> ApiResponse[list[WarningResponse]]:
    return ApiResponse(data=[WarningResponse(**item) for item in await database_domain_service.warnings(session)])


@router.post("/config/safety-stock", response_model=ApiResponse[dict], dependencies=[Depends(require_role("manager"))])
async def set_safety_stock(payload: SafetyStockPayload, session: AsyncSession = Depends(get_db)) -> ApiResponse[dict]:
    config = configuration_service.set_safety_stock(SafetyStockConfig(**payload.model_dump()))
    await persistence_service.save_safety_stock(session, payload.model_dump())
    audit_service.record("demo", "configure", "safety_stock", payload.model_dump())
    return ApiResponse(data=config.__dict__)


@router.post("/config/warning-rule", response_model=ApiResponse[dict], dependencies=[Depends(require_role("manager"))])
async def set_warning_rule(payload: WarningRulePayload, session: AsyncSession = Depends(get_db)) -> ApiResponse[dict]:
    config = configuration_service.set_warning_rule(WarningRuleConfig(**payload.model_dump()))
    await persistence_service.save_warning_rule(session, payload.model_dump())
    warning_service.configure_rule(config)
    audit_service.record("demo", "configure", "warning_rule", payload.model_dump())
    return ApiResponse(data=config.__dict__)


@router.post("/config/price-target", response_model=ApiResponse[dict], dependencies=[Depends(require_role("manager"))])
async def set_price_target(payload: PriceTargetPayload, session: AsyncSession = Depends(get_db)) -> ApiResponse[dict]:
    enabled = configuration_service.set_price_target(payload.sku, payload.enabled)
    await persistence_service.save_price_target(session, payload.sku, payload.enabled)
    audit_service.record("demo", "configure", "price_target", payload.model_dump())
    return ApiResponse(data={"sku": payload.sku, "enabled": enabled})


@router.get("/config/price-targets", response_model=ApiResponse[list[str]], dependencies=[Depends(current_access)])
async def price_targets(session: AsyncSession = Depends(get_db)) -> ApiResponse[list[str]]:
    return ApiResponse(data=await persistence_service.price_targets(session))


@router.get("/prices/{sku}/history", response_model=ApiResponse[list[dict]], dependencies=[Depends(current_access)])
async def price_history(sku: str, session: AsyncSession = Depends(get_db)) -> ApiResponse[list[dict]]:
    return ApiResponse(data=(await database_domain_service.prices(session, sku)).get("history", []))


@router.post("/integrations/sync", response_model=ApiResponse[dict], dependencies=[Depends(require_role("manager"))])
async def create_sync_job(payload: SyncRequest) -> ApiResponse[dict]:
    try:
        job = integration_service.create_job(payload.adapter_name, payload.mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result = integration_service.run_fixture(job["id"])
    audit_service.record("demo", "sync", "integration_job", {"id": job["id"], "adapter": payload.adapter_name})
    return ApiResponse(data=result)


@router.post("/integrations/excel/{entity}", response_model=ApiResponse[dict], dependencies=[Depends(require_role("planner"))])
async def import_excel(entity: str, upload: UploadFile = File(...), session: AsyncSession = Depends(get_db)) -> ApiResponse[dict]:
    if entity not in {"materials", "procurement_orders", "usage_records", "inventory_snapshots", "price_records"}:
        raise HTTPException(status_code=404, detail="不支持的数据实体")
    suffix = ".xlsx" if upload.filename and upload.filename.lower().endswith(".xlsx") else ".invalid"
    temporary_path = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        temporary_path.write(await upload.read())
        temporary_path.close()
        rows = ExcelAdapter(required_fields(entity)).read_file(Path(temporary_path.name))
        cleaned = governance_service.validate_rows(rows, ["quantity", "available_quantity", "in_transit_quantity", "unit_cost", "price"])
        imported = await persistence_service.load_rows(session, entity, cleaned["valid"])
        return ApiResponse(data={"entity": entity, "imported": imported, "rejected": len(cleaned["errors"]), "missing_count": cleaned["missing_count"]})
    finally:
        os.unlink(temporary_path.name)


@router.get("/integrations/jobs", response_model=ApiResponse[list[dict]], dependencies=[Depends(require_role("manager"))])
async def integration_jobs() -> ApiResponse[list[dict]]:
    return ApiResponse(data=integration_service.jobs)


@router.get("/audit", response_model=ApiResponse[list[dict]], dependencies=[Depends(require_role("manager"))])
async def audit_logs(session: AsyncSession = Depends(get_db)) -> ApiResponse[list[dict]]:
    return ApiResponse(data=await audit_persistence_service.list(session))


@router.post("/chat", response_model=ApiResponse[ChatResponse], dependencies=[Depends(current_access)])
async def chat(payload: ChatRequest, session: AsyncSession = Depends(get_db), access: AccessContext = Depends(current_access)) -> ApiResponse[ChatResponse]:
    result = await chatbot_service.chat(payload.message, payload.session_id, session)
    await persistence_service.save_chat(session, result["session_id"], access.username, payload.message, result["answer"], result["sources"])
    return ApiResponse(data=ChatResponse(**result))


@router.get("/chat/{session_id}", response_model=ApiResponse[list[dict[str, str]]], dependencies=[Depends(current_access)])
async def chat_session(session_id: str, session: AsyncSession = Depends(get_db)) -> ApiResponse[list[dict[str, str]]]:
    messages = await persistence_service.chat_messages(session, session_id)
    if messages:
        chatbot_service.load_session(session_id, messages)
    return ApiResponse(data=chatbot_service.session(session_id))


@router.post("/open/inventory", response_model=ApiResponse[list[dict]], dependencies=[Depends(require_open_signature), Depends(require_open_rate_limit)])
async def open_inventory(query: str | None = None, session: AsyncSession = Depends(get_db)) -> ApiResponse[list[dict]]:
    return ApiResponse(data=await database_domain_service.inventory(session, query))


@router.get("/open/purchase-recommendations", response_model=ApiResponse[list[dict]], dependencies=[Depends(require_open_signature), Depends(require_open_rate_limit)])
async def open_purchase_recommendations(session: AsyncSession = Depends(get_db)) -> ApiResponse[list[dict]]:
    return ApiResponse(data=await persistence_service.list_recommendations(session))


@router.post("/im/{platform}/callback", response_model=ApiResponse[ChatResponse])
async def im_callback(platform: str, payload: ChatRequest, session: AsyncSession = Depends(get_db)) -> ApiResponse[ChatResponse]:
    if platform not in {"wecom", "dingtalk", "feishu"}:
        raise HTTPException(status_code=404, detail="不支持的 IM 平台")
    return ApiResponse(data=ChatResponse(**(await chatbot_service.chat(payload.message, payload.session_id, session))))


@router.post("/im/{platform}/daily-report", response_model=ApiResponse[dict])
async def im_daily_report(platform: str) -> ApiResponse[dict]:
    try:
        report = await im_service.daily_report(platform)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ApiResponse(data=report)


@router.post("/warnings/push/{platform}", response_model=ApiResponse[dict])
async def push_warnings(platform: str) -> ApiResponse[dict]:
    providers = {"wecom": WeComProvider(), "dingtalk": DingTalkProvider(), "feishu": FeishuProvider()}
    if platform not in providers:
        raise HTTPException(status_code=404, detail="不支持的 IM 平台")
    return ApiResponse(data=await warning_service.push(providers[platform]))


@router.post("/tasks", response_model=ApiResponse[dict], dependencies=[Depends(require_role("planner"))])
async def create_task(task_type: str = "fixture", config: dict | None = None) -> ApiResponse[dict]:
    return ApiResponse(data=await task_service.create_and_run(task_type, config or {}))


@router.get("/tasks/{task_id}", response_model=ApiResponse[dict], dependencies=[Depends(require_role("planner"))])
async def get_task(task_id: str) -> ApiResponse[dict]:
    task = await task_service.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return ApiResponse(data=task)


@router.post("/tasks/{task_id}/cancel", response_model=ApiResponse[dict], dependencies=[Depends(require_role("planner"))])
async def cancel_task(task_id: str) -> ApiResponse[dict]:
    task = await task_service.cancel(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return ApiResponse(data=task)


@router.post("/sql/validate", response_model=ApiResponse[dict], dependencies=[Depends(require_role("manager"))])
async def validate_sql(query: str) -> ApiResponse[dict]:
    try:
        validated_query = ControlledSql().validate(query)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiResponse(data={"query": validated_query, "read_only": True})


@router.post("/sql/preview", response_model=ApiResponse[SqlPreviewResponse], dependencies=[Depends(require_role("manager"))])
async def preview_sql(payload: SqlPreviewRequest) -> ApiResponse[SqlPreviewResponse]:
    try:
        controlled = ControlledSql()
        query = controlled.validate(payload.query)
        tables = sorted(controlled.tables(query))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiResponse(data=SqlPreviewResponse(query=query, tables=tables, read_only=True, max_rows=100))
