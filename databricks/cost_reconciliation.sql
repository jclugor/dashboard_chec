-- Databricks-only cost reconciliation for the CHEC Dashboard deployment.
--
-- Run in a Databricks SQL editor or through a SQL warehouse that can read
-- system.billing.usage. This query does not start application compute or jobs.
--
-- Replace the date window if estimating a different month. The first SELECT
-- returns detailed usage rows; the second returns DBU/DSU/token subtotals.

CREATE OR REPLACE TEMP VIEW chec_cost_reconciliation_2026_06 AS
WITH usage_by_sku AS (
  SELECT
    workspace_id,
    CASE
      WHEN billing_origin_product = 'APPS'
        OR UPPER(sku_name) LIKE '%APP%'
        THEN 'Databricks App'
      WHEN UPPER(sku_name) LIKE '%SERVERLESS%SQL%'
        OR UPPER(billing_origin_product) LIKE '%SQL%'
        THEN 'SQL warehouse'
      WHEN UPPER(sku_name) LIKE '%AUTOMATED%SERVERLESS%'
        OR UPPER(billing_origin_product) LIKE '%JOBS%'
        THEN 'Jobs'
      WHEN UPPER(billing_origin_product) LIKE '%VECTOR%'
        OR UPPER(sku_name) LIKE '%DATABRICKS%STORAGE%UNIT%'
        THEN 'AI Search / Vector Search'
      WHEN UPPER(sku_name) LIKE '%INFERENC%'
        OR UPPER(billing_origin_product) LIKE '%MODEL%'
        THEN 'Model Serving'
      ELSE COALESCE(billing_origin_product, 'Other')
    END AS component,
    billing_origin_product,
    sku_name,
    usage_unit,
    usage_type,
    to_json(usage_metadata) AS usage_metadata_json,
    SUM(usage_quantity) AS usage_quantity
  FROM system.billing.usage
  WHERE cloud = 'AZURE'
    AND workspace_id = '7405611288758888'
    AND usage_start_time >= TIMESTAMP '2026-06-01 00:00:00'
    AND usage_start_time < TIMESTAMP '2026-07-01 00:00:00'
  GROUP BY ALL
  HAVING SUM(usage_quantity) != 0
),
priced_usage AS (
  SELECT
    *,
    CASE
      WHEN usage_unit = 'DBU' AND UPPER(sku_name) LIKE '%SERVERLESS%SQL%' THEN 0.70
      WHEN usage_unit = 'DBU' AND UPPER(sku_name) LIKE '%AUTOMATED%SERVERLESS%' THEN 0.45
      WHEN usage_unit = 'DBU' AND UPPER(sku_name) LIKE '%INTERACTIVE%SERVERLESS%' THEN 0.95
      WHEN usage_unit = 'DBU' AND UPPER(sku_name) LIKE '%REALTIME%INFERENC%' THEN 0.07
      WHEN UPPER(sku_name) LIKE '%LAUNCH%REALTIME%INFERENC%' THEN 0.07
      WHEN usage_unit = 'DSU' AND UPPER(sku_name) LIKE '%DATABRICKS%STORAGE%UNIT%' THEN 0.026
      ELSE NULL
    END AS usd_per_unit
  FROM usage_by_sku
)
SELECT
  workspace_id,
  component,
  billing_origin_product,
  sku_name,
  usage_unit,
  usage_type,
  usage_metadata_json,
  usage_quantity,
  usd_per_unit,
  CASE
    WHEN usd_per_unit IS NULL THEN NULL
    ELSE ROUND(usage_quantity * usd_per_unit, 4)
  END AS estimated_usd,
  CASE
    WHEN usage_unit NOT IN ('DBU', 'DSU') AND usd_per_unit IS NULL THEN 'NON_DBU_UNIT_REVIEW_MODEL_OR_TOKEN_PRICING'
    WHEN usage_unit NOT IN ('DBU', 'DSU') THEN 'NON_DBU_OR_DSU_UNIT_PRICED_FROM_RETAIL_REVIEW_BILLING_EXPORT'
    WHEN usd_per_unit IS NULL THEN 'PRICE_NOT_MAPPED_REVIEW_AZURE_RETAIL_PRICES'
    ELSE 'PRICED_FROM_2026_06_11_EASTUS_RETAIL_RATES'
  END AS pricing_note
FROM priced_usage;

SELECT
  workspace_id,
  component,
  billing_origin_product,
  sku_name,
  usage_unit,
  usage_type,
  usage_metadata_json,
  usage_quantity,
  usd_per_unit,
  estimated_usd,
  pricing_note
FROM chec_cost_reconciliation_2026_06
ORDER BY
  component,
  billing_origin_product,
  sku_name,
  usage_unit,
  usage_type;

SELECT
  usage_unit,
  pricing_note,
  SUM(usage_quantity) AS usage_quantity,
  ROUND(SUM(COALESCE(estimated_usd, 0)), 4) AS estimated_usd
FROM chec_cost_reconciliation_2026_06
GROUP BY usage_unit, pricing_note
ORDER BY usage_unit, pricing_note;
