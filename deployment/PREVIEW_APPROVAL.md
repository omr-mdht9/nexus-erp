# NUMERA online preview proposal — awaiting approval

Proposed workspace: NEXUS (`tea-dalcduijnfac73938k3g`), the only workspace returned by Render. The connector requires user confirmation of the workspace before listing or changing its resources. Existing services have not yet been inspected, and no resource has been created or billed.

## Resources requested

- A new Python web service named `numera-erp-preview`, in Frankfurt, on `0.5c-512mb` compute.
- A new 1 GB persistent disk mounted at `/var/data`, containing a fresh SQLite database.
- Source branch `numera/development` in `omr-mdht9/nexus-erp`.
- A separately generated session secret. No old application secrets or data are copied.
- Manual deployments, one worker and one instance.
- A Render-generated HTTPS URL, reachable on the internet; application accounts are used to access company records.

## Estimated recurring cost

Compute: USD 7/month. Persistent disk: USD 0.25/month for 1 GB. Base incremental estimate: USD 7.25/month, excluding applicable taxes, bandwidth/build overages and existing workspace charges. Verify the actual checkout estimate before applying. This is an estimate, not a billing cap.

Pricing verified 2026-10-05 at https://render.com/pricing. Disk behavior verified at https://render.com/docs/disks.

## Scope

An internal development review using synthetic data only. The current SQLite implementation can be reviewed on one disk-backed instance. PostgreSQL, schema migrations, database backup/restoration validation, production authentication controls and the unfinished accounting modules remain necessary before a paying-customer pilot. No custom domain, payment gateway or live business data is included in this approval.

## After approval

1. Confirm the NEXUS workspace with the Render connector and inspect existing service names to avoid conflicts.
2. Verify the proposed Blueprint against Render before applying it; rename the new service if its name is already used.
3. Create only the approved new service and disk; leave existing resources intact.
4. Deploy the development branch and verify startup, health, sample registration, purchases, sales and settlement workflows.
5. Return the actual preview URL and observed deployment status.

The YAML is syntactically checked locally. Render-side validation and resource-name checks remain pending workspace confirmation. No Render CLI is installed in this execution environment. Select the development branch and `deployment/render.preview.yaml` in the Blueprint creation flow; do not use the default main branch.
