# Vyapro

Vyapro is a retail order-management application for Indian wholesalers and retailer customers. It brings customer ordering and shopkeeper operations into one React application, backed by shared Flask services and MySQL records.

## What Vyapro does

- **Customer workspace:** browse the live catalog, prepare an order request with catalog products or one `quantity unit product` line at a time, review stock, price and credit checks, confirm an order, and view its saved status and history.
- **Shopkeeper workspace:** view saved orders, customers, inventory, review requests that need attention, inspect order activity, and use the order assistant to look up business data.
- **Order workflow:** the backend matches registered customers and products, checks current inventory, configured prices and credit, offers only configured substitutions, and records proposals, confirmations, orders and audit events. Stock and credit are rechecked when an order is confirmed.
- **Shortages:** where stock is insufficient, the proposal can show an accepted quantity and a pending remainder. The customer must accept the split; stock is not reserved when a proposal is created. Later fulfillment rechecks stock and credit.
- **Imports:** preview CSV, Excel and supported text-readable PDF business files, see row errors, then explicitly confirm the database import. Sample import files are marked as fictional demo-only data.
- **Language and voice:** the interface offers English, Hindi and Kannada. Browser speech input/output depends on the browser and available device voices. Uploaded audio transcription requires a configured provider.

Order interpretation in the customer order form is deterministic and uses the catalog in MySQL; it is not an LLM. The separate conversational order assistant can use an optional OpenAI-compatible provider configured on the backend. Neither an LLM nor the browser can bypass server-side order validation. Routine autonomous order submission is disabled by default.

Phone calls and WhatsApp or other messaging integrations are not implemented. The application is a local development demo: API authorization is restricted to development mode and there is no production authentication. Seeded business records are fictional and must not be represented as real customers.

## Architecture

```text
React + Vite + TypeScript
        | same-origin /api requests
        v
Flask API -- order, catalog, import and agent services
        |
        v
      MySQL
```

Both customer and shopkeeper workflows use the same backend order and inventory rules. API routes and request/response examples are documented in [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md).

## Repository layout

- `frontend/` — React, TypeScript, Vite app and its English/Hindi/Kannada interface strings.
- `backend/app/` — Flask API, database access, catalog, order, import and assistant services.
- `backend/migrations/` — additive MySQL schema migrations.
- `backend/tests/` — backend unit and evaluation tests; an opt-in isolated MySQL integration test is also included.
- `backend/samples/demo_only/` — clearly labeled fictional import examples.
- `docs/API_CONTRACT.md` — API behavior and data contract.

## Run locally on Windows

### 1. Configure MySQL and Flask

Install and start MySQL Community Server separately. Create a local development database named `vyapro_dev`, then in PowerShell:

```powershell
cd backend
py -m venv .venv
Copy-Item .env.example .env
```

Edit `backend/.env` with your local MySQL host, port, database, username and password. Keep this file private; it is ignored by Git. The example contains placeholders only. For a clean development database, use `MYSQL_DATABASE=vyapro_dev` and `VYAPRO_ENV=development`.

You can run commands using `.venv\Scripts\python.exe` without activating the virtual environment (useful when PowerShell script activation is disabled):

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe migrate.py
.\.venv\Scripts\python.exe seed_dev.py
.\.venv\Scripts\python.exe run.py
```

`seed_dev.py` is optional and inserts only missing fictional development records. Its expected dataset is 8 customers, 20 products and 16 historical orders. It refuses databases that are not clearly development databases. Do not run it against production data.

Flask listens on `http://127.0.0.1:5000` by default. Check `http://127.0.0.1:5000/api/v1/health` and `http://127.0.0.1:5000/api/v1/health/database` to verify the API and MySQL connection.

### 2. Run the frontend

Open a second PowerShell terminal from the repository root:

```powershell
cd frontend
pnpm install
pnpm dev --host 127.0.0.1
```

Open the Vite URL printed in the terminal, normally `http://127.0.0.1:5173`. Vite proxies `/api` requests to the local Flask server. Node.js and pnpm must already be installed and available in that terminal.

### Optional: enable the conversational LLM and audio transcription

The deterministic catalog order form does not need an LLM. To enable LLM-powered assistant interpretation or uploaded-audio transcription, set the provider's compatible base URL, model, key and transcription model in the ignored `backend/.env` file:

```text
VYAPRO_LLM_BASE_URL=
VYAPRO_LLM_MODEL=
VYAPRO_LLM_API_KEY=
VYAPRO_TRANSCRIPTION_MODEL=
```

The provider must support OpenAI-compatible chat completions with JSON object responses and the audio transcription endpoint. Provider usage may incur charges. Do not put credentials in frontend files or commit `.env`. Without these settings, those provider-dependent features report that configuration is missing; Vyapro does not fabricate an AI answer or transcription.

## Tests and checks

Backend tests (from `backend/`):

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Frontend build and lint (from `frontend/`):

```powershell
pnpm build
pnpm lint
```

The optional MySQL shortage integration test requires a separate, empty `vyapro_shortage_test` database. Instructions and safeguards are in [`backend/README.md`](backend/README.md). The regular unit tests do not by themselves verify provider credentials or a real MySQL integration environment.

## Security and deployment status

This repository is intended for local development and demonstration. Non-health API routes are limited to development mode and the customer selector is not authentication. Do not expose the demo publicly or use it to process real customer orders until authentication, authorization, deployment security and production operations have been implemented and reviewed.
