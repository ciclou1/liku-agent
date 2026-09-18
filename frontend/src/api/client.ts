import type { ApiResponse, DormantResponse, ForecastData, InventoryItem, MaterialOption, PriceData, ReplenishmentBatch, ReplenishmentDetail, WarningItem } from "../types/domain";

// 默认走同源 /api（vite 代理到后端），本机/内网 IP 访问均自动正确；可用 VITE_API_BASE_URL 覆盖
const baseUrl = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = localStorage.getItem("liku_token");
  const response = await fetch(`${baseUrl}${path}`, { headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}), ...init?.headers }, ...init });
  if (response.status === 401) {
    localStorage.removeItem("liku_token");
    localStorage.removeItem("liku_role");
    if (window.location.pathname !== "/login") window.location.assign("/login");
    throw new Error("Login expired. Please sign in again.");
  }
  if (!response.ok) {
    const failure = await response.json().catch(() => ({}));
    throw new Error(typeof failure.detail === "string" ? failure.detail : `请求失败（${response.status}）`);
  }
  const payload = (await response.json()) as ApiResponse<T>;
  return payload.data;
}

export const api = {
  testDatabaseSource: (source: DatabaseSource) => request<{ database_url: string; message: string }>("/admin/database/test", { method: "POST", body: JSON.stringify(source) }),
  saveDatabaseSource: (source: DatabaseSource) => request<{ message: string; restart_required: boolean; name: string }>("/admin/database/source", { method: "POST", body: JSON.stringify(source) }),
  importErpData: () => request<{ source: string; replaced_demo_data: boolean; imported: Record<string, number> }>("/admin/erp/import", { method: "POST" }),
  login: (username: string, password: string) => request<{ access_token: string; role: string }>("/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }),
  databaseConfig: () => request<{ database_type: string; database_url: string; profiles: Record<string, { label: string; example: string; runtime: boolean }> }>("/admin/database"),
  switchDatabase: (database_type: string, database_url: string) => request<{ message: string; restart_required: boolean }>("/admin/database/switch", { method: "POST", body: JSON.stringify({ database_type, database_url }) }),
  health: () => request<{ status: string }>("/health"),
  dashboard: () => request<Record<string, number>>("/dashboard/health"),
  inventory: (query?: string, limit = 100, offset = 0) => {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (query) params.set("query", query);
    return request<InventoryItem[]>(`/inventory?${params.toString()}`);
  },
  materials: (query?: string, limit = 50) => request<MaterialOption[]>(`/materials${(query || limit !== 50) ? `?${new URLSearchParams({ ...(query ? { query } : {}), limit: String(limit) }).toString()}` : ""}`),
  warehouses: () => request<Array<{ warehouse_id: string; name: string }>>("/warehouses"),
  warnings: () => request<WarningItem[]>("/warnings"),
  forecast: (sku: string, warehouseId = "W1") => request<ForecastData>(`/forecast/${encodeURIComponent(sku)}?warehouse_id=${warehouseId}`),
  correctForecast: (sku: string, values: number[], warehouseId = "W1") => request<ForecastData>(`/forecast/${encodeURIComponent(sku)}/correction?warehouse_id=${warehouseId}`, { method: "POST", body: JSON.stringify({ values }) }),
  prices: (sku: string) => request<PriceData>(`/prices/${encodeURIComponent(sku)}`),
  transfers: (filters?: { sku?: string; target_warehouse_id?: string; min_quantity?: number }) => {
    const params = new URLSearchParams();
    if (filters?.sku) params.set("sku", filters.sku);
    if (filters?.target_warehouse_id) params.set("target_warehouse_id", filters.target_warehouse_id);
    if (filters?.min_quantity) params.set("min_quantity", String(filters.min_quantity));
    const query = params.toString();
    return request<Array<Record<string, string | number>>>(`/transfers${query ? `?${query}` : ""}`);
  },
  generateTransfers: (filters: { sku?: string; target_warehouse_id?: string; min_quantity?: number }) => request<Array<Record<string, string | number>>>("/transfers/generate", { method: "POST", body: JSON.stringify(filters) }),
  purchase: (payload: Record<string, string | number>) => request<Record<string, unknown>>("/purchase-recommendations", { method: "POST", body: JSON.stringify(payload) }),
  generatePurchase: (sku: string, warehouseId: string) => request<Record<string, unknown>>("/purchase-recommendations/generate", { method: "POST", body: JSON.stringify({ sku, warehouse_id: warehouseId }) }),
  recommendations: () => request<Array<Record<string, unknown>>>("/purchase-recommendations"),
  updateRecommendation: (id: string, status: string) => request<Record<string, unknown>>(`/purchase-recommendations/${id}`, { method: "PATCH", body: JSON.stringify({ status }) }),
  pushRecommendation: (id: string) => request<Record<string, unknown>>(`/purchase-recommendations/${id}/push`, { method: "POST" }),
  exportRecommendations: () => fetch(`${baseUrl}/purchase-recommendations/export`, { headers: { Authorization: `Bearer ${localStorage.getItem("liku_token") ?? ""}` } }),
  chat: (message: string, sessionId?: string) => request<{ session_id: string; answer: string; sources: string[] }>("/chat", { method: "POST", body: JSON.stringify({ message, session_id: sessionId }) }),
  dormant: (params: { threshold_days?: number; warehouse_id?: string; page?: number; size?: number }) => {
    const query = new URLSearchParams();
    if (params.threshold_days) query.set("threshold_days", String(params.threshold_days));
    if (params.warehouse_id) query.set("warehouse_id", params.warehouse_id);
    if (params.page) query.set("page", String(params.page));
    if (params.size) query.set("size", String(params.size));
    return request<DormantResponse>(`/dormant?${query.toString()}`);
  },
  dormantExport: () => fetch(`${baseUrl}/dormant/export`, { headers: { Authorization: `Bearer ${localStorage.getItem("liku_token") ?? ""}` } }),
  replenishmentDetail: (sku: string, params?: { warehouse_id?: string; coverage_months?: number; lead_time_months?: number }) => {
    const query = new URLSearchParams();
    if (params?.warehouse_id) query.set("warehouse_id", params.warehouse_id);
    if (params?.coverage_months) query.set("coverage_months", String(params.coverage_months));
    if (params?.lead_time_months) query.set("lead_time_months", String(params.lead_time_months));
    const suffix = query.toString();
    return request<ReplenishmentDetail>(`/replenishment/${encodeURIComponent(sku)}${suffix ? `?${suffix}` : ""}`);
  },
  replenishmentBatch: (params?: { warehouse_id?: string; limit?: number }) => {
    const query = new URLSearchParams();
    if (params?.warehouse_id) query.set("warehouse_id", params.warehouse_id);
    if (params?.limit) query.set("limit", String(params.limit));
    const suffix = query.toString();
    return request<ReplenishmentBatch>(`/replenishment${suffix ? `?${suffix}` : ""}`);
  },
  replenishmentExport: () => fetch(`${baseUrl}/replenishment/export`, { headers: { Authorization: `Bearer ${localStorage.getItem("liku_token") ?? ""}` } }),
};

export interface DatabaseSource {
  database_type: "mysql" | "postgresql" | "dameng" | "sqlite";
  name: string;
  host: string;
  port: number;
  username: string;
  password: string;
  database: string;
}
