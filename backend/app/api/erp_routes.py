"""ERP 平衡利库分析路由（只读，供积木嵌入页与工作台调用）。

访问控制（三选一）：
1. 平台 JWT 登录（Authorization: Bearer），权限完整；
2. X-ERP-Token：时效短、绑定申请行的签名 token（嵌入页经 /erp/access-token 换取，
   仅能访问绑定的申请行/物资）；
3. 公开换 token 端点受 erp_public_read 开关 + 限流控制，生产建议关闭并接入 SSO。

全部请求落审计日志（用户/主机/参数/结果行数）。
"""

import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel

from app.api.deps import bearer, require_open_rate_limit
from app.core.config import get_settings
from app.erp.client import ErpClient, ErpQueryError
from app.erp.service import ErpAnalysisService
from app.erp.token import ErpTokenError, create_read_token, verify_read_token
from app.adapters.erp import JimuErpAdapter
from app.core.erp_cache import erp_analysis_cache
from app.core.database import get_db
from app.services.narrative import NarrativeService
from app.services.domain import DatabaseDomainService
from app.schemas.common import ApiResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/erp", dependencies=[Depends(require_open_rate_limit)])
analysis_service = ErpAnalysisService()
erp_client = ErpClient()
narrative_service = NarrativeService()
database_domain_service = DatabaseDomainService()

# token 换取限流（独立于通用限流：更严格）
token_limiter_window = 60
token_limiter_hits: dict[str, list[float]] = {}


def _token_rate_ok(client_ip: str) -> bool:
    import time
    now = time.time()
    hits = [t for t in token_limiter_hits.get(client_ip, []) if now - t < token_limiter_window]
    if len(hits) >= 10:
        token_limiter_hits[client_ip] = hits
        return False
    hits.append(now)
    token_limiter_hits[client_ip] = hits
    return True


def require_erp_read(
    request: Request,
    prnum: str | None = None,
    itemnum: str | None = None,
    prlinenum: int | None = None,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    x_erp_token: str = Header(default=""),
):
    """ERP 只读接口鉴权：JWT（Authorization 头）或绑定申请行（含行号）的短期签名 token（X-ERP-Token 头）。"""
    settings = get_settings()
    if credentials is not None:
        # 平台 JWT：复用统一校验逻辑（无效即 401）
        from app.api.deps import current_access
        current_access(credentials=credentials)
        return {"kind": "jwt"}
    if settings.app_env == "test" and credentials is None and not x_erp_token:
        return {"kind": "test"}
    if x_erp_token:
        try:
            verify_read_token(x_erp_token, prnum=prnum, itemnum=itemnum, prlinenum=prlinenum)
        except ErpTokenError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        return {"kind": "token"}
    raise HTTPException(status_code=401, detail="需要登录凭证或 ERP 访问令牌")


def _audit(request: Request, action: str, access: dict, **params) -> None:
    client = request.client.host if request.client else "unknown"
    logger.info("AUDIT erp.%s user=%s kind=%s ip=%s %s", action,
                getattr(access, "get", lambda k: None)("kind") if isinstance(access, dict) else access,
                access.get("kind") if isinstance(access, dict) else "?", client, params)


@router.get("/health", response_model=ApiResponse[dict])
def erp_health() -> ApiResponse[dict]:
    """连通性探针（只暴露布尔状态，无业务数据）。"""
    return ApiResponse(data={"erp_connected": erp_client.ping(), "site_id": get_settings().erp_site_id})


@router.get("/adapter-status", response_model=ApiResponse[dict])
def adapter_status() -> ApiResponse[dict]:
    """Adapter SPI status used by the ERP-first balance workflow."""
    return ApiResponse(data=JimuErpAdapter().status())


class AccessTokenIn(BaseModel):
    prnum: str | None = None
    itemnum: str | None = None
    prlinenum: int | None = None


@router.post("/access-token")
def access_token(payload: AccessTokenIn, request: Request) -> ApiResponse[dict]:
    """换取绑定申请行（含行号）的短期只读 token（嵌入页用；受 erp_public_read 与限流控制）。"""
    settings = get_settings()
    if not settings.erp_public_read and settings.app_env != "test":
        raise HTTPException(status_code=403, detail="公开换取 token 已关闭，请使用平台账号登录")
    client = request.client.host if request.client else "unknown"
    if not _token_rate_ok(client):
        raise HTTPException(status_code=429, detail="令牌获取过于频繁")
    token, expires_in = create_read_token(payload.prnum, payload.itemnum, payload.prlinenum)
    logger.info("AUDIT erp.access_token ip=%s prnum=%s itemnum=%s prlinenum=%s ttl=%s",
                client, payload.prnum, payload.itemnum, payload.prlinenum, expires_in)
    return ApiResponse(data={"token": token, "expires_in": expires_in})


# 申请行检索索引：字段 → WHERE 表达式（%s 为转义后的 LIKE 关键词）
_PRLINE_SEARCH_FIELDS = {
    "prnum": "PRNUM LIKE %s",
    "itemnum": "ITEMNUM LIKE %s",
    "description": "DESCRIPTION LIKE %s",
    "requestedby": "REQUESTEDBY LIKE %s",
    "all": "(PRNUM LIKE %s OR ITEMNUM LIKE %s OR DESCRIPTION LIKE %s)",
}


@router.get("/prlines", response_model=ApiResponse[list[dict]])
def search_prlines(
    request: Request,
    q: str = Query(default="", max_length=50, description="检索关键词（配合 field）"),
    field: str = Query(default="all", description="索引字段: prnum/itemnum/description/requestedby/all"),
    keyword: str = Query(default="", max_length=100, description="兼容旧参数（等价 field=all 的 q）"),
    limit: int = Query(default=20, ge=1, le=100),
    access: dict = Depends(require_erp_read),
) -> ApiResponse[list[dict]]:
    """立项申请行检索（支持索引字段选择）。"""
    field_expr = _PRLINE_SEARCH_FIELDS.get(field)
    if field_expr is None:
        raise HTTPException(status_code=400, detail=f"不支持的检索字段: {field}")
    text = q or keyword
    if not text.strip():
        # 浏览模式：下拉一聚焦即出最近申请行
        where, params = "1=1", []
    else:
        like = f"%{analysis_service._escape_like(text.strip())}%"
        where, params = field_expr, [like] * field_expr.count("%s")
    rows = analysis_service.client.fetch_all(
        "SELECT PRNUM, PRLINENUM, ITEMNUM, DESCRIPTION, ORDERQTY, ORDERUNIT, ENTERDATE, REQUESTEDBY, "
        "(PONUM IS NOT NULL AND PONUM <> '') AS has_po "
        "FROM prline WHERE SITEID = %s AND " + where +
        " ORDER BY ENTERDATE DESC",
        [get_settings().erp_site_id, *params],
        limit=limit,
    )
    _audit(request, "prlines.search", access, field=field, q=text[:50], rows=len(rows))
    return ApiResponse(data=rows)


@router.get("/suggest", response_model=ApiResponse[list[dict]])
def suggest_items(
    request: Request,
    q: str = Query(default="", max_length=50, description="联想关键词（空 = 默认浏览列表，有库存优先）"),
    field: str = Query(default="itemnum", description="联想索引: itemnum/description/model"),
    limit: int = Query(default=20, ge=1, le=20),
    access: dict = Depends(require_erp_read),
) -> ApiResponse[list[dict]]:
    """物资联想（采购建议同款交互）：按索引字段联想 ACTIVE 物资，附库存标记；空关键词返回默认列表。"""
    try:
        rows = analysis_service.suggest_items(q.strip(), field=field, limit=limit)
    except ErpQueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit(request, "items.suggest", access, field=field, q=q[:50], rows=len(rows))
    return ApiResponse(data=rows)


@router.get("/balance-analysis", response_model=ApiResponse[dict])
def balance_analysis(
    request: Request,
    itemnum: str = Query(..., min_length=1, max_length=30, description="物资编码（立项申请行项目号）"),
    prnum: str | None = Query(default=None, max_length=30),
    prlinenum: int | None = Query(default=None, ge=1),
    request_qty: float | None = Query(default=None, ge=0),
    access: dict = Depends(require_erp_read),
) -> ApiResponse[dict]:
    """六维度平衡利库分析（纯确定性 SQL，秒级返回）。

    AI 解读独立走 /erp/balance-analysis/narrative，不阻塞本接口。"""
    cache_key = "erp:analysis:{site}:{item}:{pr}:{line}:{qty}".format(
        site=get_settings().erp_site_id, item=itemnum, pr=prnum or "-",
        line=prlinenum or "-", qty=request_qty if request_qty is not None else "-",
    )
    cached = erp_analysis_cache.get(cache_key)
    if cached is not None:
        return ApiResponse(data=cached)
    result = analysis_service.balance_analysis(
        itemnum=itemnum,
        prnum=prnum,
        prlinenum=prlinenum,
        request_qty=request_qty,
    )
    erp_analysis_cache.set(cache_key, result)
    _audit(request, "balance_analysis", access, itemnum=itemnum, prnum=prnum)
    return ApiResponse(data=result)


@router.get("/balance-analysis/narrative", response_model=ApiResponse[dict])
async def balance_analysis_narrative(
    request: Request,
    itemnum: str = Query(..., min_length=1, max_length=30),
    prnum: str | None = Query(default=None, max_length=30),
    prlinenum: int | None = Query(default=None, ge=1),
    request_qty: float | None = Query(default=None, ge=0),
    access: dict = Depends(require_erp_read),
) -> ApiResponse[dict]:
    """AI 解读（独立端点）：数值全部来自确定性 SQL 与规则，AI 仅生成文字解读（不修改数字），
    模型不可用时降级为模板。前端并行加载，失败不影响六维度分析展示。"""
    cache_key = "erp:narrative:{site}:{item}:{pr}:{line}:{qty}".format(
        site=get_settings().erp_site_id, item=itemnum, pr=prnum or "-",
        line=prlinenum or "-", qty=request_qty if request_qty is not None else "-",
    )
    cached = erp_analysis_cache.get(cache_key)
    if cached is not None:
        return ApiResponse(data=cached)
    result = analysis_service.balance_analysis(
        itemnum=itemnum,
        prnum=prnum,
        prlinenum=prlinenum,
        request_qty=request_qty,
    )
    narrative_input = {
        "item": result.get("item"),
        "pr_line": result.get("pr_line"),
        "request_qty": result.get("request_qty"),
        "summary": result.get("summary"),
        "conclusion": result.get("conclusion"),
        "formula_explanation": result.get("formula_explanation"),
    }
    text, source = await narrative_service.explain_with_source("平衡利库分析", narrative_input)
    payload = {"text": text, "source": source}
    # 仅缓存大模型成功的结果；模板降级不缓存，下次访问自动重试大模型
    if source.startswith("llm"):
        erp_analysis_cache.set(cache_key, payload)
    _audit(request, "balance_analysis.narrative", access, itemnum=itemnum, prnum=prnum, narrative_source=source)
    return ApiResponse(data=payload)


@router.get("/workbench-narrative", response_model=ApiResponse[dict])
async def workbench_narrative(
    request: Request,
    itemnum: str = Query(..., min_length=1, max_length=30),
    warehouse_id: str | None = Query(default=None, max_length=80),
    prnum: str | None = Query(default=None, max_length=30),
    prlinenum: int | None = Query(default=None, ge=1),
    request_qty: float | None = Query(default=None, ge=0),
    include_ai: bool = Query(default=True, description="是否等待大模型综合总结；false 只返回确定性面板数据"),
    access: dict = Depends(require_erp_read),
    session = Depends(get_db),
) -> ApiResponse[dict]:
    """工作台综合 AI 解读：库存原结论 + 五个联动模块的结构化摘要。"""
    cache_key = "erp:workbench:narrative:v11:{site}:{item}:{wh}:{pr}:{line}:{qty}:ai{ai}".format(
        site=get_settings().erp_site_id, item=itemnum, wh=warehouse_id or "-",
        pr=prnum or "-", line=prlinenum or "-", qty=request_qty if request_qty is not None else "-",
        ai=int(include_ai),
    )
    cached = erp_analysis_cache.get(cache_key)
    if cached is not None:
        return ApiResponse(data=cached)

    inventory = analysis_service.balance_analysis(
        itemnum=itemnum, prnum=prnum, prlinenum=prlinenum, request_qty=request_qty,
    )
    effective_warehouse = warehouse_id
    if not effective_warehouse:
        stock_details = inventory.get("dimensions", {}).get("stock_balance", {}).get("details", [])
        effective_warehouse = str(stock_details[0].get("LOCATION")) if stock_details else None

    # 其余模块优先读取与工作台一致的本地 ERP 快照；快照未同步时保留空结果，
    # 不用演示数据替代，库存原始 ERP 结论仍然完整保留。
    purchase: dict = {}
    transfers: list[dict] = []
    forecast: dict = {}
    prices: dict = {}
    warnings: list[dict] = []
    if effective_warehouse:
        try:
            purchase = await database_domain_service.purchase_recommendation(session, itemnum, effective_warehouse)
        except Exception:  # noqa: BLE001 - 综合解读不能阻断原始 ERP 分析
            purchase = {
                "warehouse_id": effective_warehouse,
                "purchase_quantity": inventory.get("conclusion", {}).get("suggested_purchase_qty", 0),
                "forecast_demand": inventory.get("request_qty", 0),
                "timing_signal": "暂无",
                "data_source": "jimu_erp",
            }
        try:
            transfers = await database_domain_service.transfers(session, itemnum)
        except Exception:  # noqa: BLE001
            transfers = []
        try:
            forecast = await database_domain_service.forecast(session, itemnum, effective_warehouse)
        except Exception:  # noqa: BLE001
            forecast = {}
    try:
        prices = await database_domain_service.prices(session, itemnum)
    except Exception:  # noqa: BLE001
        prices = {}
    try:
        warnings = await database_domain_service.warnings(session, itemnum)
    except Exception:  # noqa: BLE001
        warnings = []

    price_history = prices.get("history", []) if isinstance(prices, dict) else []
    narrative_input = {
        "inventory_balance": {
            "item": inventory.get("item"),
            "pr_line": inventory.get("pr_line"),
            "request_qty": inventory.get("request_qty"),
            "summary": inventory.get("summary"),
            "conclusion": inventory.get("conclusion"),
            "formula_explanation": inventory.get("formula_explanation"),
        },
        "purchase_recommendation": {
            key: purchase.get(key) for key in (
                "warehouse_id", "purchase_quantity", "forecast_demand", "safety_stock",
                "available_stock", "in_transit", "reserved_quantity", "available_quantity",
                "timing_signal", "expected_saving", "data_source",
            ) if key in purchase
        },
        "transfer_recommendations": transfers[:8],
        "demand_forecast": {
            "warehouse_id": effective_warehouse,
            "pattern": forecast.get("pattern", "暂无历史"),
            "model_name": forecast.get("model_name", "none"),
            "history_count": len(forecast.get("history", [])),
            "next_values": [round(float(row.get("value", 0)), 4) for row in forecast.get("forecast", [])[:3]],
        },
        "price_timing": {
            "direction": prices.get("direction", "unknown") if isinstance(prices, dict) else "unknown",
            "signal": prices.get("signal", "normal") if isinstance(prices, dict) else "normal",
            "expected_saving": prices.get("expected_saving", 0) if isinstance(prices, dict) else 0,
            "history_count": len(price_history),
            "current_price": price_history[-1].get("price") if price_history else None,
        },
        "warnings": warnings[:8],
    }
    # 大模型可能因输出长度截断；始终追加确定性模块摘要，确保原库存面板和五个联动模块不丢失。
    deterministic_summary = narrative_service._section_analysis_fallback(narrative_input)["summary"]
    if include_ai:
        ai_sections, analysis_source = await narrative_service.analyze_sections(narrative_input)
        # 某些模型会把完整 JSON 再包成 summary 字符串，统一解包，避免前端展示原始 JSON。
        summary_value = ai_sections.get("summary", "")
        if isinstance(summary_value, str) and summary_value.lstrip().startswith("{"):
            try:
                embedded = json.loads(summary_value)
                if isinstance(embedded, dict):
                    ai_sections = {key: str(embedded.get(key, ai_sections.get(key, ""))) for key in ai_sections}
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
        # 模型负责业务判断，确定性引擎负责把可执行的平衡利库顺序补全，避免总结缺少动作方案。
        ai_sections["summary"] = f"{ai_sections.get('summary', '').strip()}\n\n【确定性平衡利库方案】\n{deterministic_summary}"
        text, source = ai_sections.get("summary", deterministic_summary), analysis_source
    else:
        ai_sections, text, source = {}, deterministic_summary, "deterministic"
    payload = {
        "text": text,
        "source": source,
        "warehouse_id": effective_warehouse,
        "sections": narrative_input,
        "ai_sections": ai_sections,
        "deterministic_summary": deterministic_summary,
    }
    if source.startswith("llm") or source == "deterministic":
        erp_analysis_cache.set(cache_key, payload)
    _audit(request, "workbench_narrative", access, itemnum=itemnum, warehouse_id=effective_warehouse, prnum=prnum, narrative_source=source)
    return ApiResponse(data=payload)


@router.post("/sync-inventory", response_model=ApiResponse[dict])
def sync_inventory(
    request: Request,
    background_tasks: BackgroundTasks,
    access: dict = Depends(require_erp_read),
) -> ApiResponse[dict]:
    """ERP→本地库 全量同步（物资/库存/领用/价格），驱动库存健康度、采购建议、
    利库调剂、需求预测、价格择时基于 ERP 真实数据运行。后台执行，用 /sync-inventory/status 查进度。"""
    from app.erp import sync_inventory as sync_module

    status = sync_module.sync_status()
    if status.get("running"):
        raise HTTPException(status_code=409, detail="同步正在进行中")
    background_tasks.add_task(sync_module.run_sync)
    _audit(request, "sync_inventory.start", access)
    return ApiResponse(data={"started": True, "status": sync_module.sync_status()})


@router.get("/sync-inventory/status", response_model=ApiResponse[dict])
def sync_inventory_status(access: dict = Depends(require_erp_read)) -> ApiResponse[dict]:
    """ERP→本地库 库存数据同步进度。"""
    from app.erp.sync_inventory import sync_status
    return ApiResponse(data=sync_status())


@router.get("/balance-analysis/export")
def balance_analysis_export(
    request: Request,
    itemnum: str = Query(..., min_length=1, max_length=30),
    prnum: str | None = Query(default=None, max_length=30),
    prlinenum: int | None = Query(default=None, ge=1),
    request_qty: float | None = Query(default=None, ge=0),
    access: dict = Depends(require_erp_read),
):
    """分析报告导出（xlsx：汇总 + 各维度明细）。"""
    import io
    from datetime import datetime

    from openpyxl import Workbook

    result = analysis_service.balance_analysis(itemnum=itemnum, prnum=prnum, prlinenum=prlinenum, request_qty=request_qty)
    _audit(request, "balance_analysis.export", access, itemnum=itemnum, prnum=prnum)

    wb = Workbook()
    ws = wb.active
    ws.title = "汇总"
    ws.append(["AI 平衡利库分析报告"])
    ws.append([f"物资编码：{itemnum}", f"名称：{result['item'].get('DESCRIPTION', '')}", f"规格型号：{result['item'].get('HDMODEL', '')}"])
    if prnum:
        ws.append([f"立项申请：{prnum}" + (f" 行 {prlinenum}" if prlinenum else ""), f"申请数量：{result['request_qty']}"])
    ws.append([])
    ws.append(["维度", "数值"])
    for label, key in [("历史采购量", "history_purchase_qty"), ("在途量", "in_transit_qty"),
                       ("工单领用量", "work_order_issued_qty"), ("工单计划量", "work_order_planned_qty"),
                       ("库存量", "stock_qty"), ("预留量", "reserved_qty"), ("安全库存量", "safety_stock_qty"),
                       ("可用量", "available_qty")]:
        ws.append([label, result["summary"].get(key, 0)])
    ws.append([])
    ws.append(["结论", result["conclusion"]["text"]])
    ws.append(["建议采购量", result["conclusion"]["suggested_purchase_qty"]])

    dim = result["dimensions"]
    detail_defs = [
        ("历史采购明细", dim["history_purchase"]["details"]),
        ("在途明细", dim["in_transit"]["details"]),
        ("工单领用明细", dim["work_order_usage"]["details"]),
        ("库存分布", dim["stock_balance"]["details"]),
        ("预留明细", dim["reservations"]["details"]),
    ]
    for title, rows in detail_defs:
        if not rows:
            continue
        sheet = wb.create_sheet(title[:31])
        cols = list(rows[0].keys())
        sheet.append(cols)
        for row in rows:
            sheet.append([str(v) if not isinstance(v, (int, float)) else v for v in [row.get(c) for c in cols]])

    buffer = io.BytesIO()
    wb.save(buffer)
    filename = f"liku-analysis-{itemnum}-{datetime.now().strftime('%Y%m%d%H%M')}.xlsx"
    from fastapi.responses import Response as HttpResponse
    return HttpResponse(
        content=buffer.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
