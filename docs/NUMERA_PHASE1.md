# NUMERA ERP — Phase 1

Product name: NUMERA ERP. The existing repository name remains unchanged.

## Development isolation

Work on `numera/development`; do not merge into main or deploy to the existing application during development. A branch isolates source changes only: a staging service, separate database, credentials, and storage must be provisioned before hosted testing. Never reuse the live DATABASE_URL, JWT secret, production payment credentials, or live business data. Use synthetic sample data. Hosted staging is not yet provisioned.

## First customer scope

Small trading businesses, initially one company and one warehouse per customer. Arabic and English, mobile-friendly interfaces. Manufacturing and industry-specific POS are deferred.

## Milestones

- [x] Create isolated source branch.
- [x] Record NUMERA branding and Phase 1 scope.
- [ ] Audit existing backend, frontend, migrations, and tests; document reusable components and gaps.
- [ ] Prepare isolated local environment and baseline verification.
- [ ] Implement company registration, tenant isolation, roles, audit history, and migrations.
- [ ] Implement products, opening balances, suppliers, purchases, and stock receipts.
- [ ] Implement customers, sales, stock deductions, and controlled returns.
- [ ] Implement payment allocation, cash/bank, and expenses.
- [ ] Implement balanced accounting entries, consistent costing, stock valuation, and profit/loss.
- [ ] Build NUMERA marketing homepage, features, pricing, trial signup, login, and support pages.
- [ ] Connect trials and plan entitlements; decide prices and payment provider before live checkout.
- [ ] Provision isolated hosted staging with a separate database and secrets.
- [ ] Verify full business cycle, tenant isolation, permissions, concurrency, and backup restoration.
- [ ] Pilot with a small customer group; resolve defects before paid launch.

## Release gates

A customer must register and complete purchases, sales, returns, payments, expenses, and consistent reporting without developer intervention. Stock and accounting must reconcile. Posted records require controlled reversal/correction. Cross-company access must be denied. Backups must be restored successfully. Egyptian electronic invoicing must not be advertised as available until separately implemented and verified.

## Initial repository findings

The README documents existing inventory, purchase/sales invoices, VAT, COGS, accounting ledgers, roles, and manufacturing features. These are reuse candidates, not verified capabilities. The repository contains a Python backend, static frontend, Alembic migrations, and safety workflow tests. Existing CI runs on main pushes and applicable pull requests; development-branch checks need configuring. Existing Docker Compose uses a single local database and is not a customer-isolated SaaS environment.
