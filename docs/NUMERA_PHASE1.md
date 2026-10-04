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
- [x] Opening quantities, receipts, issues, adjustments, low-stock indicators and movement history.
- [ ] Stock costs and valuation.
- [x] Suppliers, multi-product purchase drafts, dates/references and full goods receipts.
- [ ] Purchase returns and partial receipts.
- [x] Customers, multi-product sales drafts, dates/references and atomic stock deductions.
- [ ] Controlled sales/purchase returns and corrections.
- [ ] Payment allocation, cash/bank and expenses.
- [ ] Balanced accounting and profit/loss reports.
- [ ] Final pricing, legal pages, support and subscription entitlements.
- [ ] Test-mode payment provider integration before live checkout.
- [ ] Separate hosted staging, backups and recovery validation.
- [ ] Complete business-cycle testing and small-customer pilot.

## Future modular ERP

Use an Odoo-like connected experience with a consistent workspace: Accounting, Sales, Purchases, Inventory, POS, Manufacturing and CRM. Phase 1 supplies the essentials; later modules extend the same company records. Do not advertise future modules or Egyptian e-invoicing as implemented until verified.

## Current milestone limits

Stock movements do not yet generate accounting entries or valuation. The first-release warehouse is implicit and single. Employee roles are initial role guards, not a completed ERP permission system. Trial expiration is reported but does not enforce paid entitlements. The development auth limiter operates in one process. Sessions live in browser memory and expire after two hours. No hosted application has been deployed. Full browser interaction testing remains pending.

## Inventory validation

Opening balances are allowed only before the first movement. Movements require reasons, are append-only through the API, and are scoped to the authenticated company. Composite product foreign keys reject cross-company references at the database layer. Exact quantities use integer thousandths. Posting locks the write transaction before checking stock; duplicate request keys are replayed without posting twice. Tests cover concurrent issues, precision, permissions, negative-stock prevention, retries, tenant isolation and persistence on restart.

## Purchase validation

Full goods receipt and linked stock movements share one write transaction; every line rolls back if a line fails. Repeated receipt does not post twice. Purchase creation is retry-safe and supplier references are unique per company/supplier when supplied. Draft cancellation preserves history. Owner/accountant roles create documents; owner/inventory roles receive them. Inventory staff cannot read prices. Tests cover exact totals, duplicate references, retries, simultaneous receipts, permission boundaries, tenant isolation and rollback.

## Sales validation

Sales drafts leave stock unchanged. Posting links each invoice line to an inventory issue in the same write transaction. Stock shortage rolls back all issues; status remains draft. Repeated or simultaneous posting is safe. Posted documents cannot be cancelled. Tests cover exact totals, retries, cross-company access, role guards, competing sales, same-invoice concurrent posting and the purchase-to-sale stock cycle.
