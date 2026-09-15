# Demo Data Contract

The demo planning dataset is generated into the configured MySQL database at application startup. It is intentionally deterministic and idempotent: restarting the API adds missing records but does not duplicate existing rows.

The table design follows common ERP inventory data fields reviewed from the public ERPNext Stock Entry documentation:

- `item_code` -> `materials.sku`
- `warehouse` -> `inventory_snapshots.warehouse_id` and `stock_movements.warehouse_id`
- `qty` -> `quantity` / `available_quantity`
- `uom` -> `unit`
- `posting_date` -> `posting_date` / `used_at` / `recorded_at`
- supplier and unit price history -> `suppliers` / `price_records`

Reference: https://docs.frappe.io/erpnext/user/manual/en/stock-entry

The generated planning rows cover 15 additional SKUs, two warehouses per SKU, 24 monthly usage observations, and 24 monthly supplier price observations. The existing showcase SKUs are also backfilled to 24 months so the default purchase, forecast, and price pages use database history.

To use an existing host MySQL instead of the bundled container, set `DATABASE_URL` in `.env` before starting Compose, for example `mysql+aiomysql://user:password@host.docker.internal:3306/liku`. The API, purchase engine, transfer matcher, forecast service, and price service all use this configured database connection.
