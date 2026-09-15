# Database Planning Acceptance

Date: 2026-09-08

Reference data model: public ERPNext Stock Entry documentation, https://docs.frappe.io/erpnext/user/manual/en/stock-entry. The demo mapping uses item code, warehouse, quantity, unit, posting date, supplier, and unit price fields.

Database evidence against local MySQL:

- 20 materials
- 36 inventory snapshots
- 792 usage records covering 24 monthly observations per generated SKU and warehouse
- 436 price records covering 24 monthly observations and supplier history

Serial API acceptance against `http://localhost:18000/api/v1`:

- `POST /purchase-recommendations/generate` for `DEMO-MAT-001/W2`: HTTP 200, source `mysql`, forecast demand `61.025`, purchase quantity `90`, model `AutoARIMA`.
- `GET /transfers?sku=DEMO-MAT-001&target_warehouse_id=W2&min_quantity=1`: HTTP 200, one recommendation, `W1 -> W2`, quantity `44`, distance `12 km`.
- `GET /forecast/DEMO-MAT-001?warehouse_id=W1`: HTTP 200, 24 history points and 12 forecast points.
- `GET /prices/DEMO-MAT-001`: HTTP 200, 24 price history rows, 3 forecast periods, timing signal returned.

Regression evidence:

- Python 3.13 backend: `56 passed`.
- Frontend: 2 tests passed and production build passed.
- Frontend endpoint returned HTTP 200 at `http://localhost:5173`.

Remaining risk: external customer MySQL credentials and schema permissions must be supplied for customer-environment integration. The bundled schema remains the runnable demo contract.
