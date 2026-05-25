# Phase 1 Databricks Foundation

This project now includes a Databricks bundle scaffold for the phase 1 migration.

## What The Scaffold Does
- Defines a Databricks Asset Bundle under `databricks/`.
- Keeps bundle sync limited to files inside the `dashboard` repository root so Databricks validation can succeed.
- Vendors the legacy CHEC notebooks into `databricks/references/` as reference material.
- Excludes `OPENAI_API_Key.txt` from sync so that it can be moved into a secret scope or Key Vault-backed secret store.
- Splits bootstrap from ingest so Unity Catalog volumes can be created before local data is uploaded.
- Reads raw files and ML artifacts from Unity Catalog volumes during ingest and validation.
- Uses serverless-first Lakeflow Jobs for phase 1 notebook execution.
- Keeps classic fallback jobs only for workloads that later prove incompatible with serverless.
- Adds a local preflight script that checks live Azure quota/SKU status and Databricks workspace readiness before deploys.

## Bundle Entry Points
- Bundle config: [databricks/databricks.yml](/home/jclugor/unal/CHEC/dashboard/databricks/databricks.yml)
- Bundle README: [databricks/README.md](/home/jclugor/unal/CHEC/dashboard/databricks/README.md)
- Asset manifest: [databricks/manifests/phase1_assets.json](/home/jclugor/unal/CHEC/dashboard/databricks/manifests/phase1_assets.json)

## Intended Workspace Layout
- `chec_dbx_demo.raw.source_files`
- `chec_dbx_demo.ml.artifacts`
- `chec_dbx_demo.bronze.*`
- `chec_dbx_demo.silver.*`
- `chec_dbx_demo.gold.*`
- `/Workspace/Users/<user>/.bundle/chec_phase1/dev/files`

## Manual Follow-Ups
- Create the Databricks workspace in the Azure subscription.
- Export `DATABRICKS_HOST` and authenticate with the Databricks CLI before running `databricks bundle validate` or `databricks bundle deploy`.
- Run `bash databricks/scripts/preflight_phase1_deploy.sh` before every deploy.
- Run `databricks bundle run -t dev chec_phase1_bootstrap` before uploading any raw files.
- Run `bash databricks/scripts/upload_phase1_assets.sh` after bootstrap and before the ingest-validation workflow.
- The default catalog is `chec_dbx_demo` because it is the current managed catalog in the live workspace. Override `catalog_name` only after the alternate catalog exists with a managed location.
- The default jobs path is serverless because East US supports Databricks serverless workflows and this workspace is Unity Catalog-enabled.
- If serverless is blocked by standard access mode, use `chec_phase1_bootstrap_classic` with `Standard_DC4as_v5` and `chec_phase1_ingest_validation_classic` with `Standard_L4aos_v4`.
- The classic fallback jobs retry up to 3 total attempts with a 10-minute backoff to absorb transient `SkuNotAvailable` and stockout failures.
- Create a secret scope or Key Vault-backed secret for the OpenAI API key instead of syncing it as a file.

## Current Compute Strategy
- Primary path: `chec_phase1_bootstrap` and `chec_phase1_ingest_validation` on Databricks serverless jobs compute.
- Bootstrap classic fallback: `chec_phase1_bootstrap_classic` on `Standard_DC4as_v5`.
- Ingest classic fallback: `chec_phase1_ingest_validation_classic` on `Standard_L4aos_v4`.
- Explicitly avoid returning to `Standard_D4as_v5`, `Standard_D4ads_v5`, `Standard_D4s_v5`, or `Standard_DS3_v2` unless a fresh preflight proves they are both subscription-available and Databricks-enabled.
