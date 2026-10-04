# NUMERA ERP

A clean modular ERP build. No application code is reused from the previous NEXUS implementation. Work remains on `numera/development`; the main branch and existing hosted application are unchanged.

## Milestones 1–4 — implemented

- Marketing homepage with roadmap and development-trial signup.
- Company registration and login with hashed passwords and two-hour bearer sessions.
- Company-scoped product catalogue, employee roles and audit history.
- Single-warehouse opening stock, receipts, issues, adjustments, balances and low-stock indicators.
- Exact quantities to three decimal places, immutable movement history and retry-safe posting.
- Arabic/English workspace with RTL support.
- Supplier master records and multi-product purchase drafts with document dates, due dates and supplier references.
- Full goods receipts atomically update stock, with retry/concurrency protection and role-specific receiving views.
- Customer records and multi-product sales drafts; posting deducts stock atomically and preserves document history.
- 30-day development-trial metadata. Paid billing and expiry enforcement are not enabled.

This is a local development milestone, not a production accounting service. Use synthetic data only.

## Run a separate local environment

Python 3.12 is the tested version. Install dependencies in a fresh virtual environment:

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
```

Set `NUMERA_JWT_SECRET` to a unique random secret of at least 32 characters in your shell. Set `NUMERA_DATABASE_PATH` to a new local file, such as `./numera-development.db`. Do not use a database from the previous ERP.

```bash
python -m uvicorn numera.main:create_app --factory --host 127.0.0.1 --port 8100
```

Open `http://127.0.0.1:8100`. Registration creates an empty company; no demo products or opening stock are automatically inserted. Tokens are held in browser memory; reloading requires login. Currency is a company setting, not a multicurrency accounting implementation.

```bash
python -m unittest discover -s tests -v
node --check numera/static/workspace.js
node --check numera/static/purchases.js
node --check numera/static/sales.js
```

## Next milestones

Customer/supplier payments, returns and expenses; stock valuation, balanced accounting and reports. The long-term product is an Odoo-like modular ERP, including POS, manufacturing, CRM and advanced accounting.

## Hosted release gates

Provision separate staging resources and secrets. Introduce schema migrations and a PostgreSQL persistence layer before shared hosted use; the initial SQLite schema is for local development. Add email verification, password recovery, session revocation, distributed rate limiting, employee lifecycle controls and subscription entitlements. Implement and test backups and restoration. Verify tenant isolation on every future endpoint. Test accounting, stock concurrency and tax integrations before a paid launch. Marketing pages currently do not include final legal terms, a payment checkout or a public support channel.

Browser visual verification and hosted deployment have not yet been performed. Automated API and static-route checks are provided. The suite contains 45 tests, including simultaneous stock issues and inventory persistence across restart.

## Inventory usage

Create products, then use the inventory panel to record opening stock before any other movement on each product. Receipts and positive adjustments add quantity; issues and negative adjustments subtract it. Each posting requires a reason and a client request key. Repeating an identical request returns the original movement; changing its contents with the same key is rejected. A product cannot go below zero. History shows the latest 200 movements; prior entries remain in the database. Corrections use a new adjustment.

Quantities use integer thousandths in storage, with a maximum balance of 99,999,999,999.999 units. SQLite write transactions serialize availability checks and posting. No costs, inventory valuation or accounting entries are generated yet; receipts/issues are manual development operations, not purchase or sales documents. The warehouse is implicitly the single main warehouse in this milestone.

## Purchase usage and limits

Owners/accountants create suppliers and purchase drafts. Add one line per product with quantity, tax-exclusive unit price and an explicitly chosen tax percentage; zero is the default, not a tax-law determination. Server totals use Decimal with half-up rounding per line and integer minor-unit storage. Documents use the company currency only.

Owners/inventory staff receive the full purchase; it creates one linked stock movement per line in a single transaction. Retrying or concurrently receiving the same purchase cannot add stock twice. Warehouse staff receive a quantity-only view without supplier prices. A draft can be cancelled by an owner/accountant; received documents cannot be cancelled. Partial receiving and purchase returns are not implemented.

These records are operational drafts and received purchases, not a completed statutory bill/accounting workflow. Supplier payments, outstanding balances, cost valuation and accounting posting remain pending. Due dates are stored and displayed; no reminder service is enabled. Purchase numbers are internal identifiers, not a statutory numbering scheme.

## Sales usage and limits

Owners/accountants create customers and sales drafts with one line per product. Catalogue prices prefill the form and can be changed. Enter the applicable tax percentage explicitly; prices exclude tax. Totals are calculated on the server with Decimal and per-line half-up rounding. Customer references are unique per customer/company when supplied.

Drafts do not reserve or deduct stock. Posting deducts all quantities in a single transaction; insufficient stock on any line leaves the entire invoice in draft. Concurrent sales cannot oversell, and repeated posting cannot deduct twice. Unposted drafts can be cancelled; posted documents require a future return/reversal workflow. Due dates are stored and displayed. Payments, financial balances, returns, cost valuation and accounting entries remain pending. These internal sales documents are not Egyptian electronic invoices or a verified statutory invoice implementation.
