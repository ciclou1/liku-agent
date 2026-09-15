# UI and Chatbot Acceptance

Date: 2026-09-08

- Purchase page now renders Chinese business labels, a natural-language recommendation summary, approval status labels, and database source information.
- Transfer page has condition controls for material, target warehouse, and minimum quantity. It renders actual route, quantity, distance, and lead-time results.
- Forecast page supports material and warehouse selection, renders the historical/forecast interval chart, shows history point count, and retains correction submission.
- Price timing page supports material selection, trend and timing labels, forecast chart, price history table, and expected saving.
- Warning center links to the transfer page with the warning material and warehouse query parameters.
- Chatbot resolves Chinese aliases such as `M12螺栓` to `M12-BOLT`, queries MySQL inventory, and returns natural language facts with Chinese source tags.
- Serial UTF-8 request for `M12螺栓哪个仓库有现货` selected `query_inventory`, returned two sources, and produced a non-empty database-backed answer.
- Regression: 56 backend tests passed; frontend tests and production build passed.
