import { Button, Layout, Space, Tag, Typography } from "antd";
import { useState } from "react";
import { Navigate, Outlet, useLocation, useNavigate } from "react-router-dom";
import { api } from "./api/client";

const { Header, Content } = Layout;

// hidden: 仅从顶部导航隐藏，路由保留（旧书签/URL 仍可访问）
const NAV_ITEMS = [
  { key: "/erp/analysis", label: "平衡利库分析" },
  { key: "/chat", label: "智能问答" },
  { key: "/dormant", label: "呆滞识别" },
  { key: "/safety-stock", label: "安全库存优化" },
  { key: "/purchases", label: "采购建议", hidden: true },
  { key: "/transfers", label: "利库调剂", hidden: true },
  { key: "/forecast", label: "需求预测", hidden: true },
  { key: "/prices", label: "价格择时", hidden: true },
  { key: "/settings/database", label: "数据库设置", hidden: true },
];

export function AppLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const activeKey = NAV_ITEMS.find((item) => location.pathname.startsWith(item.key))?.key ?? "/erp/analysis";
  if (!localStorage.getItem("liku_token")) return <Navigate to="/login" replace />;
  return <Layout style={{ minHeight: "100vh" }}>
    <Header className="app-header">
      <Space className="app-brand" size={8}>
        <Typography.Title level={4} style={{ margin: 0, whiteSpace: "nowrap" }}>AI 平衡利库工作台</Typography.Title>
        <Tag color="blue">ERP 只读</Tag>
      </Space>
      {/* 全部导航平铺展示（窄屏换行，不折叠进 "…"），当前页高亮 */}
      <nav className="app-nav">
        {NAV_ITEMS.filter((item) => !item.hidden).map((item) => (
          <Button key={item.key} size="small" className="app-nav-item"
                  type={activeKey === item.key ? "primary" : "text"}
                  onClick={() => navigate(item.key)}>{item.label}</Button>
        ))}
      </nav>
      <Button size="small" onClick={() => { localStorage.removeItem("liku_token"); window.location.href = "/login"; }}>退出</Button>
    </Header>
    <Content className="app-content"><Outlet /></Content>
  </Layout>;
}

export function LoginPage() {
  const navigate = useNavigate();
  const [username, setUsername] = useState("demo");
  const [password, setPassword] = useState("demo");
  const [error, setError] = useState("");
  const submit = async () => { try { const result = await api.login(username, password); localStorage.setItem("liku_token", result.access_token); localStorage.setItem("liku_role", result.role); navigate("/"); } catch (reason) { setError(reason instanceof Error ? reason.message : "登录失败"); } };
  return <div className="login-page"><div className="login-panel"><Typography.Title level={2}>平衡利库智能体</Typography.Title><Typography.Paragraph type="secondary">库存决策工作台</Typography.Paragraph><Space direction="vertical" style={{ width: "100%" }}><input value={username} onChange={(event) => setUsername(event.target.value)} placeholder="用户名" /><input value={password} onChange={(event) => setPassword(event.target.value)} placeholder="密码" type="password" /><Button type="primary" block onClick={submit}>登录</Button>{error && <Typography.Text type="danger">{error}</Typography.Text>}</Space></div></div>;
}
