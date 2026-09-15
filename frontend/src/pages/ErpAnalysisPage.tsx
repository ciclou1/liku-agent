import { Alert, Button, Card, Col, Descriptions, Row, Segmented, Select, Space, Spin, Statistic, Table, Tag, Typography } from "antd";
import { DownloadOutlined } from "@ant-design/icons";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

/** 积木嵌入专用落地页：/erp/analysis?prnum=&linenum=&itemnum=
 *  入口为积木立项申请页的「AI平衡利库分析」按钮，携带申请行参数直达。
 *  搜索：顶部物资联想（编码/名称/规格索引切换）+ 申请行联想（申请号/编码/描述/申请人索引切换），
 *  后端联想、防抖、选中即分析；鉴权优先 JWT，嵌入页无 JWT 时用绑定申请行的短令牌。 */

// 同源 /api（vite 代理到后端），本机/内网 IP 访问均自动正确
const baseUrl = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

const tokenCache = new Map<string, string>();

async function fetchToken(prnum?: string | null, itemnum?: string | null, prlinenum?: string | null): Promise<string> {
  const key = `${prnum ?? ""}|${itemnum ?? ""}|${prlinenum ?? ""}`;
  const cached = tokenCache.get(key);
  if (cached) return cached;
  const response = await fetch(`${baseUrl}/erp/access-token`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prnum: prnum || null, itemnum: itemnum || null, prlinenum: prlinenum ? Number(prlinenum) : null }),
  });
  if (!response.ok) {
    const failure = await response.json().catch(() => ({}));
    throw new Error(typeof failure.detail === "string" ? failure.detail : `获取访问令牌失败（${response.status}）`);
  }
  const payload = await response.json();
  tokenCache.set(key, payload.data.token);
  return payload.data.token;
}

/** 平台登录用户走 Authorization: Bearer <JWT>；嵌入页无 JWT 时用绑定申请行的短令牌走 X-ERP-Token。 */
function authHeaders(jwt: string | null): Record<string, string> {
  return jwt ? { Authorization: `Bearer ${jwt}` } : {};
}

async function erpGet<T>(path: string, bind?: { prnum?: string | null; itemnum?: string | null; prlinenum?: string | null }): Promise<T> {
  const jwt = localStorage.getItem("liku_token");
  const headers = jwt ? authHeaders(jwt) : { "X-ERP-Token": await fetchToken(bind?.prnum, bind?.itemnum, bind?.prlinenum) };
  const response = await fetch(`${baseUrl}${path}`, { headers });
  if (!response.ok) {
    const failure = await response.json().catch(() => ({}));
    throw new Error(typeof failure.detail === "string" ? failure.detail : `请求失败（${response.status}）`);
  }
  const payload = (await response.json()) as { data: T };
  return payload.data;
}

interface PrLine { PRNUM: string; PRLINENUM: number | null; ITEMNUM: string; DESCRIPTION: string; ORDERQTY: string; ORDERUNIT: string; ENTERDATE: string; REQUESTEDBY?: string | null; has_po?: number }
interface SuggestItem { ITEMNUM: string; DESCRIPTION: string; HDMODEL: string; ISSUEUNIT: string; has_stock: number }
interface Analysis {
  item: { ITEMNUM: string; DESCRIPTION: string; HDMODEL?: string; ISSUEUNIT?: string };
  pr_line: PrLine | null;
  request_qty: number;
  summary: Record<string, number>;
  conclusion: { status: string; text: string; suggested_purchase_qty: number; suggested_purchase_with_safety: number };
  dimensions: {
    history_purchase: { total_qty: number; contract_lines: number; details: any[] };
    in_transit: { in_transit_qty: number; details: any[] };
    work_order_usage: { issued_qty: number; planned_qty: number; returned_qty: number; details: any[] };
    stock_balance: { total_qty: number; details: any[] };
    reservations: { total_qty: number; details: any[] };
    safety_stock: { total_qty: number; details: any[] };
    receipt_history: { received_qty: number; returned_qty: number; net_received_qty: number };
  };
  formula_explanation: Record<string, string>;
}

const conclusionTags: Record<string, { color: string; label: string }> = {
  satisfied: { color: "green", label: "可满足 · 无需采购" },
  partial: { color: "orange", label: "部分满足" },
  purchase: { color: "red", label: "需采购" },
  no_request: { color: "blue", label: "未关联申请量" },
};

/** 防抖 hook：返回 [debouncedValue, setImmediate] */
function useDebounced<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

/** 顶部物资联想搜索：索引（编码/名称/规格）切换 + 后端联想，选中即分析 */
function ItemSearchSelect({ value, field, onFieldChange, onPick }: {
  value: string | null;
  field: string;
  onFieldChange: (f: string) => void;
  onPick: (itemnum: string) => void;
}) {
  const [keyword, setKeyword] = useState("");
  const [options, setOptions] = useState<SuggestItem[]>([]);
  const [fetching, setFetching] = useState(false);
  const debounced = useDebounced(keyword);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const q = debounced.trim();
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setFetching(true);
    (async () => {
      try {
        const jwt = localStorage.getItem("liku_token");
        const headers = jwt ? authHeaders(jwt) : { "X-ERP-Token": await fetchToken() };
        const response = await fetch(`${baseUrl}/erp/suggest?field=${field}&q=${encodeURIComponent(q)}&limit=20`, { headers, signal: controller.signal });
        if (!response.ok) throw new Error(String(response.status));
        const payload = await response.json();
        setOptions(payload.data ?? []);
      } catch (reason) {
        if ((reason as Error).name !== "AbortError") setOptions([]);
      } finally {
        if (!controller.signal.aborted) setFetching(false);
      }
    })();
    return () => controller.abort();
  }, [debounced, field]);

  return (
    <Space.Compact>
      <Segmented
        value={field}
        onChange={(v) => onFieldChange(v as string)}
        options={[{ label: "编码", value: "itemnum" }, { label: "名称", value: "description" }, { label: "规格", value: "model" }]}
      />
      <Select
        showSearch
        value={value ?? undefined}
        placeholder="输入 物资编码 / 名称 / 规格 联想，如 20002 或 石墨"
        style={{ width: 420 }}
        defaultActiveFirstOption={false}
        filterOption={false}
        loading={fetching}
        notFoundContent={fetching ? <Spin size="small" /> : "无匹配物资"}
        onSearch={setKeyword}
        onSelect={(itemnum: string) => { const hit = options.find((o) => o.ITEMNUM === itemnum); if (hit) onPick(itemnum); }}
        options={options.map((o) => ({
          value: o.ITEMNUM,
          label: (
            <Space>
              <b>{o.ITEMNUM}</b>
              <span>{o.DESCRIPTION}</span>
              <Typography.Text type="secondary">{o.HDMODEL}</Typography.Text>
              {o.has_stock ? <Tag color="green">有库存</Tag> : <Tag>无库存</Tag>}
            </Space>
          ),
        }))}
      />
    </Space.Compact>
  );
}

/** 底部申请行联想搜索：索引（申请号/物资编码/描述/申请人）切换 + 后端联想，选中即分析该行 */
function PrLineSearchSelect({ onPick }: {
  onPick: (record: PrLine) => void;
}) {
  const [keyword, setKeyword] = useState("");
  const [field, setField] = useState("all");
  const [rows, setRows] = useState<PrLine[]>([]);
  const [fetching, setFetching] = useState(false);
  const debounced = useDebounced(keyword);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const q = debounced.trim();
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setFetching(true);
    (async () => {
      try {
        const jwt = localStorage.getItem("liku_token");
        const headers = jwt ? authHeaders(jwt) : { "X-ERP-Token": await fetchToken() };
        const response = await fetch(`${baseUrl}/erp/prlines?field=${field}&q=${encodeURIComponent(q)}&limit=20`, { headers, signal: controller.signal });
        if (!response.ok) throw new Error(String(response.status));
        const payload = await response.json();
        setRows(payload.data ?? []);
      } catch (reason) {
        if ((reason as Error).name !== "AbortError") setRows([]);
      } finally {
        if (!controller.signal.aborted) setFetching(false);
      }
    })();
    return () => controller.abort();
  }, [debounced, field]);

  return (
    <Space.Compact style={{ width: "100%" }}>
      <Select
        value={field}
        onChange={setField}
        style={{ width: 130 }}
        options={[{ value: "all", label: "全部字段" }, { value: "prnum", label: "按申请号" }, { value: "itemnum", label: "按物资编码" }, { value: "description", label: "按描述" }, { value: "requestedby", label: "按申请人" }]}
      />
      <Select
        showSearch
        style={{ flex: 1, minWidth: 420 }}
        placeholder="输入关键词联想申请行，选中即分析（下拉默认列出最近申请行）"
        defaultActiveFirstOption={false}
        filterOption={false}
        loading={fetching}
        notFoundContent={fetching ? <Spin size="small" /> : "无匹配申请行"}
        onSearch={setKeyword}
        onSelect={(_: string, option: any) => { const rec = option?.record as PrLine | undefined; if (rec) onPick(rec); }}
        options={rows.map((r) => ({
          value: `${r.PRNUM}|${r.PRLINENUM ?? "-"}|${r.ITEMNUM}`,
          record: r,
          label: (
            <Space>
              <b>{r.PRNUM}</b>
              <Typography.Text type="secondary">行{r.PRLINENUM ?? "-"}</Typography.Text>
              <span>{r.ITEMNUM}</span>
              <span>{r.DESCRIPTION}</span>
              <Typography.Text type="secondary">×{Number(r.ORDERQTY ?? 0)}{r.ORDERUNIT}</Typography.Text>
              {r.has_po ? <Tag color="blue">已转合同</Tag> : <Tag color="orange">未转合同</Tag>}
            </Space>
          ),
        }))}
      />
    </Space.Compact>
  );
}

export function ErpAnalysisPage() {
  const [params, setParams] = useSearchParams();
  const [itemnum, setItemnum] = useState<string | null>(params.get("itemnum"));
  const [prnum, setPrnum] = useState<string | null>(params.get("prnum"));
  const [linenum, setLinenum] = useState<string | null>(params.get("linenum"));
  const [suggestField, setSuggestField] = useState("itemnum");
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [narrative, setNarrative] = useState<{ text: string; source: string } | null>(null);
  const [narrativeLoading, setNarrativeLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const analyzeByCode = useCallback((code: string, pr?: string | null, ln?: string | null) => {
    const next: Record<string, string> = { itemnum: code };
    if (pr) next.prnum = pr;
    if (ln) next.linenum = ln;
    setParams(next);
    setPrnum(pr ?? null);
    setLinenum(ln ?? null);
    setItemnum(code);
  }, [setParams]);

  const analyze = useCallback(async (code: string, pr?: string | null, ln?: string | null) => {
    setLoading(true);
    setError("");
    setNarrative(null);
    const effectivePr = pr ?? prnum;
    const effectiveLn = ln ?? linenum;
    const query = new URLSearchParams({ itemnum: code });
    if (effectivePr) query.set("prnum", effectivePr);
    if (effectiveLn) query.set("prlinenum", effectiveLn);
    const bind = { prnum: effectivePr, itemnum: code, prlinenum: effectiveLn };
    const narrativeQuery = query.toString();
    // 分析与 AI 解读完全解耦：分析先渲染，解读卡片独立异步加载，互不阻塞
    setNarrativeLoading(true);
    erpGet<Analysis>(`/erp/balance-analysis?${query.toString()}`, bind)
      .then((analysisResult) => setAnalysis(analysisResult))
      .catch((reason) => { setError(reason instanceof Error ? reason.message : "分析失败"); setAnalysis(null); })
      .finally(() => setLoading(false));
    erpGet<{ text: string; source: string }>(`/erp/balance-analysis/narrative?${narrativeQuery}`, bind)
      .then((payload) => setNarrative(payload))
      .catch(() => setNarrative(null))
      .finally(() => setNarrativeLoading(false));
  }, [prnum, linenum]);

  useEffect(() => {
    if (itemnum) analyze(itemnum);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [itemnum]);

  const exportReport = async () => {
    if (!itemnum) return;
    try {
      const query = new URLSearchParams({ itemnum });
      if (prnum) query.set("prnum", prnum);
      if (linenum) query.set("prlinenum", linenum);
      const jwt = localStorage.getItem("liku_token");
      const headers = jwt ? authHeaders(jwt) : { "X-ERP-Token": await fetchToken(prnum, itemnum, linenum) };
      const response = await fetch(`${baseUrl}/erp/balance-analysis/export?${query.toString()}`, { headers });
      if (!response.ok) throw new Error(`导出失败（${response.status}）`);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `平衡利库分析-${itemnum}.xlsx`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "导出失败");
    }
  };

  const unit = analysis?.item?.ISSUEUNIT ?? "";

  const contractColumns = useMemo(() => [
    { title: "合同号", dataIndex: "PONUM", key: "PONUM" },
    { title: "行", dataIndex: "POLINENUM", key: "POLINENUM", width: 60 },
    { title: "数量", dataIndex: "ORDERQTY", key: "ORDERQTY", width: 90 },
    { title: "已入库", dataIndex: "RECEIVEDQTY", key: "RECEIVEDQTY", width: 90 },
    { title: "行成本", dataIndex: "LINECOST", key: "LINECOST", width: 110, render: (v: string) => Number(v ?? 0).toFixed(2) },
    { title: "状态", dataIndex: "STATUS", key: "STATUS", width: 90 },
    { title: "说明", dataIndex: "DESCRIPTION", key: "DESCRIPTION", ellipsis: true },
  ], []);
  const transitColumns = useMemo(() => [
    { title: "合同号", dataIndex: "PONUM", key: "PONUM" },
    { title: "行", dataIndex: "POLINENUM", key: "POLINENUM", width: 60 },
    { title: "合同数量", dataIndex: "contract_qty", key: "contract_qty", width: 100 },
    { title: "已入库", dataIndex: "received_qty", key: "received_qty", width: 100 },
    { title: "在途", dataIndex: "in_transit_qty", key: "in_transit_qty", width: 100 },
    { title: "状态", dataIndex: "STATUS", key: "STATUS", width: 90 },
  ], []);
  const usageColumns = useMemo(() => [
    { title: "工单号", dataIndex: "REFWO", key: "REFWO" },
    { title: "库房", dataIndex: "STORELOC", key: "STORELOC", width: 80 },
    { title: "发放数量", dataIndex: "QUANTITY", key: "QUANTITY", width: 100 },
    { title: "计划数量", dataIndex: "QTYREQUESTED", key: "QTYREQUESTED", width: 100 },
    { title: "领用时余量", dataIndex: "CURBAL", key: "CURBAL", width: 100 },
    { title: "类型", dataIndex: "ISSUETYPE", key: "ISSUETYPE", width: 90, render: (v: string) => (v === "ISSUE" ? <Tag>领用</Tag> : <Tag color="green">退料</Tag>) },
    { title: "日期", dataIndex: "ACTUALDATE", key: "ACTUALDATE", width: 160, render: (v: string) => (v ? String(v).slice(0, 19) : "") },
  ], []);
  const stockColumns = useMemo(() => [
    { title: "库房", dataIndex: "LOCATION", key: "LOCATION", width: 90 },
    { title: "库名", dataIndex: "LOCATION_DESC", key: "LOCATION_DESC", ellipsis: true },
    { title: "当前余量", dataIndex: "CURBAL", key: "CURBAL", width: 110 },
    { title: "货柜", dataIndex: "BINNUM", key: "BINNUM", width: 90 },
    { title: "批次", dataIndex: "LOTNUM", key: "LOTNUM", width: 90 },
  ], []);
  const reserveColumns = useMemo(() => [
    { title: "库房", dataIndex: "LOCATION", key: "LOCATION", width: 90 },
    { title: "预留数量", dataIndex: "RESERVEDQTY", key: "RESERVEDQTY", width: 110 },
    { title: "已领用", dataIndex: "ACTUALQTY", key: "ACTUALQTY", width: 100 },
    { title: "工单", dataIndex: "WONUM", key: "WONUM" },
    { title: "类型", dataIndex: "RESTYPE", key: "RESTYPE", width: 110 },
  ], []);

  return (
    <div style={{ maxWidth: 1280, margin: "0 auto", padding: 16 }}>
      <Space direction="vertical" size={16} style={{ width: "100%" }}>
        <Card size="small">
          <Space wrap size={16}>
            <Typography.Title level={4} style={{ margin: 0 }}>AI 平衡利库分析</Typography.Title>
            {prnum && <Tag color="blue">立项申请 {prnum}{linenum ? ` / 行 ${linenum}` : ""}</Tag>}
            <ItemSearchSelect value={itemnum} field={suggestField} onFieldChange={setSuggestField} onPick={(code) => analyzeByCode(code)} />
            {analysis && <Button icon={<DownloadOutlined />} onClick={exportReport}>导出报告</Button>}
          </Space>
        </Card>

        {error && <Alert type="error" showIcon message={error} />}
        {loading && <Card><Spin tip="正在分析 ERP 数据…" /><div style={{ height: 48 }} /></Card>}

        {analysis && (
          <>
            <Card size="small">
              <Descriptions size="small" column={4}>
                <Descriptions.Item label="物资编码">{analysis.item.ITEMNUM}</Descriptions.Item>
                <Descriptions.Item label="名称">{analysis.item.DESCRIPTION}</Descriptions.Item>
                <Descriptions.Item label="规格型号">{analysis.item.HDMODEL || "-"}</Descriptions.Item>
                <Descriptions.Item label="单位">{unit}</Descriptions.Item>
                {analysis.pr_line && (
                  <>
                    <Descriptions.Item label="申请单号">{analysis.pr_line.PRNUM}</Descriptions.Item>
                    <Descriptions.Item label="申请行">{analysis.pr_line.PRLINENUM ?? "-"}</Descriptions.Item>
                    <Descriptions.Item label="申请数量">{`${Number(analysis.pr_line.ORDERQTY ?? 0)}${unit}`}</Descriptions.Item>
                    <Descriptions.Item label="申请日期">{String(analysis.pr_line.ENTERDATE ?? "").slice(0, 10)}</Descriptions.Item>
                  </>
                )}
              </Descriptions>
            </Card>

            <Alert
              type={analysis.conclusion.status === "satisfied" ? "success" : analysis.conclusion.status === "partial" ? "warning" : "info"}
              showIcon
              message={<Space><Tag color={conclusionTags[analysis.conclusion.status]?.color}>{conclusionTags[analysis.conclusion.status]?.label ?? analysis.conclusion.status}</Tag><span>{analysis.conclusion.text}</span></Space>}
              description={`建议采购量 ${analysis.conclusion.suggested_purchase_qty}${unit}（叠加安全库存参考 ${analysis.conclusion.suggested_purchase_with_safety}${unit}）`}
            />

            {(narrativeLoading || narrative?.text) && (
              <Card size="small" title={<Space>AI 解读{narrativeLoading
                ? <Spin size="small" />
                : <Tag color={narrative?.source === "llm" ? "purple" : "default"}>{narrative?.source === "llm" ? "大模型生成" : "模板解读"}</Tag>}
              </Space>}>
                {narrativeLoading
                  ? <Typography.Text type="secondary">AI 正在生成解读…（不影响下方分析结果）</Typography.Text>
                  : <>
                      <Typography.Paragraph style={{ marginBottom: 4, whiteSpace: "pre-wrap" }}>{narrative?.text}</Typography.Paragraph>
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>数值均来自 ERP 确定性查询，AI 仅作文字解读，不参与计算。</Typography.Text>
                    </>}
              </Card>
            )}

            <Row gutter={12}>
              <Col span={4}><Card size="small"><Statistic title="历史采购量" value={analysis.summary.history_purchase_qty} suffix={unit} /></Card></Col>
              <Col span={4}><Card size="small"><Statistic title="在途量" value={analysis.summary.in_transit_qty} suffix={unit} /></Card></Col>
              <Col span={4}><Card size="small"><Statistic title="工单领用量" value={analysis.summary.work_order_issued_qty} suffix={unit} /></Card></Col>
              <Col span={4}><Card size="small"><Statistic title="工单计划量" value={analysis.summary.work_order_planned_qty} suffix={unit} /></Card></Col>
              <Col span={4}><Card size="small"><Statistic title="库存量" value={analysis.summary.stock_qty} suffix={unit} /></Card></Col>
              <Col span={4}><Card size="small"><Statistic title="预留量" value={analysis.summary.reserved_qty} suffix={unit} /></Card></Col>
            </Row>
            <Row gutter={12}>
              <Col span={4}><Card size="small"><Statistic title="安全库存量" value={analysis.summary.safety_stock_qty} suffix={unit} /></Card></Col>
              <Col span={4}><Card size="small"><Statistic title="可用量" value={analysis.summary.available_qty} suffix={unit} /></Card></Col>
            </Row>

            <Card size="small" title={`可用量 = 库存量 ${analysis.summary.stock_qty} + 在途量 ${analysis.summary.in_transit_qty} − 预留量 ${analysis.summary.reserved_qty} = ${analysis.summary.available_qty}${unit}`}>
              <Typography.Text type="secondary">{analysis.formula_explanation.in_transit}；{analysis.formula_explanation.safety}</Typography.Text>
            </Card>

            <Card size="small" title={`历史采购（合同条目 ${analysis.dimensions.history_purchase.contract_lines} 条，合计 ${analysis.dimensions.history_purchase.total_qty}${unit}）`}>
              <Table size="small" rowKey={(r) => `${r.PONUM}-${r.POLINENUM}`} columns={contractColumns} dataSource={analysis.dimensions.history_purchase.details} pagination={{ pageSize: 5 }} scroll={{ x: 800 }} />
            </Card>
            <Card size="small" title={`在途明细（在途合计 ${analysis.dimensions.in_transit.in_transit_qty}${unit}，口径：合同数量 − 入库数量，按物料接收流水核销）`}>
              <Table size="small" rowKey={(r) => `${r.PONUM}-${r.POLINENUM}`} columns={transitColumns} dataSource={analysis.dimensions.in_transit.details} pagination={{ pageSize: 5 }} scroll={{ x: 700 }} />
            </Card>
            <Card size="small" title={`工单领用（累计领用 ${analysis.dimensions.work_order_usage.issued_qty}${unit}，计划 ${analysis.dimensions.work_order_usage.planned_qty}${unit}，退料 ${analysis.dimensions.work_order_usage.returned_qty}${unit}，最近 100 条）`}>
              <Table size="small" rowKey={(r) => `${r.REFWO}-${r.ACTUALDATE}-${r.QUANTITY}`} columns={usageColumns} dataSource={analysis.dimensions.work_order_usage.details} pagination={{ pageSize: 5 }} scroll={{ x: 900 }} />
            </Card>
            <Card size="small" title={`库存分布（合计 ${analysis.dimensions.stock_balance.total_qty}${unit}）`}>
              <Table size="small" rowKey={(r) => `${r.LOCATION}-${r.BINNUM}-${r.LOTNUM}`} columns={stockColumns} dataSource={analysis.dimensions.stock_balance.details} pagination={false} scroll={{ x: 600 }} />
            </Card>
            <Card size="small" title={`预留明细（合计 ${analysis.dimensions.reservations.total_qty}${unit}）`}>
              <Table size="small" rowKey={(r) => `${r.LOCATION}-${r.WONUM}-${r.REQUIREDDATE}`} columns={reserveColumns} dataSource={analysis.dimensions.reservations.details} pagination={{ pageSize: 5 }} scroll={{ x: 600 }} />
            </Card>
          </>
        )}

        {!itemnum && (
          <Card size="small" title="搜索立项申请行（支持索引切换的联想搜索）">
            <PrLineSearchSelect onPick={(record) => { analyzeByCode(record.ITEMNUM, record.PRNUM, record.PRLINENUM != null ? String(record.PRLINENUM) : null); analyze(record.ITEMNUM, record.PRNUM, record.PRLINENUM != null ? String(record.PRLINENUM) : null); }} />
          </Card>
        )}
      </Space>
    </div>
  );
}
