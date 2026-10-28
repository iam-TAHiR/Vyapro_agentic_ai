# Synthetic demo import files

Every record in this folder is invented sample data using `DEMO-` identifiers. These files are not real customers, products, prices, inventory, or order history. The application never imports them automatically. Upload each sample through the preview and confirmation screen in a local demo only after reviewing it.

Supported CSV templates are provided separately for customers, products, inventory updates, customer-specific prices, and previous-order history. XLSX workbooks use one supported dataset per sheet (sheet names: `customers`, `products`, `inventory`, `prices`, `previous_orders`).

For the end-to-end order demo, import in this order: `customers.csv`, `products.csv`, `inventory.csv`, then `prices.csv`. The intended checks are a routine 2 kg rice request for Sample Corner Shop, a 2 litre cooking-oil request for Sample Low Credit Shop (credit hold), and a 3 litre cooking-oil request for Sample Corner Shop (stock hold). Actual outcomes always come from current database values and the backend; the examples are not guaranteed if records have since changed. `previous_orders.csv` is optional and remains isolated historical data.
