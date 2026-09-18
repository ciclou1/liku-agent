import "antd/dist/reset.css";
import "./styles.css";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppLayout, LoginPage } from "./App";
import { ForecastPage, PricesPage, PurchasesPage, TransfersPage, ChatPage } from "./pages/OperationsPages";
import { DatabaseSettingsPage } from "./pages/DatabaseSettingsPage";
import { DormantPage } from "./pages/DormantPage";
import { ErpAnalysisPage } from "./pages/ErpAnalysisPage";
import { SafetyStockPage } from "./pages/SafetyStockPage";

createRoot(document.getElementById("root")!).render(<BrowserRouter><Routes><Route path="/login" element={<LoginPage />} /><Route element={<AppLayout />}><Route path="/" element={<Navigate to="/erp/analysis" replace />} /><Route path="/erp/analysis" element={<ErpAnalysisPage />} /><Route path="/dashboard" element={<Navigate to="/erp/analysis" replace />} /><Route path="/purchases" element={<PurchasesPage />} /><Route path="/transfers" element={<TransfersPage />} /><Route path="/forecast" element={<ForecastPage />} /><Route path="/prices" element={<PricesPage />} /><Route path="/warnings" element={<Navigate to="/dormant" replace />} /><Route path="/chat" element={<ChatPage />} /><Route path="/dormant" element={<DormantPage />} /><Route path="/safety-stock" element={<SafetyStockPage />} /><Route path="/settings/database" element={<DatabaseSettingsPage />} /></Route></Routes></BrowserRouter>);
