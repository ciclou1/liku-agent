import { Alert, Button, Card, Col, Descriptions, Row, Segmented, Select, Space, Spin, Statistic, Table, Tag, Typography, message } from "antd";
import { DownloadOutlined } from "@ant-design/icons";
import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { MaterialOption, ReplenishmentBatch, ReplenishmentDetail } from "../types/domain";
import { TrendChart } from "../components/TrendChart";
import { SpacePage } from "./DashboardPage";

const leadTimeSourceLabels: Record<string, { text: string; color: string }> = {
  item: { text: "该物资 ERP 实测交期", color: "green" },
  supplier: { text: "按供应商实测交期", color: "blue" },
  site: { text: "全厂实测交期均值", color: "cyan" },
  manual: { text: "手动指定交期", color: "purple" },
  default: { text: "默认交期（ERP 无样本）", color: "orange" },
};

/** 物料远程搜索（同采购建议页模式，4 万物资防全量渲染） */
function useMaterialSearch(defaultLimit = 50) {
  const [materials, setMaterials] = useState<MaterialOption[]>([]);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => { void api.materials(undefined, defaultLimit).then(setMaterials).catch(() => {}); }, [defaultLimit]);
  const onMaterialsSearch = (query: string) => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => { void api.materials(query, 50).then(setMaterials).catch(() => {}); }, 250);
  };
  const materialOptions = materials.map((item) => ({ value: item.sku, label: `${item.sku} ${item.name}` }));
  return { materialOptions, onMaterialsSearch };
}

/** 安全库存优化：按消耗速率 + 供应交期动态建议补货点与补货量 */
export function SafetyStockPage() {
  const warehouseOptions = useWarehouseOptions();
  const { materialOptions, onMaterialsSearch } = useMaterialSearch();
  const [mode, setMode] = useState<string | number>("detail");
  const [sku, setSku] = useState("");
  const [warehouseId, setWarehouseId] = useState<string | undefined>();
  const [detail, setDetail] = useState<ReplenishmentDetail>();
  const [batch, setBatch] = useState<ReplenishmentBatch>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => { void loadBatch(); /* 首屏批量列表 */ }, []);
  useEffect(() => { if (!warehouseId && warehouseOptions[0]) setWarehouseId(undefined); }, [warehouseOptions]);

  const loadDetail = async (nextSku = sku) => {
    if (!nextSku) return;
    setLoading(true);
    setError("");
    try { setDetail(await api.replenishmentDetail(nextSku, { warehouse_id: warehouseId })); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "补货建议加载失败"); }
    finally { setLoading(false); }
  };
  const loadBatch = async () => {
    setLoading(true);
    try { setBatch(await api.replenishmentBatch({ warehouse_id: warehouseId, limit: 100 })); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "批量补货建议加载失败"); }
    finally { setLoading(false); }
  };

  const exportFile = async () => {
    const response = await api.replenishmentExport();
    if (!response.ok) { message.error("导出失败"); return; }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "replenishment.xlsx";
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const leadTag = (source: string) => {
    const meta = leadTimeSourceLabels[source] ?? { text: source, color: "default" };
    return <Tag color={meta.color}>{meta.text}</Tag>;
  };

  return <SpacePage title="安全库存优化" subtitle="按月度消耗速率（均值/波动）与供应交期动态建议补货点（ROP）、安全库存与补货量；交期默认取 ERP「下单 → 首次入库」实测值。">
    {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} />}
    <Card size="small" style={{ marginBottom: 12 }}>
      <Space wrap>
        <Segmented value={mode} onChange={(v) => setMode(v)} options={[{ label: "单物资明细", value: "detail" }, { label: "批量 Top 100", value: "batch" }]} />
        {mode === "detail" ? <>
          <Select showSearch onSearch={onMaterialsSearch} filterOption={false} notFoundContent="输入编码/名称搜索" value={sku || undefined} placeholder="输入物料编码/名称搜索" style={{ width: 280 }} options={materialOptions} onChange={(value) => { setSku(value); void loadDetail(value); }} />
          <Select allowClear placeholder="全部仓库" style={{ width: 160 }} options={warehouseOptions} onChange={(v) => setWarehouseId(v)} />
          <Button type="primary" disabled={!sku} loading={loading} onClick={() => void loadDetail()}>计算</Button>
        </> : <>
          <Select allowClear placeholder="全部仓库" style={{ width: 160 }} options={warehouseOptions} onChange={(v) => setWarehouseId(v)} />
          <Button type="primary" loading={loading} onClick={() => void loadBatch()}>刷新批量</Button>
          <Button icon={<DownloadOutlined />} onClick={() => void exportFile()}>导出 Excel</Button>
        </>}
      </Space>
    </Card>

    {mode === "detail" && <>
      {detail?.insufficient_data && <Alert type="warning" showIcon style={{ marginBottom: 12 }}
        message={`该物料近 12 个月有领用记录的月份不足 ${detail.min_months_required} 个月，无法计算消耗波动；请先补充领用数据或手动指定交期口径。`} />}
      {detail && !detail.insufficient_data && <>
        <Row gutter={[12, 12]} style={{ marginBottom: 12 }}>
          <Col xs={24} sm={12} lg={6}><Card size="small"><Statistic title="月均消耗 μ" value={detail.mu_monthly} precision={2} suffix={detail.unit} /></Card></Col>
          <Col xs={24} sm={12} lg={6}><Card size="small"><Statistic title="月消耗波动 σ" value={detail.sigma_monthly} precision={2} suffix={detail.unit} /></Card></Col>
          <Col xs={24} sm={12} lg={6}><Card size="small"><Statistic title="补货点 ROP" value={detail.reorder_point} precision={2} suffix={detail.unit} /></Card></Col>
          <Col xs={24} sm={12} lg={6}><Card size="small"><Statistic title="建议补货量" value={detail.reorder_quantity} precision={2} suffix={detail.unit} /></Card></Col>
        </Row>
        <Card size="small" style={{ marginBottom: 12 }}>
          <Descriptions size="small" column={{ xs: 1, sm: 2, md: 4 }} items={[
            { label: "供应交期", children: <Space>{`${detail.lead_time_months} 个月`}{leadTag(detail.lead_time_source)}</Space> },
            { label: "服务水平 z", children: String(detail.service_level_z) },
            { label: "当前安全库存", children: `${detail.current_safety}${detail.unit}` },
            { label: "建议安全库存", children: <Space>{`${detail.suggested_safety}${detail.unit}`}<Tag color={(detail.safety_gap ?? 0) > 0 ? "red" : (detail.safety_gap ?? 0) < 0 ? "green" : "default"}>{(detail.safety_gap ?? 0) > 0 ? `缺口 ${detail.safety_gap}` : (detail.safety_gap ?? 0) < 0 ? `富余 ${Math.abs(detail.safety_gap ?? 0)}` : "持平"}</Tag></Space> },
            { label: "可用量", children: `${detail.available}${detail.unit}` },
            { label: "在途量", children: `${detail.in_transit}${detail.unit}` },
            { label: "计算窗口", children: `近 ${detail.months_used} 个月` },
            { label: "目标覆盖", children: `${detail.coverage_months} 个月` },
          ]} />
          {detail.lead_time_detail && <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
            交期样本：{String((detail.lead_time_detail as { samples?: number }).samples ?? "-")} 个合同行，最短 {String((detail.lead_time_detail as { min_days?: number }).min_days ?? "-")} 天，最长 {String((detail.lead_time_detail as { max_days?: number }).max_days ?? "-")} 天。
          </Typography.Paragraph>}
        </Card>
        {detail.monthly_usage.length > 0 && <Card size="small" title="近 12 个月消耗" style={{ marginBottom: 12 }}>
          <TrendChart labels={detail.monthly_usage.map((item) => item.month)} series={[{ name: "月度领用量", type: "bar", data: detail.monthly_usage.map((item) => item.usage) }]} />
        </Card>}
        <Card size="small" title="计算口径">
          {Object.entries(detail.formula_explanation ?? {}).map(([key, text]) => (
            <Typography.Paragraph key={key} style={{ marginBottom: 4 }}>{text}</Typography.Paragraph>
          ))}
        </Card>
      </>}
      {detail?.insufficient_data && detail.monthly_usage.length > 0 && <Card size="small" title="已有领用记录">
        <TrendChart labels={detail.monthly_usage.map((item) => item.month)} series={[{ name: "月度领用量", type: "bar", data: detail.monthly_usage.map((item) => item.usage) }]} />
      </Card>}
    </>}

    {mode === "batch" && <Card size="small">
      {batch?.note && <Alert type="info" showIcon message={batch.note} style={{ marginBottom: 12 }} />}
      <Table rowKey="sku" dataSource={batch?.items ?? []} loading={loading} size="small"
        pagination={{ pageSize: 20, showTotal: (total) => `共 ${total} 项` }}
        columns={[
          { title: "编码", dataIndex: "sku", width: 100 },
          { title: "名称", dataIndex: "name", ellipsis: true },
          { title: "月均消耗", dataIndex: "mu_monthly", align: "right" as const, width: 100, render: (v: number) => v?.toFixed(2) },
          { title: "月波动 σ", dataIndex: "sigma_monthly", align: "right" as const, width: 90, render: (v: number) => v?.toFixed(2) },
          { title: "当前安全库存", dataIndex: "current_safety", align: "right" as const, width: 110, render: (v: number) => v?.toFixed(2) },
          { title: "建议安全库存", dataIndex: "suggested_safety", align: "right" as const, width: 110, render: (v: number) => v?.toFixed(2) },
          { title: "缺口", dataIndex: "safety_gap", align: "right" as const, width: 90, render: (v: number) => v > 0 ? <Tag color="red">{v.toFixed(2)}</Tag> : v < 0 ? <Tag color="green">{Math.abs(v).toFixed(2)}</Tag> : "-" },
          { title: "补货点", dataIndex: "reorder_point", align: "right" as const, width: 90, render: (v: number) => v?.toFixed(2) },
          { title: "建议补货量", dataIndex: "reorder_quantity", align: "right" as const, width: 100, render: (v: number) => v?.toFixed(2) },
        ]} />
      <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
        批量模式交期取默认值（可在系统 .env 配置），单物资明细为 ERP「下单 → 首次入库」实测交期；服务水平 z = 1.65（约 95%）。
      </Typography.Paragraph>
    </Card>}
  </SpacePage>;
}

function useWarehouseOptions() {
  const [options, setOptions] = useState<Array<{ label: string; value: string }>>([]);
  useEffect(() => { void api.warehouses().then((rows) => setOptions(rows.map((row) => ({ label: `${row.warehouse_id} ${row.name}`, value: row.warehouse_id })))).catch(() => {}); }, []);
  return options;
}
