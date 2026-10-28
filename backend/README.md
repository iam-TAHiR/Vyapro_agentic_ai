# Vyapro local demo

Vyapro is a React/Vite frontend with a Flask API and MySQL persistence. The current backend supports customer/inventory reads and a web-text order proposal, validation, clarification, approval, order history, and audit workflow. Phone and messaging channels are not connected.

## Local setup

Python 3.10 or newer and a local MySQL server are required. From the repository root, prepare the backend:

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `backend/.env` with the local MySQL host, database, user and password. The database itself must already exist. Real `.env` files are ignored by Git. The MySQL user needs table creation rights to run migrations and read/write rights for local order workflows.

Apply the additive migrations and start Flask:

```powershell
python migrate.py
python run.py
```

The migration runner creates its ledger and the current customer, product/inventory, substitution, proposal, order, and audit tables. It does not delete or reset data. If a migration fails, stop and inspect the error and current schema before retrying.

### Seed a local development business dataset

`python seed_dev.py` inserts eight **fictional** wholesale customers, twenty fictional products, aliases, explicit substitution/pricing relationships, and sixteen dated historical orders. The dataset is for local development only; these names do not represent real businesses. Seed records are ordinary customer/catalog/order records, without a demo badge in the application. The command requires `VYAPRO_ENV=development`, configured MySQL, and a database name ending in `_dev` or `_development`. It only inserts missing records, skips existing identifiers, and refuses to associate historical records with conflicting customer/product records. It does not change stock or current credit balances when adding historical orders. Re-running it is safe.

```powershell
python migrate.py
python seed_dev.py
```

Review the JSON output's `verified` counts after it finishes. A clean seed should verify 8 customers, 20 products, 16 previous orders, and 16 matching order activity events. The seed has not been loaded unless that command completed successfully against your local development database.

In a second terminal, start the existing frontend:

```powershell
cd frontend
pnpm install
pnpm dev
```

Vite proxies `/api` requests to `http://127.0.0.1:5000` by default. If Flask uses another local port, set `VITE_API_PROXY_TARGET` before starting Vite; this keeps browser requests same-origin and avoids direct cross-origin API calls. For example, if Flask is on port 5001:

```powershell
$env:VITE_API_PROXY_TARGET = 'http://127.0.0.1:5001'
pnpm dev
```

The browser does not receive database credentials or the LLM key.

## LLM configuration

Natural-language proposal creation needs an OpenAI-compatible Chat Completions endpoint that supports JSON object responses. Configure these backend-only values in `.env`:

```text
VYAPRO_LLM_BASE_URL=https://provider-host.example
VYAPRO_LLM_MODEL=provider-model-name
VYAPRO_LLM_API_KEY=your-provider-key
VYAPRO_LLM_TIMEOUT=20
VYAPRO_TRANSCRIPTION_MODEL=provider-audio-model-name
```

Use a provider that implements both OpenAI-compatible Chat Completions with JSON object mode and `/v1/audio/transcriptions`. Use the provider's API origin as the base URL; the backend appends those endpoint paths. Model names and the key come from the provider you choose. No provider account is created by this project. Calls can incur provider charges under that account. Without chat settings, the separate agent assistant and LLM-based clarification return `LLM_NOT_CONFIGURED`; without transcription settings, audio returns `TRANSCRIPTION_NOT_CONFIGURED`. The deterministic Customer Ordering proposal flow does not need a provider. No path fabricates results.

## Available endpoints

- `GET /api/v1/health` checks Flask without requiring MySQL.
- `GET /api/v1/health/database` runs `SELECT 1` against MySQL.
- `GET /api/v1/customers` reads customers and their credit balances.
- `GET /api/v1/inventory` reads products, stock quantities and unit prices.
- `POST /api/v1/order-proposals` prepares a web proposal through the deterministic order parser, matches the selected customer and catalog product records, then checks stock/pricing/credit and stores a proposal. Requires `customerId` and `Idempotency-Key`. This customer order flow does not use an LLM.
- `POST /api/v1/audio/order-proposals` transcribes a browser recording or uploaded audio and feeds the transcript into the same proposal workflow. Requires a transcription model and the same LLM API key.
- `POST /api/v1/order-proposals/{id}/clarifications` reinterprets the original request with a clarification. Requires the proposal version and `Idempotency-Key`.
- `POST /api/v1/order-proposals/{id}/approval` accepts or rejects a proposal. Approval rechecks current stock, prices and customer credit in a transaction. Substitutions require explicit acceptance.
- `GET /api/v1/customer-orders?customerId=...` returns saved order statuses for the selected local-demo account. This is not authentication and is development-only.
- `POST /api/v1/orders/{id}/fulfill-pending` requires `{"confirm": true}` and an `Idempotency-Key`. It rechecks current stock and customer credit in one transaction, fulfills only the quantity currently available, and records an audit event. It never reports an unverified restock date.
- `GET /api/v1/order-proposals` and `GET /api/v1/order-proposals/{id}` support the review queue.
- `GET /api/v1/orders`, `GET /api/v1/orders/{id}`, and `GET /api/v1/orders/{id}/events` read saved orders and audit history.

All non-health APIs are restricted to `VYAPRO_ENV=development` until authentication and authorization are implemented. Local approvals are therefore suitable only for the localhost demo, not a public deployment. Web text and uploaded/browser-recorded voice are supported when their provider settings are present. Phone and messaging have not been integrated.

The deterministic web parser accepts one `quantity unit product` item per line (or semicolon-separated), for example `2 kg India Gate Basmati Rice`. It matches the longest exact catalog name, SKU, or explicit alias and uses MySQL product IDs and the selected registered customer ID. It does not correct misspellings, infer omitted quantities, or invent products. Substitutions are offered only for relationships recorded in `product_substitutions`; this project does not invent product equivalence. No business data is inserted automatically during startup or migration. Enter records through the import workflow or explicitly run the development-only seed command above before proposals can pass validation.

### Stock-shortage handling

If a matched product has some stock but less than requested, and no configured substitute can cover the full request, Vyapro offers the current available quantity and records the remainder as pending. For example, a request for 10 kg with 5 kg available is presented as 5 kg now and 5 kg pending, with no restock-date promise. The customer must explicitly accept this split. Proposal creation does not reserve or deduct stock.

On explicit acceptance, the backend locks and rechecks the live product, applicable price and customer credit. It deducts only the accepted quantity, charges credit only for that quantity, stores the original requested quantity and pending remainder, marks the order `partially_fulfilled`, and records the quantities in its audit history. Rejection or a failed recheck leaves stock and credit unchanged.

The shopkeeper order detail page shows requested, fulfilled and pending quantities. Its **Recheck and fulfill available quantity** action requires confirmation and rechecks inventory and credit in a transaction. If nothing is in stock or credit is insufficient, the transaction makes no changes. If some pending stock is available, only that amount is fulfilled; the order remains partial until its remainder is fulfilled. Repeated requests with the same idempotency key do not apply the operation twice. The customer workspace shows saved order status and refreshes it from the backend every 30 seconds. No phone, WhatsApp, email, or SMS status delivery is connected.

## Vyapro agent assistant

`POST /api/v1/assistant/messages` runs the bounded assistant workflow over explicitly registered backend tools. The current web interface uses deterministic intent routing (no LLM provider is needed). It can explain the current page, inspect the selected order or proposal for shopkeepers, match products, check inventory, customer prices and credit, read substitutions, prepare a proposal, apply a clarification, and submit through the existing transactional approval service. Tool calls are validated against the registry and role policy; model output cannot replace database results or bypass order validation. Tool inputs are logged with identifying text redacted, and outputs with personal/catalog details omitted.

The floating helper and dedicated shopkeeper assistant use this same endpoint and business services. A customer helper can read order history only for the registered account selected in that request; it cannot query another customer by name. Account selection is a local demo distinction, not authentication, so the API remains localhost-development-only until real authentication is added.

Order submission requires an explicit confirmation in the UI by default. Routine autonomous submission is disabled by default. To enable it deliberately, set `VYAPRO_AGENT_AUTONOMOUS_ROUTINE_ORDERS=true` and a positive `VYAPRO_AGENT_AUTONOMOUS_MAX_MINOR`; the server only permits a proposal with no validation warnings or substitutions, in the current version, within that amount. Final stock, price, and credit checks still run inside the order transaction. Agent iterations and total time are capped by `VYAPRO_AGENT_MAX_ITERATIONS` and `VYAPRO_AGENT_MAX_SECONDS`.

Migrations `010_create_product_aliases.sql` and `011_create_customer_product_prices.sql` add optional aliases and customer-specific price overrides. The standard catalog price remains the fallback. These tables start empty; no aliases or negotiated prices are inferred or seeded.

## Preview-first shop-data imports

Apply migrations before using imports. `POST /api/v1/imports/preview` accepts multipart form data with `file`, optional `datasetType` (`customers`, `products`, `inventory`, `prices`, or `previous_orders`), and optional `updateExisting=false|true`. It extracts and validates rows, checks units, duplicate identifiers and customer/product relationships, and compares rows with current MySQL values. The response contains a row-level preview and errors. No customer, product, inventory, price, or history rows are changed during preview. Invalid rows block the whole batch.

After reviewing the full preview, confirm with `POST /api/v1/imports/{importId}/confirm`, JSON `{ "confirm": true }`, and an `Idempotency-Key` header. The import commits as one transaction. Existing record changes are blocked by default; preview with `updateExisting=true` to see the old and proposed values, then explicitly confirm. The server rechecks that database rows have not changed since preview. Re-uploading the same file with the same update option reuses its import batch. Reconfirming with the same key returns the completed summary. A conflict or database failure rolls back the business-data writes.

CSV files use one dataset per file. XLSX files can use one dataset per sheet named `customers`, `products`, `inventory`, `prices`, or `previous_orders`. PDF support targets text-readable catalogue tables with a recognizable header and pipe, tab, or aligned columns. If a PDF has no extractable text, the optional local OCR path uses `pypdfium2` and `pytesseract`; install the Tesseract OCR executable separately and add it to PATH. Scanned PDF row extraction still needs human review in the preview. PDF imports support product catalogues, prices, and inventory only.

Fields such as IDs, names, SKUs, units, quantities, prices, currencies, and dates must be supplied where required. Units are checked against the supported retail unit set in `app/data_import.py`. Money columns are entered in major currency units and converted to minor units using the ISO currency decimal convention (common two-digit currencies, listed zero-digit currencies, and listed three-digit currencies). Unknown fields are not used to fill missing business values. Product pack size and pack unit may both be blank; if provided, both must be present. Customer prices can specify `customer_id`; blank customer ID means catalog price. Historical orders are stored in separate `imported_order_history` tables and never appear as Vyapro-processed orders or change stock/credit.

Synthetic templates are under `samples/demo_only/`. They are clearly labeled, use `DEMO-` IDs, and are never automatically loaded. Do not treat them as real shop records.

### Deterministic customer and shopkeeper demo flow

To try a real end-to-end order locally, start Flask and the frontend, configure the development MySQL database, then run `python seed_dev.py`. This loads only the documented fictional development records and skips existing identifiers. No LLM provider is needed for this flow.

Open **Customer Ordering**, select a registered development customer, then either add catalog products or enter exact catalog text such as `2 kg India Gate Basmati Rice`. The parser accepts one item per line. Review the proposal and explicitly confirm it. Try the provided **Credit review** and **Stock review** examples to exercise backend holds. The proposal reads actual MySQL customer, catalog, price, stock, and credit values; approval rechecks them transactionally, updates stock and credit, and records audit activity. The shopkeeper **Orders** and **Activity** pages show saved database records. Interpretation is deterministic and limited to the documented grammar; the separate agent assistant, typo correction, conversational clarifications, and audio transcription still need an LLM provider. Fictional seed customers and products are local development records, not real businesses. The demo customer selection is not authentication; APIs remain development-only until real authentication is implemented.

## Tests

From `backend` with the virtual environment active:

```powershell
python -m unittest discover -s tests -v
```

The unit tests use mocked database boundaries and do not require MySQL or an LLM provider. They do not prove that migrations work against a real MySQL server or that a configured LLM is reachable. Verify both through the local endpoints and a real test request after configuring those services.

### Agent scenario evaluation

Run the deterministic wholesale evaluation suite with:

```powershell
python -m unittest discover -s tests -p test_agent_evaluation.py -v
```

It covers 14 seeded scenarios: normal and repeat orders, an explicit alias, an LLM-corrected misspelling, ambiguous quantity, unavailable stock, an approved substitution, a credit breach, unknown customer, duplicate confirmation, LLM/database failures, repeated identical tool calls, and model false-success text. It exercises the actual `_evaluate` stock, alias, substitution, and credit rules against synthetic in-memory records. Tool selection and persistence boundaries are deterministic test doubles; this is an automated regression evaluation, not a live-provider or production-readiness certification.

### Real-MySQL shortage integration test

The opt-in integration suite runs migrations and creates temporary retailer/product/order rows in the dedicated `vyapro_shortage_test` schema. It refuses to run if customer, product, proposal, order, or audit tables contain rows. Test rows use unique IDs and are deleted with their dependent audit and fulfillment records in `tearDown`; cleanup is asserted. It verifies partial acceptance, rejection, a stock race, no-stock retry, partial then completed fulfillment, idempotency, credit failure rollback, inventory/credit totals, customer status responses, and audit events. It does not touch `vyapro_dev`.

The normal application account is scoped to the development database and cannot create this separate schema. As a MySQL administrator, create the isolated schema and grant the existing local app account access to only that schema:

```sql
CREATE DATABASE vyapro_shortage_test CHARACTER SET utf8mb4;
GRANT ALL PRIVILEGES ON vyapro_shortage_test.* TO 'vyapro_app'@'localhost';
```

Then run from `backend` in PowerShell. The test overrides only the database name; it reads host and credentials from the existing ignored `.env` without printing them:

```powershell
$env:VYAPRO_TEST_MYSQL_DATABASE = 'vyapro_shortage_test'
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_shortage_mysql_integration.py -v
Remove-Item Env:VYAPRO_TEST_MYSQL_DATABASE
```

Do not use a business or seed database for this suite. If a prior interrupted run left rows in the dedicated test schema, review and clean that schema manually before rerunning; the test deliberately refuses to erase unexpected data.
