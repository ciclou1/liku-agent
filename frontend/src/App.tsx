import { AppstoreOutlined, BellOutlined, BulbOutlined, DashboardOutlined, LineChartOutlined, MenuFoldOutlined, MenuUnfoldOutlined, MessageOutlined, SearchOutlined, SwapOutlined } from "@ant-design/icons";
import { Button, Layout, Menu, Space, Tag, Tooltip, Typography } from "antd";
import { useState } from "react";
import { Link, Navigate, Outlet, useLocation, useNavigate } from "react-router-dom";
import { api } from "./api/client";
import { canAccessRoute } from "./utils/permissions";

const { Header, Sider, Content } = Layout;
const items = [
  { key: "/", icon: <DashboardOutlined />, label: <Link to="/">库存健康度</Link> },
  { key: "/erp/analysis", icon: <SearchOutlined />, label: <Link to="/erp/analysis">AI 平衡利库</Link> },
  { key: "/purchases", icon: <AppstoreOutlined />, label: <Link to="/purchases">采购建议</Link> },
  { key: "/transfers", icon: <SwapOutlined />, label: <Link to="/transfers">利库调剂</Link> },
  { key: "/forecast", icon: <LineChartOutlined />, label: <Link to="/forecast">需求预测</Link> },
  { key: "/prices", icon: <BulbOutlined />, label: <Link to="/prices">价格择时</Link> },
  { key: "/warnings", icon: <BellOutlined />, label: <Link to="/warnings">预警中心</Link> },
  { key: "/chat", icon: <MessageOutlined />, label: <Link to="/chat">智能问答</Link> },
  { key: "/settings/database", icon: <DashboardOutlined />, label: <Link to="/settings/database">数据库连接</Link> },
];

export function AppLayout() {
  const [collapsed, setCollapsed] = useState(false);
  const location = useLocation();
  const role = localStorage.getItem("liku_role") ?? "manager";
  const visibleItems = items.filter((item) => canAccessRoute(role, item.key)).map((item) => item.key === "/settings/database" ? { ...item, disabled: role !== "admin" } : item);
  if (!localStorage.getItem("liku_token")) return <Navigate to="/login" replace />;
  return <Layout style={{ minHeight: "100vh" }}>
    <Sider collapsible collapsed={collapsed} trigger={null} width={224} className="app-sider">
      <div className="brand">{collapsed ? "利库" : "平衡利库智能体"}</div>
      <Menu theme="dark" mode="inline" selectedKeys={[location.pathname]} items={visibleItems} />
    </Sider>
    <Layout>
      <Header className="app-header"><Space><Tooltip title="切换导航"><button className="collapse-button" onClick={() => setCollapsed(!collapsed)} aria-label="切换导航">{collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}</button></Tooltip><Typography.Title level={4} style={{ margin: 0 }}>库存决策工作台</Typography.Title></Space><Space><Tag color="blue">ERP 只读</Tag><Button size="small" onClick={() => { localStorage.removeItem("liku_token"); window.location.href = "/login"; }}>退出</Button></Space></Header>
      <Content className="app-content"><Outlet /></Content>
    </Layout>
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
