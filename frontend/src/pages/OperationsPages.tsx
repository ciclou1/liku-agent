import { Button, Card, Descriptions, Form, Input, InputNumber, Select, Segmented, Space, Table, Tag, Typography, message } from "antd";
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { ForecastData, MaterialOption, PriceData, WarningItem } from "../types/domain";
import { TrendChart } from "../components/TrendChart";
import { ChatPanel } from "../components/ChatPanel";
import { SpacePage } from "./DashboardPage";

function useWarehouseOptions() {
  const [options, setOptions] = useState<Array<{ label: string; value: string }>>([]);
  useEffect(() => { void api.warehouses().then((rows) => setOptions(rows.map((row) => ({ label: `${row.warehouse_id} ${row.name}`, value: row.warehouse_id })))); }, []);
  return options;
}

/** 物料远程搜索：本地库 4 万+ 物资，下拉默认 50 个，输入关键词后端过滤（防全量渲染卡死） */
function useMaterialSearch(defaultLimit = 50) {
  const [materials, setMaterials] = useState<MaterialOption[]>([]);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => { void api.materials(undefined, defaultLimit).then(setMaterials).catch(() => {}); }, [defaultLimit]);
  const onMaterialsSearch = (query: string) => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => { void api.materials(query, 50).then(setMaterials).catch(() => {}); }, 250);
  };
  const materialOptions = materials.map((item) => ({ value: item.sku, label: `${item.sku} ${item.name}` }));
  return { materials, materialOptions, onMaterialsSearch };
}
const statusLabels: Record<string, string> = { generated: "待审核", reviewed: "已审核", exported: "已导出", pushed: "已推送" };
const signalLabels: Record<string, string> = { stock_up: "建议提前备货", delay: "建议延后采购", normal: "按计划采购", no_purchase: "当前无需采购" };
const directionLabels: Record<string, string> = { up: "上涨", down: "下跌", flat: "基本平稳", unknown: "暂无趋势" };
const historyThenGap = (history: number[], futureLength: number): Array<number | null> => [...history, ...Array.from({ length: futureLength }, () => null)];
const gapThenFuture = (historyLength: number, future: number[]): Array<number | null> => [...Array.from({ length: historyLength }, () => null), ...future];

export function PurchasesPage() {
  const warehouseOptions = useWarehouseOptions();
  const { materialOptions, onMaterialsSearch } = useMaterialSearch();
  const [form] = Form.useForm();
  const [rows, setRows] = useState<Array<Record<string, unknown>>>([]);
  const [result, setResult] = useState<Record<string, unknown>>();
  const reload = async () => setRows(await api.recommendations());
  useEffect(() => { void reload(); }, []);
  useEffect(() => { if (warehouseOptions[0]) form.setFieldValue("warehouse_id", warehouseOptions[0].value); }, [warehouseOptions, form]);
  const generate = async (values: { sku: string; warehouse_id: string }) => {
    try { setResult(await api.generatePurchase(values.sku, values.warehouse_id)); await reload(); message.success("已根据 MySQL 库存和历史消耗生成建议"); }
    catch { message.error("该物料缺少库存或领用历史"); }
  };
  const review = async (id: string) => { await api.updateRecommendation(id, "reviewed"); await reload(); message.success("建议已审核"); };
  const push = async (id: string) => { await api.pushRecommendation(id); await reload(); message.success("建议已推送"); };
  const exportFile = async () => { const response = await api.exportRecommendations(); if (!response.ok) { message.error("请先审核全部建议"); return; } const blob = await response.blob(); const url = URL.createObjectURL(blob); const anchor = document.createElement("a"); anchor.href = url; anchor.download = "purchase-recommendations.xlsx"; anchor.click(); URL.revokeObjectURL(url); };
  return <SpacePage title="采购建议" subtitle="使用 ERP 实时库存、领用、包装和价格历史生成可追溯采购建议。">
    <Card>
      <Form form={form} layout="inline" onFinish={generate} initialValues={{ sku: "", warehouse_id: "" }}>
        <Form.Item name="sku" label="物料"><Select showSearch onSearch={onMaterialsSearch} filterOption={false} notFoundContent="输入编码/名称搜索" style={{ width: 260 }} options={materialOptions} /></Form.Item>
        <Form.Item name="warehouse_id" label="仓库"><Select style={{ width: 110 }} options={warehouseOptions} /></Form.Item>
        <Button type="primary" htmlType="submit">从数据库生成</Button><Button onClick={exportFile}>导出 Excel</Button>
      </Form>
      {result && <><Typography.Paragraph strong>{String(result.narrative ?? result.summary ?? `${String(result.sku)} 建议采购 ${String(result.purchase_quantity)}`)}</Typography.Paragraph><Descriptions bordered size="small" column={3} items={[{ label: "物料编码", children: String(result.sku ?? "") }, { label: "预测需求", children: String(result.forecast_demand ?? "") }, { label: "建议采购量", children: String(result.purchase_quantity ?? "") }, { label: "库存量", children: String(result.inventory_quantity ?? result.available_stock ?? "") }, { label: "在途量", children: String(result.in_transit ?? "") }, { label: "预留量", children: String(result.reserved_quantity ?? "") }, { label: "可用量", children: String(result.available_quantity ?? "") }, { label: "采购时机", children: signalLabels[String(result.timing_signal)] ?? String(result.timing_signal ?? "") }, { label: "预测模型", children: String(result.model_name ?? "") }, { label: "数据来源", children: String(result.data_source) === "jimu_erp" ? "积木 ERP 实时数据" : String(result.data_source ?? "") }]} /></>}
      <Table style={{ marginTop: 20 }} rowKey={(row) => String(row.id)} dataSource={rows} columns={[{ title: "物料编码", dataIndex: "sku" }, { title: "建议采购量", dataIndex: "purchase_quantity" }, { title: "采购时机", dataIndex: "timing_signal", render: (value: string) => signalLabels[value] ?? value }, { title: "审批状态", dataIndex: "status", render: (value: string) => statusLabels[value] ?? value }, { title: "操作", render: (_, row) => row.status === "no_purchase" ? <Tag color="blue">当前无需采购</Tag> : row.status === "generated" ? <Button size="small" onClick={() => review(String(row.id))}>审核</Button> : row.status === "reviewed" ? <Button size="small" onClick={() => push(String(row.id))}>推送</Button> : <Tag color="green">已处理</Tag> }]} />
    </Card>
  </SpacePage>;
}

export function TransfersPage() {
  const warehouseOptions = useWarehouseOptions();
  const { materialOptions, onMaterialsSearch } = useMaterialSearch();
  const [rows, setRows] = useState<Array<Record<string, string | number>>>([]);
  const [view, setView] = useState<string | number>("list");
  const [searchParams] = useSearchParams();
  const [filters, setFilters] = useState(() => ({ sku: searchParams.get("sku") ?? "", target_warehouse_id: searchParams.get("target_warehouse_id") ?? "", min_quantity: Number(searchParams.get("min_quantity") ?? 0) }));
  const [generated, setGenerated] = useState(false);
  const load = async () => setRows(await api.transfers(filters));
  const generate = async () => { const result = await api.generateTransfers(filters); setRows(result); setGenerated(true); message.success(`已生成 ${result.length} 条调拨建议`); };
  useEffect(() => { void load(); }, []);
  return <SpacePage title="利库调剂" subtitle="按数据库库存缺口、富余、安全库存、仓库路线和最小调拨量筛选调剂建议。">
    <Card>
      <Space wrap style={{ marginBottom: 16 }}><Select allowClear showSearch onSearch={onMaterialsSearch} filterOption={false} placeholder="全部物料（输入搜索）" style={{ width: 240 }} options={materialOptions} onChange={(sku) => setFilters((old) => ({ ...old, sku: sku ?? "" }))} /><Select allowClear placeholder="目标仓库" style={{ width: 130 }} options={warehouseOptions} onChange={(target_warehouse_id) => setFilters((old) => ({ ...old, target_warehouse_id: target_warehouse_id ?? "" }))} /><InputNumber min={0} placeholder="最小调拨量" onChange={(min_quantity) => setFilters((old) => ({ ...old, min_quantity: min_quantity ?? 0 }))} /><Button onClick={load}>查询条件</Button><Button type="primary" onClick={generate}>生成调拨建议</Button><Segmented value={view} onChange={setView} options={[{ label: "列表", value: "list" }, { label: "路径", value: "path" }]} /></Space>
      {generated && <Typography.Paragraph type="secondary">{rows.length ? `本次根据当前库存缺口、富余库存和仓库路线生成 ${rows.length} 条调拨建议。` : "ERP 当前没有形成可执行调剂：需要至少一个仓库存在可调富余，且另一个仓库存在库存缺口或目标需求。"}</Typography.Paragraph>}
      {view === "list" ? <Table rowKey={(row) => `${row.source_warehouse_id}-${row.target_warehouse_id}-${row.sku}`} dataSource={rows} locale={{ emptyText: "没有符合条件的调剂建议" }} columns={[{ title: "物料编码", dataIndex: "sku" }, { title: "调出仓", dataIndex: "source_warehouse_id" }, { title: "调入仓", dataIndex: "target_warehouse_id" }, { title: "建议调拨量", dataIndex: "quantity" }, { title: "运输距离（km）", dataIndex: "distance_km" }, { title: "预计时效（天）", dataIndex: "lead_time_days" }]} /> : <div className="transfer-map">{rows.map((row) => <div className="transfer-line" key={`${row.source_warehouse_id}-${row.target_warehouse_id}-${row.sku}`}><Tag color="blue">{row.source_warehouse_id}</Tag><span>→</span><Tag color="green">{row.target_warehouse_id}</Tag><span>{row.sku} {row.quantity} 件 / {row.distance_km} km</span></div>)}</div>}
    </Card>
  </SpacePage>;
}

export function ForecastPage() {
  const warehouseOptions = useWarehouseOptions();
  const { materialOptions, onMaterialsSearch } = useMaterialSearch();
  const [data, setData] = useState<ForecastData>();
  const [sku, setSku] = useState("");
  const [warehouse, setWarehouse] = useState("");
  const [correction, setCorrection] = useState("40,42,38,45,41,44");
  const load = async (nextSku = sku, nextWarehouse = warehouse) => setData(await api.forecast(nextSku, nextWarehouse));
  useEffect(() => { if (!warehouse && warehouseOptions[0]) setWarehouse(warehouseOptions[0].value); }, [warehouse, warehouseOptions]);
  const submitCorrection = async () => { const values = correction.split(",").map(Number).filter(Number.isFinite); setData(await api.correctForecast(sku, values, warehouse)); message.success("人工修正已提交"); };
  return <SpacePage title="需求预测" subtitle="从 ERP 领用流水提取历史特征，使用模型池输出预测区间并支持人工修正。">
    <Card extra={<Space><Select showSearch onSearch={onMaterialsSearch} filterOption={false} notFoundContent="输入编码/名称搜索" value={sku || undefined} placeholder="输入物料编码/名称搜索" style={{ width: 260 }} options={materialOptions} onChange={(value) => { setSku(value); void load(value); }} /><Select value={warehouse || undefined} style={{ width: 100 }} options={warehouseOptions} onChange={setWarehouse} /><Button disabled={!sku} onClick={() => void load()}>查询</Button></Space>}>
      {data && <><Space><Tag color="blue">消耗模式：{data.pattern}</Tag><Tag>模型：{data.model_name}</Tag><Tag>历史点数：{data.history.length}</Tag></Space><TrendChart labels={data.history.map((item) => item.period).concat(data.forecast.map((item) => item.period))} series={[{ name: "历史领用", data: historyThenGap(data.history.map((item) => item.usage), data.forecast.length) }, { name: "预测", data: gapThenFuture(data.history.length, data.forecast.map((item) => item.value)) }, { name: "区间下界", data: gapThenFuture(data.history.length, data.forecast.map((item) => item.lower)) }, { name: "区间上界", data: gapThenFuture(data.history.length, data.forecast.map((item) => item.upper)) }]} /><Space.Compact style={{ width: "100%" }}><Input value={correction} onChange={(event) => setCorrection(event.target.value)} placeholder="逗号分隔的历史领用量" /><Button onClick={submitCorrection}>提交人工修正</Button></Space.Compact></>}
    </Card>
  </SpacePage>;
}

export function PricesPage() {
  const { materialOptions, onMaterialsSearch } = useMaterialSearch();
  const [sku, setSku] = useState("");
  const [data, setData] = useState<PriceData>();
  const load = async (nextSku = sku) => setData(await api.prices(nextSku));
  useEffect(() => { /* 首次进入不自动加载，用户搜索选择物料后查询 */ }, []);
  return <SpacePage title="价格择时" subtitle="读取多供应商采购价历史，计算趋势、涨跌信号和预期节省金额。">
    <Card extra={<Space><Select showSearch onSearch={onMaterialsSearch} filterOption={false} notFoundContent="输入编码/名称搜索" value={sku || undefined} placeholder="输入物料编码/名称搜索" style={{ width: 260 }} options={materialOptions} onChange={(value) => { setSku(value); void load(value); }} /><Button disabled={!sku} onClick={() => void load()}>刷新价格</Button></Space>}>
      {data && <><Space><Tag color={data.direction === "up" ? "red" : "green"}>趋势：{directionLabels[data.direction] ?? data.direction}</Tag><Tag color="gold">采购时机：{signalLabels[data.signal] ?? data.signal}</Tag><Tag>模型：{data.model_name}</Tag><Tag>历史报价：{data.history?.length ?? 0} 条</Tag><Tag>预计节省：{data.expected_saving}</Tag></Space><TrendChart labels={data.history.map((item) => item.recorded_at).concat(data.periods.map((item) => `预测${item}`))} series={[{ name: "历史价格", data: historyThenGap(data.history.map((item) => item.price), data.periods.length) }, { name: "预测价格", data: gapThenFuture(data.history.length, data.prices) }]} /><Table size="small" pagination={{ pageSize: 6 }} rowKey={(row) => `${row.supplier}-${row.recorded_at}`} dataSource={data.history} columns={[{ title: "供应商", dataIndex: "supplier" }, { title: "报价日期", dataIndex: "recorded_at" }, { title: "采购单价", dataIndex: "price" }]} /></>}
    </Card>
  </SpacePage>;
}

export function WarningsPage() { const [rows, setRows] = useState<WarningItem[]>([]); useEffect(() => { void api.warnings().then(setRows); }, []); return <SpacePage title="预警中心" subtitle="集中处理呆滞、超储和临期风险，处置建议可直接带物料条件打开调剂建议。"><Card><Table rowKey={(row) => `${row.sku}-${row.warehouse_id}-${row.warning_type}`} dataSource={rows} columns={[{ title: "物料编码", dataIndex: "sku" }, { title: "仓库", dataIndex: "warehouse_id" }, { title: "风险类型", dataIndex: "warning_type" }, { title: "风险级别", dataIndex: "level", render: (level: string) => <Tag color={level === "critical" ? "red" : "orange"}>{level === "critical" ? "严重" : "警告"}</Tag> }, { title: "处置建议", dataIndex: "action" }, { title: "涉及金额", dataIndex: "amount" }, { title: "调剂建议", render: (_, row) => <Link to={`/transfers?sku=${encodeURIComponent(row.sku)}&target_warehouse_id=${encodeURIComponent(row.warehouse_id)}`}>查看对应调剂</Link> }]} /></Card></SpacePage>; }

export function ChatPage() { return <SpacePage title="智能问答" subtitle="数值问题先经过受控业务工具，再由模型组织答案并附来源。"><Card><ChatPanel /></Card></SpacePage>; }
