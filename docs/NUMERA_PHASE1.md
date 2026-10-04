# NUMERA ERP — clean-build roadmap

## Architecture and isolation

NUMERA is a new implementation under `numera/`, with no legacy application imports. Development source lives on `numera/development`; main and the existing hosted service remain untouched. All current business records carry a company identity. Company identity comes from the authenticated user, never from form input. Money values in the catalogue use Decimal validation and exact string storage.

The first local milestone uses a separate SQLite database. A PostgreSQL persistence layer, versioned schema migrations and independent hosting/database/secrets are required before a shared staging pilot. No live data is copied.

## Build checklist

- [x] Separate source branch.
- [x] Adopt NUMERA ERP branding.
- [x] Begin a clean application, excluding the legacy ERP.
- [x] Company registration and login.
- [x] Owner/accountant/inventory permissions for implemented endpoints.
- [x] Company-isolated catalogue, employee records and audit history.
- [x] Landing page, registration and Arabic/English workspace.
- [x] Development-trial metadata, with billing visibly disabled.
- [ ] Schema migrations and PostgreSQL persistence.
- [ ] Stock movements, opening balances and valuation.
- [ ] Suppliers, purchases and receipts.
- [ ] Customers, sales and stock deductions.
- [ ] Controlled sales/purchase returns and corrections.
- [ ] Payment allocation, cash/bank and expenses.
- [ ] Balanced accounting and profit/loss reports.
- [ ] Final pricing, legal pages, support and subscription entitlements.
- [ ] Test-mode payment provider integration before live checkout.
- [ ] Separate hosted staging, backups and recovery validation.
- [ ] Complete business-cycle testing and small-customer pilot.

## Future modular ERP

Use an Odoo-like connected experience with a consistent workspace: Accounting, Sales, Purchases, Inventory, POS, Manufacturing and CRM. Phase 1 supplies the essentials; later modules extend the same company records. Do not advertise future modules or Egyptian e-invoicing as implemented until verified.

## Milestone 1 limits

The catalogue does not implement stock quantities or movements. Employee roles are initial role guards, not a completed ERP permission system. Trial expiration is reported but does not enforce paid entitlements. The development auth limiter operates in one process. Sessions live in browser memory and expire after two hours. No hosted application has been deployed. Full browser interaction testing remains pending.
