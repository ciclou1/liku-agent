import { Alert, Button, Card, Form, Input, InputNumber, Modal, Popconfirm, Select, Space, Typography } from "antd";
import { useEffect, useState } from "react";
import { api, type DatabaseSource } from "../api/client";
import { SpacePage } from "./DashboardPage";

const engines = {
  postgresql: { label: "PostgreSQL / openGauss / 人大金仓（PG协议）", port: 5432, username: "postgres", driver: "asyncpg（已内置；兼容数据库需实际测试）" },
  mysql: { label: "MySQL / MariaDB（MySQL协议）", port: 3306, username: "liku", driver: "aiomysql（已内置）" },
  dameng: { label: "达梦 DM", port: 5236, username: "SYSDBA", driver: "dmPython（当前异步适配未就绪，暂不可启用）" },
  sqlite: { label: "SQLite", port: 1, username: "", driver: "aiosqlite（已内置）" },
};

export function DatabaseSettingsPage() {
  const [form] = Form.useForm<DatabaseSource>();
  const kind = Form.useWatch("database_type", form) ?? "postgresql";
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<"test" | "save" | "erp" | null>(null);
  const [connection, setConnection] = useState("");
  const [result, setResult] = useState<{ type: "success" | "error" | "info"; text: string }>();
  const [saved, setSaved] = useState("");
  const isAdmin = localStorage.getItem("liku_role") === "admin";
  const host = Form.useWatch("host", form) ?? "";
  const database = Form.useWatch("database", form) ?? "";
  const isErpDatabase = kind === "mysql" && host.trim() === "172.20.0.114" && database.trim().toLowerCase() === "php_saas";
  useEffect(() => {
    if (isAdmin) void api.databaseConfig().then(data => setConnection(data.database_url)).catch(error => setResult({ type: "error", text: error.message }));
  }, [isAdmin]);

  const submit = async (action: "test" | "save") => {
    if (busy || !isAdmin) return;
    let fields: DatabaseSource;
    try { fields = await form.validateFields(); } catch { return; }
    if (action === "save" && isErpDatabase) {
      setResult({ type: "error", text: "积木 ERP 原始库不能保存为 agent 业务库，请使用 ERP 专用同步/分析入口" });
      return;
    }
    setBusy(action);
    setResult(undefined);
    try {
      if (action === "test") {
        const response = await api.testDatabaseSource(fields);
        setResult({ type: "success", text: `${response.message}：${response.database_url}` });
      } else {
        const response = await api.saveDatabaseSource(fields);
        setSaved(`${fields.name || engines[kind].label}：${response.message}。现有数据不会自动迁移到目标库。`);
        setOpen(false);
        form.resetFields();
      }
    } catch (error) {
      setResult({ type: "error", text: error instanceof Error ? error.message : "请求失败，请稍后重试" });
    } finally { setBusy(null); }
  };

  const importErp = async () => {
    if (busy || !isAdmin) return;
    setBusy("erp");
    setResult(undefined);
    try {
      const baseUrl = "/api/v1";
      const headers = { "Content-Type": "application/json", Authorization: `Bearer ${localStorage.getItem("liku_token") ?? ""}` };
      await fetch(`${baseUrl}/erp/sync-inventory`, { method: "POST", headers });
      // 轮询后台同步进度（全量同步约 1-3 分钟）
      setSaved("ERP 数据同步已启动，正在后台执行…");
      for (;;) {
        await new Promise((resolve) => setTimeout(resolve, 2000));
        const statusResponse = await fetch(`${baseUrl}/erp/sync-inventory/status`, { headers });
        const statusPayload = (await statusResponse.json()) as { data: { running: boolean; stage: string; counts: Record<string, number>; error: string | null } };
        const status = statusPayload.data;
        setSaved(`同步中：${status.stage} · ${Object.entries(status.counts).map(([k, v]) => `${k} ${v}`).join("，")}`);
        if (!status.running) {
          if (status.error) { setResult({ type: "error", text: `同步失败：${status.error}` }); setSaved(""); }
          else {
            const rows = Object.entries(status.counts).map(([key, value]) => `${key} ${value}`).join("，");
            setSaved(`ERP 真实数据同步完成：${rows}。各功能页已切换为 ERP 数据。`);
          }
          break;
        }
      }
    } catch (error) {
      setResult({ type: "error", text: error instanceof Error ? error.message : "ERP 导入失败，本地数据未变更" });
    } finally { setBusy(null); }
  };

  if (!isAdmin) return <SpacePage title="数据库配置" subtitle="管理员专用"><Alert type="info" showIcon message="仅管理员可以添加和切换数据源" /></SpacePage>;
  return <SpacePage title="数据库配置" subtitle="添加目标数据源并测试连接，保存为下次启动使用的数据库。">
    <Card title="数据库连接" extra={<Space><Popconfirm title="导入 ERP 数据" description="将替换当前本地演示业务数据；ERP 读取失败时不会清理本地数据。" okText="开始导入" cancelText="取消" onConfirm={() => void importErp()}><Button loading={busy === "erp"}>导入 ERP 数据</Button></Popconfirm><Button type="primary" onClick={() => { setResult(undefined); setOpen(true); }}>添加数据源</Button></Space>}>
      <Typography.Paragraph>已配置连接：<Typography.Text code>{connection || "加载中"}</Typography.Text></Typography.Paragraph>
      {saved && <Alert showIcon type="success" message={saved} />}
      {!open && result?.type === "error" && <Alert showIcon type="error" message={result.text} />}
    </Card>
    <Modal title="添加数据源" className="database-source-modal" open={open} width={838} centered maskClosable={!busy} closable={!busy} onCancel={() => { if (!busy) { setOpen(false); form.resetFields(); } }} footer={<Space size={16}>
      <Button disabled={!!busy} onClick={() => { setOpen(false); form.resetFields(); }}>取消</Button>
      <Button disabled={!!busy || kind === "dameng"} loading={busy === "test"} onClick={() => void submit("test")}>生成并测试</Button>
      <Button type="primary" disabled={!!busy || kind === "dameng"} loading={busy === "save"} onClick={() => void submit("save")}>保存</Button>
    </Space>}>
      {isErpDatabase && (
        <Alert
          style={{ marginBottom: 16 }}
          type="warning"
          showIcon
          message="这是积木 ERP 原始数据库，不是 agent 业务数据库"
          description="请不要在此页面保存或切换。保持 agent 的演示/业务库不变，通过 ERP 平衡利库页面或 agent2 的积木 ERP 同步入口读取数据。"
        />
      )}
      <Form form={form} layout="horizontal" labelCol={{ flex: "165px" }} wrapperCol={{ flex: 1 }} size="large" colon={false} initialValues={{ database_type: "postgresql", name: "", host: "", port: 5432, username: "", password: "", database: "" }} onValuesChange={() => setResult(undefined)}>
        <Form.Item name="database_type" label="数据库类型"><Select options={Object.entries(engines).map(([value, item]) => ({ value, label: item.label }))} onChange={value => { form.setFieldsValue({ port: engines[value as keyof typeof engines].port }); setResult(undefined); }} /></Form.Item>
        <Form.Item name="name" label="数据源名称"><Input placeholder="如：生产库-达梦" maxLength={100} /></Form.Item>
        {kind !== "sqlite" && <>
          <Form.Item name="host" label="主机" rules={[{ required: true, whitespace: true, message: "请输入主机地址" }]}><Input placeholder="192.168.1.100" /></Form.Item>
          <Form.Item name="port" label="端口" rules={[{ required: true, message: "请输入端口" }]}><InputNumber min={1} max={65535} precision={0} style={{ width: "100%" }} controls={false} /></Form.Item>
          <Form.Item name="username" label="用户名" rules={[{ required: true, whitespace: true, message: "请输入用户名" }]}><Input placeholder={engines[kind].username} autoComplete="off" /></Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true, message: "请输入密码" }]}><Input.Password autoComplete="new-password" /></Form.Item>
        </>}
        <Form.Item name="database" label={kind === "sqlite" ? "数据库文件名" : "数据库名"} rules={[{ required: true, whitespace: true, message: "请输入数据库名" }]}><Input placeholder={kind === "sqlite" ? "demo.db" : "invclos"} /></Form.Item>
      </Form>
      <div className="database-driver-note">驱动要求：{engines[kind].driver}</div>
      {result && <Alert style={{ marginTop: 16 }} showIcon type={result.type} message={result.text} />}
    </Modal>
  </SpacePage>;
}
