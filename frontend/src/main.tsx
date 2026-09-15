import "antd/dist/reset.css";
import "./styles.css";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppLayout, LoginPage } from "./App";
import { DashboardPage } from "./pages/DashboardPage";
import { ChatPage, ForecastPage, PricesPage, PurchasesPage, TransfersPage, WarningsPage } from "./pages/OperationsPages";
import { DatabaseSettingsPage } from "./pages/DatabaseSettingsPage";
import { ErpAnalysisPage } from "./pages/ErpAnalysisPage";

createRoot(document.getElementById("root")!).render(<BrowserRouter><Routes><Route path="/login" element={<LoginPage />} /><Route element={<AppLayout />}><Route path="/" element={<DashboardPage />} /><Route path="/erp/analysis" element={<ErpAnalysisPage />} /><Route path="/dashboard" element={<DashboardPage />} /><Route path="/purchases" element={<PurchasesPage />} /><Route path="/transfers" element={<TransfersPage />} /><Route path="/forecast" element={<ForecastPage />} /><Route path="/prices" element={<PricesPage />} /><Route path="/warnings" element={<WarningsPage />} /><Route path="/chat" element={<ChatPage />} /><Route path="/settings/database" element={<DatabaseSettingsPage />} /></Route></Routes></BrowserRouter>);
