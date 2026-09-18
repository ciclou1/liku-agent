export interface InventoryItem {
  sku: string;
  name: string;
  warehouse_id: string;
  warehouse_name: string;
  available_quantity: number;
  in_transit: number;
  unit_cost: number;
  safety_stock: number;
  last_used_at: string | null;
  expiry_date: string | null;
}

export interface ApiResponse<T> {
  data: T;
  request_id?: string;
}

export interface WarningItem {
  sku: string;
  warehouse_id: string;
  warning_type: string;
  level: string;
  message: string;
  action: string;
  amount: number;
}

export interface ForecastData {
  sku: string;
  warehouse_id: string;
  pattern: string;
  history: Array<{ period: string; usage: number }>;
  forecast: Array<{ period: string; value: number; lower: number; upper: number }>;
  corrected: boolean;
  model_name: string;
  backtest: Record<string, string | number>;
  narrative: string;
}

export interface PriceData {
  sku: string;
  periods: string[];
  prices: number[];
  direction: string;
  signal: string;
  expected_saving: number;
  history: Array<{ sku: string; supplier: string; price: number; recorded_at: string }>;
  narrative: string;
  model_name: string;
}

export interface MaterialOption {
  sku: string;
  name: string;
  category: string;
  unit: string;
  package_size: number;
  shelf_life_days: number | null;
}

export interface DormantItem {
  sku: string;
  name: string;
  unit: string;
  warehouse_id: string;
  warehouse_name: string;
  available_quantity: number;
  unit_cost: number;
  last_used_at: string | null;
  amount: number;
  days_idle: number | null;
  suggestion: string;
  action: string;
  basis: string;
}

export interface DormantResponse {
  items: DormantItem[];
  total: number;
  page: number;
  size: number;
  threshold_days: number;
  page_amount: number;
  summary: { transfer: number; return: number; scrap: number };
}

export interface ReplenishmentDetail {
  sku: string;
  name: string;
  unit: string;
  warehouse_id: string;
  monthly_usage: Array<{ month: string; usage: number }>;
  lead_time_months: number;
  lead_time_source: string;
  lead_time_detail: Record<string, unknown> | null;
  available: number;
  in_transit: number;
  current_safety: number;
  insufficient_data: boolean;
  min_months_required: number;
  mu_monthly?: number;
  sigma_monthly?: number;
  service_level_z?: number;
  suggested_safety?: number;
  safety_gap?: number;
  reorder_point?: number;
  reorder_quantity?: number;
  coverage_months?: number;
  months_used?: number;
  formula_explanation?: Record<string, string>;
}

export interface ReplenishmentBatch {
  items: Array<{
    sku: string;
    name: string;
    unit: string;
    mu_monthly: number;
    sigma_monthly: number;
    current_safety: number;
    suggested_safety: number;
    safety_gap: number;
    reorder_point: number;
    reorder_quantity: number;
  }>;
  lead_time_months: number;
  lead_time_source: string;
  note?: string;
}
