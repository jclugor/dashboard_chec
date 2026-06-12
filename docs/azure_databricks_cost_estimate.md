# Azure Databricks Cost Estimate

Last updated: 2026-06-11

This estimate covers only the Databricks deployment path in this repository. It
excludes Azure Container Apps, Azure Container Registry, Azure Files, and the
legacy containerized demo path.

## Concise Summary

For the current pilot setup, the only clean monthly DBU forecast that can be
computed without billing data is the Databricks App: `88 DBU/month`, or about
`$83.60/month`, assuming the Medium app runs 8 hours/day for 22 business days.
The Phase 2 refresh job is paused, so scheduled refresh adds `0 DBU/month`.

SQL warehouse, AI Search, and Model Serving costs should be reconciled from
`system.billing.usage` because their actual DBU, DSU, or token quantities depend
on real usage. The included reconciliation SQL is the source of truth for actual
monthly spend once Databricks/Azure auth is refreshed.

## Architecture Basis

The canonical client deployment is the Databricks fresh-install path documented
in `docs/AZURE_DATABRICKS_FRESH_INSTALL.md`. The active bundle uses
`databricks/manifests/normalized_vano_assets.json`, so the Databricks data
foundation is sized around the normalized Parquet dataset, not the full legacy
pickle folder.

Observed local and workspace facts:

| Item | Value |
|---|---:|
| Workspace region | East US |
| Workspace ID | `7405611288758888` |
| Catalog | `chec_dbx_demo` |
| Active source manifest | `normalized_vano_assets.json` |
| Normalized source rows | `159,470` |
| Normalized source size in `./data` | about `64 MB` |
| Chatbot corpus size in `./data` | about `1.9 MB` |
| Full local `./data` folder | about `6 GB`, not active unless the legacy manifest is selected |
| SQL warehouse | `CHEC Dashboard Warehouse`, Small, PRO, serverless, Photon, auto-stop 10 minutes |
| SQL warehouse state at inspection | `STOPPED` |
| Databricks App | `chec-dash-parity`, Medium |
| Databricks App state at inspection | `STOPPED` |
| Phase 2 refresh job | Scheduled daily at 06:00 America/Bogota but `PAUSED` |
| Chatbot resources | AI Search index plus `databricks-qwen3-next-80b-a3b-instruct` Model Serving endpoint |

## Pricing Inputs

Current East US retail prices were checked from the Azure Retail Prices API for
`serviceName = Azure Databricks` and `armRegionName = eastus`.

| Meter | Unit | Retail price |
|---|---:|---:|
| Premium Serverless SQL DBU | 1 DBU-hour | `$0.70` |
| Premium Automated Serverless Compute DBU | 1 DBU-hour | `$0.45` |
| Premium Interactive Serverless Compute DBU | 1 DBU-hour | `$0.95` |
| Premium Serverless Realtime Inferencing DBU | 1 DBU-hour | `$0.07` |
| Launch Charge Serverless Realtime Inferencing DBU | 1 launch unit | `$0.07` |
| Premium Databricks Storage Unit DSU | 1 DSU | `$0.026` |

Databricks Apps are priced by provisioned app capacity while running. The
current app is Medium, and Databricks documents Medium app compute as `0.5 DBU`
per hour.

## Pilot Forecast

Assumptions for this forecast:

| Assumption | Value |
|---|---:|
| Pilot month | 22 business days |
| App availability | 8 hours/day |
| App runtime | 176 hours/month |
| SQL warehouse active time | 1.5 hours/day, 33 hours/month |
| Refresh job | paused, so 0 scheduled monthly runs |
| Optional refresh case | weekly run, 4 runs/month |
| Chatbot load | light, 25 questions/day, 550 questions/month |
| Token planning assumption | 3,500 tokens/question across prompt, retrieval context, and answer |
| LLM judges | disabled |
| Provisioned throughput | not assumed unless billing data shows it |

Forecast table:

| Component | Usage unit | Assumed quantity | DBU/DSU/token quantity | Unit price | Monthly USD | One-time USD | Confidence |
|---|---:|---:|---:|---:|---:|---:|---|
| Databricks App `chec-dash-parity` | Medium app-hour | 176 h/mo | 88 DBU/mo | `$0.95/DBU-hour` | `$83.60` | n/a | High for DBU quantity; Medium for SKU mapping until billing confirms `APPS` SKU |
| SQL warehouse dashboard/app queries | warehouse runtime | 33 h/mo | Actual DBUs from billing; planning formula: `33 * sql_dbu_per_hour` | `$0.70/DBU-hour` | Actual from billing; planning formula: `$23.10 * sql_dbu_per_hour` | n/a | Medium-low until `system.billing.usage` confirms DBUs |
| Scheduled refresh job, current state | job run | 0 runs/mo | 0 DBU/mo | `$0.45/DBU-hour` | `$0.00` | n/a | High because job is paused |
| Scheduled refresh job, optional weekly case | job run | 4 runs/mo | `4 * actual_dbu_per_run` | `$0.45/DBU-hour` | `4 * actual_dbu_per_run * $0.45` | n/a | Medium-low until billing confirms serverless job DBUs |
| One-time bootstrap + ingest/build | job run | observed successful elapsed runs around 7-8 min total for normalized path | Actual DBUs from billing | `$0.45/DBU-hour` | n/a | Actual DBU * `$0.45` | Medium-low until billing confirms serverless job DBUs |
| AI Search endpoint/index | DSU | actual DSU from billing | Actual DSU, not DBU | `$0.026/DSU` | `actual_dsu * $0.026` | setup sync DSU from billing | Medium-low until billing confirms DSUs |
| Model Serving, pay-per-token mode | token | about 1.93M tokens/mo | TOKEN usage, not DBU | billing token SKU required | Actual from billing | n/a | Low until billing confirms model SKU |
| Model Serving, provisioned/realtime mode if used | DBU-hour | not assumed | Actual DBUs from billing | `$0.07/DBU-hour` plus `$0.07` launch units if applicable | Actual from billing | Actual from billing | Low unless endpoint is provisioned |

Known monthly subtotal:

| Scope | Monthly DBU | Monthly USD |
|---|---:|---:|
| App only, because Medium app DBU/hour is explicit | 88 DBU | `$83.60` |
| App + SQL planning formula | `88 + 33 * sql_dbu_per_hour` | `$83.60 + $23.10 * sql_dbu_per_hour` |
| Current paused refresh add-on | 0 DBU | `$0.00` |

The app-only line is the clean DBU forecast. The app + SQL line is useful for
budget planning, but it must be replaced by billing-table DBUs before being
treated as actual spend.

## Actual Reconciliation

Do not start stopped compute to estimate costs. Use billing records instead.

Preferred SQL source:

```sql
SELECT
  workspace_id,
  billing_origin_product,
  sku_name,
  usage_unit,
  usage_type,
  usage_metadata,
  SUM(usage_quantity) AS quantity
FROM system.billing.usage
WHERE cloud = 'AZURE'
  AND workspace_id = '7405611288758888'
GROUP BY ALL
HAVING quantity != 0;
```

A reusable priced version lives in
`databricks/cost_reconciliation.sql`.

Alternative account-level CSV command:

```bash
databricks account billable-usage download 2026-06 2026-06 --personal-data
```

At the time of this update, `databricks auth profiles -o json` reported the
`DEFAULT` and `chec` Azure CLI profiles as invalid, so the account usage CSV
could not be downloaded from this shell. Workspace metadata calls still returned
the app, warehouse, and job states above.

## Interpretation

For a pilot where the app is manually started only during stakeholder hours, the
lowest defensible Databricks DBU forecast is the app line: `88 DBU/month`, or
about `$83.60/month` before SQL, AI Search, and model-serving usage.

The SQL warehouse is likely the next meaningful cost driver if reviewers use the
dashboard daily. Because serverless SQL bills actual DBUs rather than just wall
clock time, the accurate monthly SQL number must be pulled from
`system.billing.usage`. The report includes a 33-hour planning case so the budget
conversation has a concrete upper planning handle, but the billing table should
replace it for any client-facing actual.

AI Search and Model Serving should not be folded into the DBU subtotal unless
the billing table shows DBU units for those products. AI Search commonly appears
through `VECTOR_SEARCH` with DSU units; pay-per-token Foundation Model APIs
appear as token usage. Keep those separate in finance reporting.

## Sources

- Local deployment runbook:
  `dashboard/docs/AZURE_DATABRICKS_FRESH_INSTALL.md`
- Local bundle defaults:
  `dashboard/databricks/databricks.yml`
- Local fresh-install defaults:
  `dashboard/databricks/fresh_install.env.example`
- Local app deploy script:
  `dashboard/databricks/scripts/deploy_phase35_databricks_app.sh`
- Active data manifest:
  `dashboard/databricks/manifests/normalized_vano_assets.json`
- Azure Retail Prices API:
  `https://prices.azure.com/api/retail/prices?$filter=serviceName%20eq%20%27Azure%20Databricks%27%20and%20armRegionName%20eq%20%27eastus%27`
- Databricks Apps compute size:
  `https://learn.microsoft.com/azure/databricks/dev-tools/databricks-apps/compute-size`
- Databricks billable usage table:
  `https://learn.microsoft.com/azure/databricks/admin/system-tables/billing`
- Databricks Foundation Model APIs:
  `https://learn.microsoft.com/azure/databricks/machine-learning/foundation-model-apis/`
