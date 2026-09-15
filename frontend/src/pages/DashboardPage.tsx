import { Card, Col, Input, Row, Statistic, Table, Typography } from "antd";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { InventoryItem } from "../types/domain";
import { TrendChart } from "../components/TrendChart";
import type { ReactNode } from "react";

export function DashboardPage() {
  const [metrics, setMetrics] = useState<Record<string, number>>({});
  const [inventory, setInventory] = useState<InventoryItem[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const load = (q: string) => {
    setLoading(true);
    void Promise.all([api.dashboard(), api.inventory(q, 500)])
      .then(([dashboard, rows]) => { setMetrics(dashboard); setInventory(rows); })
      .catch((reason) => setError(reason instanceof Error ? reason.message : "库存健康度加载失败"))
      .finally(() => setLoading(false));
  };
  useEffect(() => { load(""); }, []);
  const role = localStorage.getItem("liku_role") ?? "manager";
  const portalTitle = role === "worker" ? "一线查询门户" : role === "planner" ? "采购员工作台" : "管理者看板";
  return <SpacePage title={portalTitle} subtitle="从现有库存、在途和需求预测出发，优先发现可利库空间。ERP 全量数据可用搜索框按物料编码/名称检索。">
    {error && <Typography.Text type="danger">{error}</Typography.Text>}
    <Row gutter={[16, 16]}>{[["库存资金占用", metrics.inventory_value, "¥"], ["呆滞库存金额", metrics.stagnant_value, "¥"], ["预计利库降本", metrics.saving_value, "¥"], ["库存周转率", metrics.turnover_rate, "次"]].map(([title, value, prefix]) => <Col xs={24} sm={12} lg={6} key={String(title)}><Card loading={loading}><Statistic title={title} value={value ?? 0} prefix={prefix === "¥" ? "¥" : undefined} suffix={prefix === "次" ? "次" : undefined} precision={prefix === "¥" ? 0 : 1} /></Card></Col>)}</Row>
    <Input.Search allowClear placeholder="搜索物料编码 / 名称（如 20002 或 石墨）" style={{ maxWidth: 420, margin: "12px 0" }} enterButton onSearch={(value) => load(value.trim())} />
    <Row gutter={[16, 16]} style={{ marginTop: 0 }}><Col xs={24} lg={15}><Card title="库存价值概览"><TrendChart labels={inventory.map((item) => item.sku)} series={[{ name: "库存价值", type: "bar", data: inventory.map((item) => item.available_quantity * item.unit_cost) }]} /></Card></Col><Col xs={24} lg={9}><Card title="现货明细（按库存价值排序显示前 500 条，支持搜索）"><Table size="small" rowKey={(item) => `${item.sku}-${item.warehouse_id}`} pagination={{ pageSize: 20 }} dataSource={inventory} columns={[{ title: "物料", dataIndex: "name" }, { title: "编码", dataIndex: "sku", width: 110 }, { title: "仓库", dataIndex: "warehouse_name" }, { title: "可用", dataIndex: "available_quantity" }]} /></Card></Col></Row>
  </SpacePage>;
}

export function SpacePage({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) { return <div><Typography.Title level={2}>{title}</Typography.Title><Typography.Paragraph type="secondary">{subtitle}</Typography.Paragraph>{children}</div>; }
