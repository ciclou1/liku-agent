"""ERP → 本地标准表 全量同步（库存健康度/采购建议/利库调剂/需求预测/价格择时 的数据底座）。

从积木 ERP 只读拉取，写入本地库标准表：
- warehouses           ← locations（库房字典）
- materials            ← item（物资档案，upsert）
- inventory_snapshots  ← invbalances 余量 + inventory.MINLEVEL 安全库存 + invcost.AVGCOST 单价
                         + matusetrans 最近领用 + poline 开放合同核销在途（挂靠首个有余额库房）
- usage_records        ← matusetrans 领用按 月×库房×物资 聚合（近 36 个月）
- price_records        ← matrectrans 入库实际单价（近 36 个月）

同步为显式操作（POST /api/v1/erp/sync-inventory），全量替换快照/流水表。
"""

from __future__ import annotations

import logging
import uuid
from datetime import date

from sqlalchemy import delete, insert, text

from app.core.database import session_factory
from app.erp.client import ErpClient
from app.models import InventorySnapshot, Material, PriceRecord, ProcurementOrder, StockMovement, UsageRecord, Warehouse

logger = logging.getLogger(__name__)

_sync_state: dict = {"running": False, "stage": "", "counts": {}, "error": None, "finished_at": None}

_BATCH = 500
# 全历史导入（ERP 领用/入库数据最早到 2014 年），预测与价格择时才能获得足够样本
_USAGE_MONTHS = 240


def sync_status() -> dict:
    return dict(_sync_state)


def _uuid() -> str:
    return str(uuid.uuid4())


def _chunks(rows: list[dict], size: int = _BATCH):
    for i in range(0, len(rows), size):
        yield rows[i:i + size]


def _dec(value) -> float:
    return round(float(value or 0), 4)


def _datestr(value) -> date:
    """MySQL DATE_FORMAT 返回字符串，转 date 供 SQLAlchemy Date 列使用。"""
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def run_sync() -> None:
    """同步入口（在后台线程执行；数据库写入经 asyncio.run 驱动异步会话）。

    同步跑在独立事件循环里，与请求主循环共用的全局引擎连接池会把旧循环的连接带进来，
    触发 "Future attached to a different loop"。因此每次同步在 asyncio.run 内重建专用引擎。
    """
    import asyncio

    if _sync_state["running"]:
        return
    _sync_state.update(running=True, stage="启动", counts={}, error=None, finished_at=None)
    try:
        asyncio.run(_run_isolated())
        _sync_state["stage"] = "完成"
    except Exception as exc:  # noqa: BLE001 —— 同步失败留痕
        logger.exception("ERP inventory sync failed")
        _sync_state["error"] = str(exc)[:300]
        _sync_state["stage"] = "失败"
    finally:
        from datetime import datetime
        _sync_state["running"] = False
        _sync_state["finished_at"] = datetime.now().isoformat(timespec="seconds")


async def _run_isolated() -> None:
    """在独立循环内创建专用引擎与会话工厂，跑完后关闭。"""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.config import get_active_database_profile, get_settings

    url = get_active_database_profile(get_settings())["database_url"]
    engine = create_async_engine(url, pool_pre_ping=False, pool_recycle=1800)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        await _run(maker)
    finally:
        await engine.dispose()


async def _run(session_factory) -> None:
    client = ErpClient()
    site = _site_id()

    async def stage(name: str, counts: dict) -> None:
        _sync_state["stage"] = name
        _sync_state["counts"].update(counts)
        logger.info("erp sync %s %s", name, counts)

    # ── 1. 库房字典 ──
    wh_rows = client.fetch_all(
        "SELECT LOCATION, DESCRIPTION FROM locations WHERE SITEID = %s", [site], limit=500000)
    warehouses = [{"id": _uuid(), "warehouse_id": r["LOCATION"],
                   "name": (r.get("DESCRIPTION") or r["LOCATION"]).strip()[:160],
                   "organization_id": site} for r in wh_rows]
    async with session_factory() as session:
        await session.execute(delete(Warehouse))
        for chunk in _chunks(warehouses):
            await session.execute(insert(Warehouse), chunk)
        await session.commit()
    await stage("库房字典", {"warehouses": len(warehouses)})

    # ── 2. 物资档案（全量替换：清除本地演示/旧物资，确保与 ERP 一致）──
    item_rows = client.fetch_all(
        "SELECT ITEMNUM, DESCRIPTION, COALESCE(NULLIF(HDMODEL,''),'') AS HDMODEL, "
        "COALESCE(NULLIF(ISSUEUNIT,'个'),'个') AS ISSUEUNIT, "
        "COALESCE(NULLIF(HDMCLASS,''),'UNCAT') AS HDMCLASS "
        "FROM item WHERE STATUS = 'ACTIVE'", limit=500000)
    material_rows = [{"id": _uuid(), "sku": r["ITEMNUM"],
                      "name": (r.get("DESCRIPTION") or r["ITEMNUM"]).strip()[:160],
                      "category": (r.get("HDMCLASS") or "UNCAT")[:80],
                      "unit": (r.get("ISSUEUNIT") or "个")[:20],
                      "package_size": 1} for r in item_rows]
    async with session_factory() as session:
        await session.execute(delete(Material))
        for chunk in _chunks(material_rows):
            await session.execute(insert(Material), chunk)
        await session.commit()
    await stage("物资档案", {"materials_total": len(material_rows)})

    # ── 3. 库存快照（全量替换）──
    since = _months_ago(_USAGE_MONTHS)
    bal_rows = client.fetch_all(
        "SELECT b.ITEMNUM, b.LOCATION, SUM(b.CURBAL) AS CURBAL "
        "FROM invbalances b WHERE b.SITEID = %s AND COALESCE(b.is_del,0) = 0 "
        "GROUP BY b.ITEMNUM, b.LOCATION", [site], limit=500000)
    quota_rows = client.fetch_all(
        "SELECT ITEMNUM, CUST_KCDE AS QUOTA FROM item "
        "WHERE STATUS = 'ACTIVE' AND CUST_KCDE > 0", limit=500000)
    minlevel_rows = client.fetch_all(
        "SELECT ITEMNUM, MINLEVEL AS QUOTA FROM inventory "
        "WHERE SITEID = %s AND MINLEVEL > 0", [site], limit=500000)
    cost_rows = client.fetch_all(
        "SELECT c.ITEMNUM, c.LOCATION, c.AVGCOST FROM invcost c WHERE c.SITEID = %s", [site], limit=500000)
    last_use_rows = client.fetch_all(
        "SELECT ITEMNUM, STORELOC, MAX(ACTUALDATE) AS LAST_USE FROM matusetrans "
        "WHERE SITEID = %s AND ISSUETYPE = 'ISSUE' GROUP BY ITEMNUM, STORELOC", [site], limit=500000)
    transit_rows = client.fetch_all(
        "SELECT p.ITEMNUM, SUM(CASE WHEN p.ORDERQTY - COALESCE(r.received_qty, 0) < 0 THEN 0 "
        "ELSE p.ORDERQTY - COALESCE(r.received_qty, 0) END) AS in_transit "
        "FROM poline p JOIN po ON po.PONUM = p.PONUM AND po.SITEID = p.SITEID "
        "LEFT JOIN (SELECT PONUM, POLINENUM, SITEID, SUM(QUANTITY) AS received_qty "
        "           FROM matrectrans WHERE ISSUETYPE IN ('RECEIPT','RETURN') "
        "           GROUP BY PONUM, POLINENUM, SITEID) r "
        "ON r.PONUM = p.PONUM AND r.POLINENUM = p.POLINENUM AND r.SITEID = p.SITEID "
        "WHERE po.SITEID = %s AND po.STATUS NOT IN ('CLOSE','CAN','CLOSED','WAPPR') "
        "GROUP BY p.ITEMNUM", [site], limit=500000)
    procurement_rows = client.fetch_all(
        "SELECT p.PONUM, p.POLINENUM, p.ITEMNUM, p.ORDERQTY, p.UNITCOST, "
        "COALESCE(po.VENDOR,'') AS VENDOR, COALESCE(po.ORDERDATE, po.STARTDATE) AS ORDER_DATE "
        "FROM poline p JOIN po ON po.PONUM = p.PONUM AND po.SITEID = p.SITEID "
        "WHERE po.SITEID = %s AND p.ITEMNUM IS NOT NULL "
        "AND COALESCE(po.ORDERDATE, po.STARTDATE) IS NOT NULL "
        "AND po.STATUS NOT IN ('WAPPR','CAN') "
        "AND COALESCE(po.ORDERDATE, po.STARTDATE) >= %s", [site, since], limit=500000)
    issue_detail_rows = client.fetch_all(
        "SELECT MATUSETRANSID, ITEMNUM, STORELOC, QUANTITY, ACTUALDATE, REFWO "
        "FROM matusetrans WHERE SITEID = %s AND ISSUETYPE = 'ISSUE' "
        "AND ITEMNUM IS NOT NULL AND STORELOC IS NOT NULL AND ACTUALDATE IS NOT NULL "
        "AND ACTUALDATE >= %s", [site, since], limit=500000)

    # 安全库存（物资级，两个来源取大值）：item.CUST_KCDE 库存定额 + inventory.MINLEVEL 最低库存
    quota_by_item: dict[str, float] = {}
    for rows in (quota_rows, minlevel_rows):
        for r in rows:
            itemnum = r["ITEMNUM"]
            quota_by_item[itemnum] = max(quota_by_item.get(itemnum, 0.0), _dec(r["QUOTA"]))
    cost = {(r["ITEMNUM"], r["LOCATION"]): _dec(r["AVGCOST"]) for r in cost_rows if r.get("AVGCOST") is not None}
    last_use = {(r["ITEMNUM"], r["STORELOC"]): r["LAST_USE"] for r in last_use_rows if r.get("LAST_USE")}
    # 在途按物资聚合，挂靠到该物资有正余额的首个库房（按余量降序），避免多库房重复计数
    transit_by_item = {r["ITEMNUM"]: _dec(r["in_transit"]) for r in transit_rows if _dec(r["in_transit"]) > 0}
    balance_by_item: dict[str, list[dict]] = {}
    for r in bal_rows:
        if _dec(r["CURBAL"]) != 0:
            balance_by_item.setdefault(r["ITEMNUM"], []).append(r)
    transit_attach: dict[tuple[str, str], float] = {}
    for itemnum, rows in balance_by_item.items():
        transit = transit_by_item.get(itemnum)
        if transit:
            first = max(rows, key=lambda r: _dec(r["CURBAL"]))
            transit_attach[(itemnum, first["LOCATION"])] = transit

    snapshot_rows = []
    for r in bal_rows:
        key = (r["ITEMNUM"], r["LOCATION"])
        snapshot_rows.append({
            "id": _uuid(), "sku": r["ITEMNUM"], "warehouse_id": r["LOCATION"],
            "available_quantity": _dec(r["CURBAL"]),
            "in_transit_quantity": transit_attach.get(key, 0.0),
            "unit_cost": cost.get(key, 0.0),
            "safety_stock": quota_by_item.get(r["ITEMNUM"], 0.0),
            "last_used_at": last_use.get(key),
            "expiry_date": None,
        })
    async with session_factory() as session:
        await session.execute(delete(InventorySnapshot))
        for chunk in _chunks(snapshot_rows):
            await session.execute(insert(InventorySnapshot), chunk)
        await session.commit()
    await stage("库存快照", {"inventory_rows": len(snapshot_rows),
                            "items_with_in_transit": len(transit_by_item)})

    # ── 4. 领用记录（近 36 个月，按 月×库房×物资 聚合）──
    usage_rows = client.fetch_all(
        "SELECT ITEMNUM, STORELOC, DATE_FORMAT(ACTUALDATE, '%%Y-%%m-01') AS MONTH_START, "
        "SUM(-QUANTITY) AS QTY "
        "FROM matusetrans WHERE SITEID = %s AND ISSUETYPE = 'ISSUE' AND ACTUALDATE >= %s "
        "GROUP BY ITEMNUM, STORELOC, MONTH_START HAVING SUM(-QUANTITY) > 0",
        [site, since], limit=500000)
    usage_records = [{"id": _uuid(), "sku": r["ITEMNUM"], "warehouse_id": r["STORELOC"],
                      "quantity": _dec(r["QTY"]), "used_at": _datestr(r["MONTH_START"]),
                      "work_order_id": None} for r in usage_rows]
    async with session_factory() as session:
        await session.execute(delete(UsageRecord).where(UsageRecord.used_at >= since))
        for chunk in _chunks(usage_records):
            await session.execute(insert(UsageRecord), chunk)
        await session.commit()
    await stage("领用记录", {"usage_rows": len(usage_records), "since": str(since)})

    # ── 5. 采购价历史（全历史：入库实际单价 + 有效合同单价）──
    price_rows = client.fetch_all(
        "SELECT ITEMNUM, UNITCOST, ACTUALDATE, COALESCE(PONUM,'') AS PONUM "
        "FROM matrectrans WHERE SITEID = %s AND ISSUETYPE = 'RECEIPT' "
        "AND ACTUALDATE >= %s AND UNITCOST > 0",
        [site, since], limit=500000)
    price_records = [{"id": _uuid(), "sku": r["ITEMNUM"], "supplier": (r.get("PONUM") or "")[:160],
                      "price": _dec(r["UNITCOST"]), "recorded_at": r["ACTUALDATE"]} for r in price_rows]
    # 合同单价（po.ORDERDATE 为主，STARTDATE 全空）
    price_records += [{"id": _uuid(), "sku": r["ITEMNUM"], "supplier": (r.get("VENDOR") or "ERP供应商")[:160],
                       "price": _dec(r["UNITCOST"]), "recorded_at": r["ORDER_DATE"]} for r in procurement_rows
                      if _dec(r["UNITCOST"]) > 0]
    async with session_factory() as session:
        await session.execute(delete(PriceRecord).where(PriceRecord.recorded_at >= since))
        for chunk in _chunks(price_records):
            await session.execute(insert(PriceRecord), chunk)
        await session.commit()
    await stage("采购价历史", {"price_rows": len(price_records), "since": str(since)})

    # ── 6. 采购合同（全历史有效合同行，日期取 ORDERDATE/STARTDATE）──
    procurement_records = [{"id": _uuid(), "sku": r["ITEMNUM"], "warehouse_id": "ERP",
                            "supplier": (r.get("VENDOR") or "ERP供应商")[:160],
                            "quantity": _dec(r["ORDERQTY"]), "unit_price": _dec(r["UNITCOST"]),
                            "ordered_at": r["ORDER_DATE"]} for r in procurement_rows]
    async with session_factory() as session:
        await session.execute(delete(ProcurementOrder).where(ProcurementOrder.ordered_at >= since))
        for chunk in _chunks(procurement_records):
            await session.execute(insert(ProcurementOrder), chunk)
        await session.commit()
    await stage("采购合同", {"procurement_rows": len(procurement_records)})

    # ── 7. 收发流水（近 36 个月：入库/入库退库/领用）──
    receipt_detail_rows = client.fetch_all(
        "SELECT MATRECTRANSID, ITEMNUM, STORELOC, QUANTITY, COALESCE(NULLIF(UNITCOST,0),0) AS UNITCOST, "
        "ACTUALDATE, COALESCE(PONUM,'') AS PONUM, ISSUETYPE "
        "FROM matrectrans WHERE SITEID = %s AND ISSUETYPE IN ('RECEIPT','RETURN') "
        "AND ITEMNUM IS NOT NULL AND STORELOC IS NOT NULL AND ACTUALDATE IS NOT NULL "
        "AND ACTUALDATE >= %s", [site, since], limit=500000)
    known_items = {r["ITEMNUM"] for r in item_rows}
    known_whs = {w["warehouse_id"] for w in warehouses}
    movement_rows = []
    for r in receipt_detail_rows:
        if r["ITEMNUM"] not in known_items or r["STORELOC"] not in known_whs:
            continue
        movement_rows.append({
            "id": _uuid(), "sku": r["ITEMNUM"], "warehouse_id": r["STORELOC"],
            "movement_type": "receipt" if r["ISSUETYPE"] == "RECEIPT" else "purchase_return",
            "quantity": _dec(r["QUANTITY"]), "unit": "个",
            "posting_date": r["ACTUALDATE"],
            "reference_no": (str(r.get("PONUM") or r.get("MATRECTRANSID") or ""))[:120] or None,
        })
    for r in issue_detail_rows:
        if r["ITEMNUM"] not in known_items or r["STORELOC"] not in known_whs:
            continue
        movement_rows.append({
            "id": _uuid(), "sku": r["ITEMNUM"], "warehouse_id": r["STORELOC"],
            "movement_type": "issue", "quantity": _dec(abs(float(r["QUANTITY"] or 0))), "unit": "个",
            "posting_date": r["ACTUALDATE"],
            "reference_no": (str(r.get("REFWO") or r.get("MATUSETRANSID") or ""))[:120] or None,
        })
    async with session_factory() as session:
        await session.execute(delete(StockMovement).where(StockMovement.posting_date >= since))
        for chunk in _chunks(movement_rows):
            await session.execute(insert(StockMovement), chunk)
        await session.commit()
    await stage("收发流水", {"movement_rows": len(movement_rows)})


def _site_id() -> str:
    from app.core.config import get_settings
    return get_settings().erp_site_id


def _months_ago(months: int) -> date:
    today = date.today().replace(day=1)
    year, month = today.year, today.month - months
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, 1)
