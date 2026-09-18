import { Alert, Button, Card, Col, Descriptions, Empty, Row, Select, Space, Spin, Statistic, Table, Tag, Tabs, Typography, message } from "antd";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { ForecastData, PriceData, WarningItem } from "../types/domain";
import { TrendChart } from "./TrendChart";

type WorkbenchRecord = Record<string, unknown>;
type WarehouseOption = { warehouse_id: string; name: string };

interface BalanceWorkbenchProps {
  sku: string;
  unit: string;
}

const signalLabels: Record<string, string> = {
  stock_up: "建议提前备货",
  delay: "建议延后采购",
  normal: "建议按计划采购",
  no_purchase: "当前无需采购",
};

const directionLabels: Record<string, string> = { up: "上涨", down: "下跌", flat: "基本平稳", unknown: "暂无趋势" };

function text(value: unknown, fallback = "-") {
  return value === null || value === undefined || value === "" ? fallback : String(value);
}

function numeric(value: unknown, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function useWorkbenchData(sku: string, warehouseId: string, activeKey: string) {
  const [transfers, setTransfers] = useState<WorkbenchRecord[]>([]);
  const [forecast, setForecast] = useState<ForecastData>();
  const [prices, setPrices] = useState<PriceData>();
  const [warnings, setWarnings] = useState<WarningItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!sku || activeKey === "purchase" || (activeKey !== "warnings" && !warehouseId)) {
      setLoading(false);
      return;
    }
    setError("");
    setLoading(true);
    const task = activeKey === "overview"
      ? Promise.all([api.transfers({ sku }), api.forecast(sku, warehouseId), api.prices(sku)])
      : activeKey === "transfers"
        ? api.transfers({ sku })
        : activeKey === "forecast"
          ? api.forecast(sku, warehouseId)
          : activeKey === "prices"
            ? api.prices(sku)
            : api.warnings();
    void task
      .then((data) => {
        if (activeKey === "overview") {
          const [transferRows, forecastData, priceData] = data as [WorkbenchRecord[], ForecastData, PriceData];
          setTransfers(transferRows);
          setForecast(forecastData);
          setPrices(priceData);
        }
        if (activeKey === "transfers") setTransfers(data as WorkbenchRecord[]);
        if (activeKey === "forecast") setForecast(data as ForecastData);
        if (activeKey === "prices") setPrices(data as PriceData);
        if (activeKey === "warnings") setWarnings(data as WarningItem[]);
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : "联动分析加载失败"))
      .finally(() => setLoading(false));
  }, [activeKey, sku, warehouseId]);

  return { transfers, forecast, prices, warnings, loading, error };
}

function PurchasePanel({ sku, unit, warehouseOptions }: BalanceWorkbenchProps & { warehouseOptions: WarehouseOption[] }) {
  const [warehouseId, setWarehouseId] = useState("__all__");
  const [result, setResult] = useState<WorkbenchRecord>();
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!warehouseId) setWarehouseId("__all__");
  }, [warehouseId, warehouseOptions]);

  const basis = result?.calculation_basis && typeof result.calculation_basis === "object"
    ? result.calculation_basis as WorkbenchRecord
    : {};
  const value = (key: string, fallback?: unknown) => result?.[key] ?? basis[key] ?? fallback;
  const inventoryQuantity = value("inventory_quantity", value("available_stock"));
  const inTransit = value("in_transit");
  const reservedQuantity = value("reserved_quantity", 0);
  const availableQuantity = value("available_quantity", numeric(inventoryQuantity) + numeric(inTransit) - numeric(reservedQuantity));

  const generate = async () => {
    if (!warehouseId) return;
    setLoading(true);
    try {
      setResult(await api.generatePurchase(sku, warehouseId));
      message.success("已生成采购建议，可在下方继续审核或推送");
    } catch (reason) {
      message.error(reason instanceof Error ? reason.message : "采购建议生成失败");
    } finally {
      setLoading(false);
    }
  };

  return <Card size="small" title="采购建议" extra={<Space><Select value={warehouseId || undefined} placeholder="选择仓库" style={{ width: 170 }} options={[{ value: "__all__", label: "全部仓库" }, ...warehouseOptions.map((item) => ({ value: item.warehouse_id, label: `${item.warehouse_id} ${item.name}` }))]} onChange={setWarehouseId} /><Button type="primary" loading={loading} disabled={!warehouseId} onClick={() => void generate()}>生成建议</Button></Space>}>
    {result ? <>
      <Typography.Paragraph strong>{text(result.narrative ?? result.summary)}</Typography.Paragraph>
      <Descriptions bordered size="small" column={{ xs: 1, sm: 2, md: 4 }} items={[
        { label: "物料", children: text(result.sku) },
        { label: "库存量", children: `${text(inventoryQuantity)}${unit}` },
        { label: "在途量", children: `${text(inTransit)}${unit}` },
        { label: "预留量", children: `${text(reservedQuantity)}${unit}` },
        { label: "可用量", children: `${text(availableQuantity)}${unit}` },
        { label: "安全库存", children: `${text(value("safety_stock"))}${unit}` },
        { label: "预测需求", children: `${text(value("forecast_demand"))}${unit}` },
        { label: "建议采购量", children: `${text(result.purchase_quantity)}${unit}` },
        { label: "采购时机", children: signalLabels[text(result.timing_signal)] ?? text(result.timing_signal) },
        { label: "数据来源", children: text(result.data_source) === "jimu_erp" ? "积木 ERP 实时数据" : text(result.data_source) },
      ]} />
    </> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="选择仓库并生成采购建议" />}
  </Card>;
}

export function BalanceWorkbench({ sku, unit }: BalanceWorkbenchProps) {
  const [warehouseOptions, setWarehouseOptions] = useState<WarehouseOption[]>([]);
  const [activeKey, setActiveKey] = useState("overview");
  const [warehouseId, setWarehouseId] = useState("__all__");
  const { transfers, forecast, prices, warnings, loading, error } = useWorkbenchData(sku, warehouseId, activeKey);

  useEffect(() => {
    void api.warehouses().then((rows) => {
      setWarehouseOptions(rows);
      setWarehouseId((current) => current || "__all__");
    }).catch(() => setWarehouseOptions([]));
  }, [sku]);

  const forecastSeries = useMemo(() => forecast ? [
    { name: "历史领用", data: [...forecast.history.map((item) => item.usage), ...forecast.forecast.map(() => null)] },
    { name: "预测", data: [...forecast.history.map(() => null), ...forecast.forecast.map((item) => item.value)] },
  ] : [], [forecast]);
  const forecastLabels = forecast ? [...forecast.history.map((item) => item.period), ...forecast.forecast.map((item) => item.period)] : [];
  const priceSeries = useMemo(() => prices ? [
    { name: "历史价格", data: [...prices.history.map((item) => item.price), ...prices.periods.map(() => null)] },
    { name: "预测价格", data: [...prices.history.map(() => null), ...prices.prices] },
  ] : [], [prices]);
  const priceLabels = prices ? [...prices.history.map((item) => item.recorded_at), ...prices.periods.map((item) => `预测${item}`)] : [];
  const currentWarnings = warnings.filter((row) => row.sku === sku);

  const tabItems = [
    { key: "overview", label: "联动总览", children: <Card size="small">{loading && <Spin size="small" />} {error && <Alert type="warning" showIcon message={error} style={{ marginBottom: 12 }} />}<Row gutter={[12, 12]}>
      <Col xs={24} sm={12} lg={6}><Card size="small"><Statistic title="采购建议" value="待生成" /></Card></Col>
      <Col xs={24} sm={12} lg={6}><Card size="small"><Statistic title="利库调剂" value={transfers.length} suffix="条候选" /></Card></Col>
      <Col xs={24} sm={12} lg={6}><Card size="small"><Statistic title="需求预测" value={forecast?.pattern ? forecast.pattern : "暂无历史"} /></Card></Col>
      <Col xs={24} sm={12} lg={6}><Card size="small"><Statistic title="价格择时" value={prices ? (directionLabels[prices.direction] ?? prices.direction) : "暂无历史"} /></Card></Col>
    </Row><Typography.Paragraph type="secondary" style={{ margin: "16px 0 0" }}>同一物料的库存结论、采购、调拨、需求和价格分析均在当前工作台完成，切换标签不会离开当前分析上下文。</Typography.Paragraph></Card> },
    { key: "purchase", label: "采购建议", children: <PurchasePanel sku={sku} unit={unit} warehouseOptions={warehouseOptions} /> },
    { key: "transfers", label: "利库调剂", children: <Card size="small" title={<Space>调拨候选{warehouseId === "__all__" ? <Tag>全部仓库</Tag> : warehouseId && <Tag>参考仓库：{warehouseId}</Tag>}</Space>}>
      {loading ? <Spin /> : error ? <Alert type="error" showIcon message={error} /> : <Table size="small" rowKey={(row) => `${text(row.source_warehouse_id)}-${text(row.target_warehouse_id)}-${text(row.sku)}`} dataSource={transfers} locale={{ emptyText: "当前物料没有可执行的调剂建议" }} columns={[{ title: "物料", dataIndex: "sku" }, { title: "调出仓", dataIndex: "source_warehouse_id" }, { title: "调入仓", dataIndex: "target_warehouse_id" }, { title: "建议调拨量", dataIndex: "quantity" }, { title: "距离（km）", dataIndex: "distance_km" }, { title: "时效（天）", dataIndex: "lead_time_days" }]} pagination={{ pageSize: 8 }} />}
    </Card> },
    { key: "forecast", label: "需求预测", children: <Card size="small" title={<Space>需求预测<Select value={warehouseId || undefined} style={{ width: 180 }} options={[{ value: "__all__", label: "全部仓库" }, ...warehouseOptions.map((item) => ({ value: item.warehouse_id, label: `${item.warehouse_id} ${item.name}` }))]} onChange={setWarehouseId} /></Space>}>
      {loading ? <Spin /> : error ? <Alert type="error" showIcon message={error} /> : forecast ? <><Space><Tag color="blue">消耗模式：{forecast.pattern}</Tag><Tag>模型：{forecast.model_name}</Tag><Tag>历史点数：{forecast.history.length}</Tag></Space>{forecastSeries.length ? <TrendChart labels={forecastLabels} series={forecastSeries} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该仓库暂无足够领用历史" />}</> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="选择仓库后加载预测" />}
    </Card> },
    { key: "prices", label: "价格择时", children: <Card size="small" title="价格趋势与采购时机">
      {loading ? <Spin /> : error ? <Alert type="error" showIcon message={error} /> : prices ? <><Space><Tag color={prices.direction === "up" ? "red" : "green"}>趋势：{directionLabels[prices.direction] ?? prices.direction}</Tag><Tag color="gold">采购时机：{signalLabels[prices.signal] ?? prices.signal}</Tag><Tag>模型：{prices.model_name}</Tag><Tag>预计节省：{prices.expected_saving}</Tag></Space>{priceSeries.length ? <TrendChart labels={priceLabels} series={priceSeries} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无价格历史" />}<Table size="small" rowKey={(row) => `${row.supplier}-${row.recorded_at}`} dataSource={prices.history} pagination={{ pageSize: 6 }} columns={[{ title: "供应商", dataIndex: "supplier" }, { title: "报价日期", dataIndex: "recorded_at" }, { title: "采购单价", dataIndex: "price" }]} /></> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="加载价格历史" />}
    </Card> },
    { key: "warnings", label: "预警中心", children: <Card size="small" title={<Space>当前物料预警<Tag color={currentWarnings.length ? "red" : "green"}>{currentWarnings.length ? `${currentWarnings.length} 条` : "无风险"}</Tag></Space>}>
      {loading ? <Spin /> : error ? <Alert type="error" showIcon message={error} /> : <Table size="small" rowKey={(row) => `${row.sku}-${row.warehouse_id}-${row.warning_type}`} dataSource={currentWarnings} locale={{ emptyText: "当前物料暂无库存预警" }} columns={[{ title: "仓库", dataIndex: "warehouse_id" }, { title: "风险类型", dataIndex: "warning_type" }, { title: "等级", dataIndex: "level", render: (value: string) => <Tag color={value === "critical" ? "red" : "orange"}>{value === "critical" ? "严重" : "警告"}</Tag> }, { title: "风险说明", dataIndex: "message" }, { title: "处置建议", dataIndex: "action" }, { title: "涉及金额", dataIndex: "amount" }]} pagination={{ pageSize: 8 }} />}
    </Card> },
  ];

  return <Card title={<Space><span>AI 平衡利库工作台</span><Tag color="blue">{sku}</Tag></Space>} size="small"><Tabs activeKey={activeKey} onChange={setActiveKey} items={tabItems} /></Card>;
}
