import { Alert, Button, Card, Descriptions, Empty, List, Space, Statistic, Tag, Typography } from "antd";
import { LeftOutlined, RightOutlined } from "@ant-design/icons";
import { useMemo, useState } from "react";

type AnyRecord = Record<string, any>;

interface NarrativePayload {
  text: string;
  source: string;
  sections?: AnyRecord;
  ai_text?: string;
  deterministic_summary?: string;
  ai_sections?: Record<string, string>;
}

interface NarrativePanelsProps {
  analysis: AnyRecord;
  narrative: NarrativePayload | null;
  loading: boolean;
}

const signalLabels: Record<string, string> = {
  stock_up: "建议提前备货",
  delay: "建议延后采购",
  normal: "建议按计划采购",
  no_purchase: "当前无需采购",
};

const directionLabels: Record<string, string> = { up: "上涨", down: "下跌", flat: "基本平稳", unknown: "暂无趋势" };

const numberText = (value: unknown, suffix = "") => {
  if (value === null || value === undefined || value === "") return "暂无数据";
  const n = Number(value);
  return `${Number.isFinite(n) ? n : String(value)}${suffix}`;
};

function cleanSummary(value: unknown): string {
  if (typeof value !== "string") return value ? String(value) : "";
  let trimmed = value.trim();
  const planMarker = "【确定性平衡利库方案】";
  const markerIndex = trimmed.indexOf(planMarker);
  if (markerIndex >= 0) {
    const modelPart = trimmed.slice(0, markerIndex).trim();
    const planPart = trimmed.slice(markerIndex + planMarker.length).trim();
    // 模型已有完整分析时，去掉后面重复的确定性方案；模型为空时保留确定性方案。
    trimmed = modelPart.length >= 40 ? modelPart : planPart;
  }
  if (!trimmed.startsWith("{")) return trimmed;
  // 模型可能返回“JSON 对象 + 正文”，不能直接对整段 JSON.parse；按字符串状态机找到首个完整对象。
  let depth = 0;
  let inString = false;
  let escaped = false;
  let end = -1;
  for (let index = 0; index < trimmed.length; index += 1) {
    const char = trimmed[index];
    if (inString) {
      if (escaped) escaped = false;
      else if (char === "\\") escaped = true;
      else if (char === '"') inString = false;
      continue;
    }
    if (char === '"') inString = true;
    else if (char === "{") depth += 1;
    else if (char === "}" && --depth === 0) { end = index + 1; break; }
  }
  if (end < 0) return value;
  try {
    const parsed = JSON.parse(trimmed.slice(0, end)) as { summary?: unknown };
    const rest = trimmed.slice(end).replace(/^\s*[,;:\n]+\s*/, "").trim();
    const summary = typeof parsed.summary === "string" ? parsed.summary : "";
    return [summary, rest].filter(Boolean).join("\n\n");
  } catch {
    return trimmed.slice(end).trim() || value;
  }
}

export function NarrativePanels({ analysis, narrative, loading }: NarrativePanelsProps) {
  const [page, setPage] = useState(1);
  const sections = narrative?.sections ?? {};
  const inventory = sections.inventory_balance ?? { summary: analysis.summary, conclusion: analysis.conclusion, item: analysis.item };
  const purchase = sections.purchase_recommendation ?? {};
  const transfers = Array.isArray(sections.transfer_recommendations) ? sections.transfer_recommendations : [];
  const forecast = sections.demand_forecast ?? {};
  const price = sections.price_timing ?? {};
  const warnings = Array.isArray(sections.warnings) ? sections.warnings : [];
  const summaryText = cleanSummary(narrative?.ai_sections?.summary || narrative?.ai_text || narrative?.text || "");
  const aiSections = narrative?.ai_sections ?? {};
  const aiText = (key: string) => aiSections[key] ? <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}><b>AI 分析：</b>{aiSections[key]}</Typography.Paragraph> : null;

  const panels = useMemo(() => [
    {
      title: "库存面板结论",
      content: <>
        <Alert type={inventory.conclusion?.status === "satisfied" ? "success" : inventory.conclusion?.status === "partial" ? "warning" : "info"} showIcon message={inventory.conclusion?.text || "库存结论加载中…"} />
        <Descriptions bordered size="small" column={{ xs: 1, sm: 2, md: 3 }} style={{ marginTop: 12 }} items={[
          { label: "库存量", children: numberText(inventory.summary?.stock_qty) },
          { label: "在途量", children: numberText(inventory.summary?.in_transit_qty) },
          { label: "预留量", children: numberText(inventory.summary?.reserved_qty) },
          { label: "安全库存", children: numberText(inventory.summary?.safety_stock_qty) },
          { label: "可用量", children: numberText(inventory.summary?.available_qty) },
          { label: "申请量", children: numberText(inventory.request_qty) },
        ]} />
        {aiText("inventory")}
      </>,
    },
    {
      title: "采购建议结论",
      content: <>
        <Space wrap>
          <Tag color={Number(purchase.purchase_quantity ?? 0) > 0 ? "red" : "green"}>建议采购 {numberText(purchase.purchase_quantity)}</Tag>
          <Tag>预测需求 {numberText(purchase.forecast_demand)}</Tag>
          <Tag>采购时机：{signalLabels[String(purchase.timing_signal)] ?? numberText(purchase.timing_signal)}</Tag>
        </Space>
        <Descriptions bordered size="small" column={{ xs: 1, sm: 2, md: 3 }} style={{ marginTop: 12 }} items={[
          { label: "仓库", children: purchase.warehouse_id || "暂无数据" },
          { label: "库存量", children: numberText(purchase.inventory_quantity ?? purchase.available_stock) },
          { label: "在途量", children: numberText(purchase.in_transit) },
          { label: "预留量", children: numberText(purchase.reserved_quantity, "") },
          { label: "可用量", children: numberText(purchase.available_quantity) },
          { label: "数据来源", children: purchase.data_source === "jimu_erp" ? "积木 ERP 实时数据" : (purchase.data_source || "暂无数据") },
        ]} />
        {aiText("purchase")}
      </>,
    },
    {
      title: "利库调剂结论",
      content: <>{transfers.length ? <List size="small" dataSource={transfers.slice(0, 6)} renderItem={(row: AnyRecord) => <List.Item><Space wrap><Tag color="blue">{row.source_warehouse_id}</Tag><span>→</span><Tag color="green">{row.target_warehouse_id}</Tag><span>{row.sku} 调拨 {numberText(row.quantity)}，距离 {numberText(row.distance_km, " km")}，时效 {numberText(row.lead_time_days, " 天")}</span></Space></List.Item>} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={narrative ? "当前物料没有可执行的调剂候选" : "调剂结论加载中…"} />}{aiText("transfers")}</>,
    },
    {
      title: "需求预测结论",
      content: <>
        <Space wrap>
          <Tag color="blue">消耗模式：{forecast.pattern || "暂无历史"}</Tag>
          <Tag>模型：{forecast.model_name || "暂无"}</Tag>
          <Tag>预测仓库：{forecast.warehouse_id || "暂无"}</Tag>
        </Space>
        {forecast.next_values?.length ? <Card size="small" style={{ marginTop: 12 }}><Space wrap>{forecast.next_values.map((value: number, index: number) => <Statistic key={index} title={`未来第 ${index + 1} 期`} value={value} />)}</Space></Card> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={narrative ? "该仓库暂无足够领用历史" : "预测结论加载中…"} />}
        {aiText("forecast")}
      </>,
    },
    {
      title: "价格择时结论",
      content: <>
        <Space wrap>
          <Tag color={price.direction === "up" ? "red" : "green"}>趋势：{directionLabels[price.direction] ?? price.direction ?? "暂无"}</Tag>
          <Tag color="gold">{signalLabels[String(price.signal)] ?? price.signal ?? "暂无采购时机"}</Tag>
          <Tag>预计节省：{numberText(price.expected_saving)}</Tag>
          <Tag>历史报价：{numberText(price.history_count, " 条")}</Tag>
        </Space>
        <Typography.Paragraph type="secondary" style={{ marginTop: 12 }}>价格结论仅用于采购时机判断，不改变库存数量和建议采购量。</Typography.Paragraph>
        {aiText("price")}
      </>,
    },
    {
      title: "预警中心结论",
      content: <>{warnings.length ? <List size="small" dataSource={warnings.slice(0, 8)} renderItem={(row: AnyRecord) => <List.Item><Space direction="vertical" size={2}><Space><Tag color={row.level === "critical" ? "red" : "orange"}>{row.level === "critical" ? "严重" : "警告"}</Tag><span>{row.warehouse_id || "全局"} · {row.warning_type}</span></Space><Typography.Text>{row.message || "存在库存风险"}</Typography.Text><Typography.Text type="secondary">处置建议：{row.action || "请进一步核查"}</Typography.Text></Space></List.Item>} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={narrative ? "当前物料暂无库存预警" : "预警结论加载中…"} />}{aiText("warnings")}</>,
    },
    {
      title: "综合总结",
      content: loading ? <Space direction="vertical"><Typography.Text type="secondary">正在生成综合分析，前面的业务结论已可查看…</Typography.Text><div style={{ width: 240 }}><SpinPlaceholder /></div></Space> : summaryText ? <Typography.Paragraph style={{ whiteSpace: "pre-wrap", marginBottom: 0 }}>{summaryText}</Typography.Paragraph> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无综合总结" />,
    },
  ], [analysis, inventory, loading, price, purchase, summaryText, transfers, warnings, forecast, narrative]);

  const current = panels[page - 1];
  return <Card size="small" title={<Space>AI 综合解读 <Tag color={narrative?.source?.startsWith("llm") ? "purple" : "blue"}>{narrative?.source?.startsWith("llm") ? "大模型 + 确定性结论" : "确定性结论"}</Tag></Space>}>
    <Space wrap size={[6, 6]} style={{ marginBottom: 12 }}>
      {panels.map((panel, index) => <Button key={panel.title} size="small" type={index + 1 === page ? "primary" : "default"} onClick={() => setPage(index + 1)}>{panel.title.replace("结论", "")}</Button>)}
    </Space>
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
      <Typography.Title level={5} style={{ margin: 0 }}>{current.title}</Typography.Title>
      <Space><Button aria-label="上一页" icon={<LeftOutlined />} disabled={page === 1} onClick={() => setPage((value) => value - 1)} /><Typography.Text type="secondary">{page} / {panels.length}</Typography.Text><Button aria-label="下一页" icon={<RightOutlined />} disabled={page === panels.length} onClick={() => setPage((value) => value + 1)} /></Space>
    </div>
    {current.content}
    <div style={{ display: "flex", justifyContent: "center", gap: 6, marginTop: 16 }}>{panels.map((panel, index) => <button key={panel.title} aria-label={`第 ${index + 1} 页：${panel.title}`} onClick={() => setPage(index + 1)} style={{ width: index + 1 === page ? 24 : 8, height: 8, border: 0, borderRadius: 8, padding: 0, background: index + 1 === page ? "#1677ff" : "#d9d9d9", cursor: "pointer" }} />)}</div>
  </Card>;
}

function SpinPlaceholder() {
  return <div style={{ height: 8, borderRadius: 4, background: "linear-gradient(90deg, #f0f0f0 25%, #d9d9d9 50%, #f0f0f0 75%)", backgroundSize: "200% 100%", animation: "narrative-loading 1.2s infinite" }} />;
}
