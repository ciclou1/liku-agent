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
