# Nexus ERP — v0.2 Manufacturing & Accounting Foundation

This release moves the project from a dashboard MVP into a connected ERP foundation.

## Added in v0.2
- Arabic/English direction toggle
- VAT 14% on purchase and sales invoices
- Purchase and sales invoice register
- Sales COGS posting based on product standard cost
- Multi-warehouse master data
- Customers / suppliers master data
- BOM (Bill of Materials)
- Production orders with material availability checks
- Automatic raw-material consumption and finished-goods receipt
- Production batch/unit costing
- Receipt/payment journal endpoints
- Expanded chart of accounts including Input VAT / Output VAT
- Stock ledger + accounting ledger remain transaction-linked

## First-run configuration
Copy `.env.example` to `.env` and set strong, unique values for all variables. The first start creates the administrator from `NEXUS_INITIAL_ADMIN_USERNAME` and `NEXUS_INITIAL_ADMIN_PASSWORD`. These values are intentionally not stored in the repository.

## Run
```bash
copy .env.example .env
# Edit .env and set the three required values.
python -m venv .venv
# Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```
Open `http://127.0.0.1:8000`.

Alternatively, after creating `.env`, run `docker compose up --build`.

## Important production note
This is still a development foundation. Before using it for statutory accounting or live company transactions, we need to complete approvals, fiscal periods, document numbering rules, returns, payments allocation, landed cost, purchase/sales workflow, audit logs, backups, PostgreSQL migration, user permissions, and Egyptian e-invoicing/tax integration.


## Build-stage permission matrix

| Activity | Admin | Accountant | Inventory |
|---|---:|---:|---:|
| Manage users and roles | Yes | No | No |
| Create products, warehouses, BOMs, production, transfers, and stock adjustments | Yes | No | Yes |
| Create/approve financial and commercial documents | Yes, with independent-approval rules | Yes, with independent-approval rules | No |
| View financial reports and reconciliation | Yes | Yes | No |
| Review transfer and adjustment history | Yes | No | Yes |
| View audit logs and system checks | Yes | No | No |

Stock cannot go below zero. Transfers and adjustments require a reason and are retained in audit history. A document creator cannot approve their own quotation, purchase order, or invoice, and cannot post their own invoice.

## Release-control safeguards

- Invoices are always created as drafts. Immediate posting is rejected by the API and is not offered by the frontend.
- Every new or converted invoice stores its creator and source document. Approval and posting fail closed when creator identity is unavailable, and the creator cannot approve or post the same invoice.
- A purchase-order goods receipt is the stock-recognition event. The related converted supplier invoice requires that receipt and posts only the accounting entry, so stock is not counted twice.
- Voiding a receipt or payment retains the original payment and allocation rows, marks allocations inactive, and links the reversing journal, actor, and timestamp.
- Monetary database fields use fixed-precision `NUMERIC` values and application calculations use `Decimal` with half-up rounding to two decimal places.
- Inventory users receive operational dashboard and product data without financial totals, prices, invoices, journals, accounts, trial balance, financial reports, or reconciliation data.

Run the current safety and migration suite with:

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```
