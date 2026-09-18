import { Alert, Button, Card, Col, InputNumber, Row, Select, Space, Statistic, Table, Tag, Typography, message } from "antd";
import { DownloadOutlined, ReloadOutlined } from "@ant-design/icons";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { DormantItem, DormantResponse } from "../types/domain";
import { SpacePage } from "./DashboardPage";

const suggestionTags: Record<string, { color: string }> = {
  调剂: { color: "blue" },
  退货: { color: "orange" },
  报废评估: { color: "red" },
};

/** 呆滞库存识别：长期无消耗物资清单 + 处置建议（调剂 → 退货 → 报废 优先级） */
export function DormantPage() {
  const [warehouseOptions, setWarehouseOptions] = useState<Array<{ label: string; value: string }>>([]);
  const [thresholdDays, setThresholdDays] = useState<number>(365);
  const [warehouseId, setWarehouseId] = useState<string | undefined>();
  const [data, setData] = useState<DormantResponse>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => { void api.warehouses().then((rows) => setWarehouseOptions(rows.map((row) => ({ label: `${row.warehouse_id} ${row.name}`, value: row.warehouse_id })))).catch(() => {}); }, []);

  const load = useCallback((page = 1, size = 50) => {
    setLoading(true);
    setError("");
    void api.dormant({ threshold_days: thresholdDays, warehouse_id: warehouseId, page, size })
      .then(setData)
      .catch((reason) => setError(reason instanceof Error ? reason.message : "呆滞清单加载失败"))
      .finally(() => setLoading(false));
  }, [thresholdDays, warehouseId]);

  useEffect(() => { load(); }, [load]);

  const exportFile = async () => {
    const response = await api.dormantExport();
    if (!response.ok) { message.error("导出失败"); return; }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "dormant-stock.xlsx";
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const columns = [
    { title: "编码", dataIndex: "sku", width: 100 },
    { title: "名称", dataIndex: "name", ellipsis: true },
    { title: "仓库", dataIndex: "warehouse_name", width: 130, ellipsis: true },
    { title: "可用量", dataIndex: "available_quantity", width: 90, align: "right" as const, render: (v: number, row: DormantItem) => `${v}${row.unit}` },
    { title: "占用金额", dataIndex: "amount", width: 110, align: "right" as const, render: (v: number) => Number(v ?? 0).toLocaleString("zh-CN", { minimumFractionDigits: 2 }) },
    { title: "最近领用", dataIndex: "last_used_at", width: 100, render: (v: string | null) => v ?? <Tag>从未领用</Tag> },
    { title: "呆滞天数", dataIndex: "days_idle", width: 90, align: "right" as const, render: (v: number | null) => (v === null ? "-" : v) },
    { title: "处置建议", dataIndex: "suggestion", width: 100, render: (v: string) => <Tag color={suggestionTags[v]?.color}>{v}</Tag> },
    { title: "建议依据", dataIndex: "basis", ellipsis: true },
  ];

  return <SpacePage title="呆滞库存识别" subtitle="识别长期无领用的库存物资，按「调剂 → 退货 → 报废」优先级给出处置建议；数据来自 ERP 同步快照。">
    {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} />}
    <Card size="small" style={{ marginBottom: 12 }}>
      <Space wrap>
        <span>呆滞阈值（天）：</span>
        <InputNumber min={30} max={1825} step={30} value={thresholdDays} onChange={(v) => setThresholdDays(Number(v ?? 365))} />
        <Select allowClear placeholder="全部仓库" style={{ width: 180 }} options={warehouseOptions} onChange={(v) => setWarehouseId(v)} />
        <Button type="primary" icon={<ReloadOutlined />} onClick={() => load()} loading={loading}>查询</Button>
        <Button icon={<DownloadOutlined />} onClick={() => void exportFile()}>导出 Excel</Button>
      </Space>
    </Card>
    <Row gutter={[12, 12]} style={{ marginBottom: 12 }}>
      <Col xs={24} sm={12} lg={6}><Card size="small"><Statistic title="呆滞总项数（当前页范围）" value={data?.total ?? 0} /></Card></Col>
      <Col xs={24} sm={12} lg={6}><Card size="small"><Statistic title="当前页占用金额（元）" value={data?.page_amount ?? 0} precision={2} /></Card></Col>
      <Col xs={24} sm={12} lg={4}><Card size="small"><Statistic title="建议调剂" value={data?.summary.transfer ?? 0} valueStyle={{ color: "#1677ff" }} /></Card></Col>
      <Col xs={24} sm={12} lg={4}><Card size="small"><Statistic title="建议退货" value={data?.summary.return ?? 0} valueStyle={{ color: "#fa8c16" }} /></Card></Col>
      <Col xs={24} sm={12} lg={4}><Card size="small"><Statistic title="建议报废评估" value={data?.summary.scrap ?? 0} valueStyle={{ color: "#cf1322" }} /></Card></Col>
    </Row>
    <Card size="small">
      <Table
        rowKey={(row) => `${row.sku}-${row.warehouse_id}`}
        dataSource={data?.items ?? []}
        columns={columns}
        loading={loading}
        size="small"
        pagination={{
          total: data?.total ?? 0, pageSize: data?.size ?? 50, current: data?.page ?? 1,
          showSizeChanger: true, pageSizeOptions: [20, 50, 100, 200], showTotal: (total) => `共 ${total} 项`,
          onChange: (page, size) => load(page, size),
        }}
      />
      <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
        处置优先级：① 其他仓库近 12 个月有领用且存在缺口 → 建议调剂；② 近 12 个月有采购记录 → 建议与供应商协商退货；③ 其余长龄无消耗 → 建议组织报废评估。调剂/退货/报废统计为当前页口径。
      </Typography.Paragraph>
    </Card>
  </SpacePage>;
}
