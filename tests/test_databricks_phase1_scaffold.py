from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
DATABRICKS_DIR = ROOT / "databricks"
NOTEBOOK_DIR = DATABRICKS_DIR / "notebooks"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_phase1_manifest_contract() -> None:
    manifest = json.loads(_read(DATABRICKS_DIR / "manifests" / "normalized_vano_assets.json"))

    assert manifest["bundle_name"] == "chec_phase1"
    assert manifest["catalog_name"] == "chec_dbx_demo"
    assert manifest["source_sha256"] == "7d4efade8c78a6d364ed68e0228439693a533626bde8a247c5e6e0b4ab89d354"
    assert "full_reconstruction ok" in manifest["reconstruction_guarantee"]
    assert manifest["workspace_root_path"] == (
        "/Workspace/Users/${workspace.current_user.userName}/.bundle/chec_phase1/dev/files"
    )

    raw_sources = manifest["raw_sources"]
    assert len(raw_sources) == 8
    assert sum(1 for entry in raw_sources if entry["load_mode"] == "parquet") == 8
    assert sum(int(entry["expected_rows"]) for entry in raw_sources) == 373474

    bronze_tables = {
        entry["bronze_table"]
        for entry in raw_sources
        if entry.get("bronze_table")
    }
    assert bronze_tables == {
        "bronze_causas",
        "bronze_equipos_proteccion",
        "bronze_apoyos",
        "bronze_vanos",
        "bronze_transformador_profiles",
        "bronze_eventos",
        "bronze_evento_vano_trafo",
        "bronze_clima_vano_fecha",
    }
    assert {entry["logical_name"]: entry["expected_rows"] for entry in raw_sources}["evento_vano_trafo"] == 159470
    assert manifest["central_fact"]["logical_name"] == "evento_vano_trafo"
    assert manifest["central_fact"]["row_count"] == 159470
    raw_by_name = {entry["logical_name"]: entry for entry in raw_sources}
    assert "municipio" in raw_by_name["vanos"]["required_columns"]
    assert "municipio_source" in raw_by_name["vanos"]["required_columns"]
    assert "municipio_confidence" in raw_by_name["vanos"]["required_columns"]
    assert "municipio" in raw_by_name["transformador_profiles"]["required_columns"]

    gold_tables = {entry["table_name"] for entry in manifest["gold_tables"]}
    assert gold_tables == {
        "gold_impact_daily",
        "gold_impact_circuit_summary",
        "gold_timeseries_event_details",
        "gold_timeseries_daily_attribution",
        "gold_timeseries_environment_daily",
        "gold_probability_inputs",
        "gold_map_points",
        "gold_map_line_segments",
        "gold_map_filter_index",
        "gold_map_event_days",
    }


def test_phase1_bundle_and_job_paths() -> None:
    bundle_text = _read(DATABRICKS_DIR / "databricks.yml")
    jobs_text = _read(DATABRICKS_DIR / "resources" / "phase1_jobs.yml")
    phase2_text = _read(DATABRICKS_DIR / "resources" / "phase2_pilot_resources.yml")

    assert "name: chec_phase1" in bundle_text
    assert "references/**" in bundle_text
    assert "../../data" not in bundle_text
    assert "../../Dashboard_CHEC" not in bundle_text
    assert "/Workspace/Shared" not in bundle_text
    assert "workspace_root_path:" not in bundle_text
    assert "mode: development" in bundle_text
    assert "default: chec_dbx_demo" in bundle_text
    assert "bootstrap_classic_node_type_id:" in bundle_text
    assert "default: Standard_DC4as_v5" in bundle_text
    assert "ingest_classic_node_type_id:" in bundle_text
    assert "default: Standard_L4aos_v4" in bundle_text
    assert "manifest_filename:" in bundle_text
    assert "default: normalized_vano_assets.json" in bundle_text
    assert "manifest_filename: ${var.manifest_filename}" in jobs_text
    assert "dashboard_warehouse_id:" in bundle_text
    assert 'default: ""' in bundle_text
    assert "4437a6195e05c59c" not in bundle_text
    assert "dashboard_parent_path:" in bundle_text
    assert "/Shared/CHEC Phase2 Pilot" in bundle_text
    assert "phase2_refresh_quartz_cron:" in bundle_text
    assert "phase2_refresh_pause_status:" in bundle_text
    assert "dashboards/*.lvdash.json" in bundle_text

    expected_notebooks = [
        "../notebooks/00_bootstrap_uc.py",
        "../notebooks/01_stage_bronze_tables.py",
        "../notebooks/02_validate_ingest.py",
        "../notebooks/03_build_silver_gold.py",
    ]
    for notebook_path in expected_notebooks:
        assert notebook_path in jobs_text

    assert "chec_phase1_bootstrap:" in jobs_text
    assert "chec_phase1_ingest_validation:" in jobs_text
    assert "chec_phase1_bootstrap_classic:" in jobs_text
    assert "chec_phase1_ingest_validation_classic:" in jobs_text
    assert "${workspace.file_path}" in jobs_text
    assert "${var.bootstrap_classic_node_type_id}" in jobs_text
    assert "${var.ingest_classic_node_type_id}" in jobs_text
    assert "num_workers: 0" in jobs_text
    assert "spark.databricks.cluster.profile: singleNode" in jobs_text
    assert "ResourceClass: SingleNode" in jobs_text
    assert "max_retries: 2" in jobs_text
    assert "min_retry_interval_millis: 600000" in jobs_text
    assert "retry_on_timeout: true" in jobs_text
    assert "chec_phase2_summary_pilot:" in phase2_text
    assert "chec_phase2_pilot_refresh:" in phase2_text
    assert "../dashboards/chec_summary_pilot.lvdash.json" in phase2_text
    assert "${var.dashboard_warehouse_id}" in phase2_text
    assert "quartz_cron_expression: ${var.phase2_refresh_quartz_cron}" in phase2_text
    assert "pause_status: ${var.phase2_refresh_pause_status}" in phase2_text

    for task_key in [
        "bootstrap_uc",
        "stage_bronze_tables",
        "validate_ingest",
        "build_silver_gold",
    ]:
        assert f"task_key: {task_key}" in jobs_text


def test_fresh_install_template_and_orchestrator_contract() -> None:
    template_text = _read(DATABRICKS_DIR / "fresh_install.env.example")
    orchestrator = DATABRICKS_DIR / "scripts" / "fresh_install_databricks.sh"
    orchestrator_text = _read(orchestrator)

    for expected_text in [
        "AZURE_SUBSCRIPTION_ID=\"fdc04a72-8109-4807-9dc4-c809f25b6f42\"",
        "AZURE_REGION=\"eastus\"",
        "AZURE_RESOURCE_GROUP=\"rg-chec-dashboard-dev\"",
        "DATABRICKS_WORKSPACE_NAME=\"adb-chec-dashboard-dev\"",
        "DATABRICKS_WORKSPACE_ID=\"\"",
        "DATABRICKS_HOST=\"https://adb-7405611288758888.8.azuredatabricks.net\"",
        "DATABRICKS_AUTH_TYPE=\"azure-cli\"",
        "CATALOG_NAME=\"chec_dbx_demo\"",
        "APP_NAME=\"chec-dash-parity\"",
        "REVIEWER_PRINCIPAL=\"users\"",
        "UC_MANAGED_STORAGE_ENABLED=\"true\"",
        "UC_STORAGE_CONTAINER_NAME=\"unity-catalog\"",
        "UC_STORAGE_CREDENTIAL_NAME=\"chec_dashboard_mi_cred\"",
        "UC_EXTERNAL_LOCATION_NAME=\"chec_dashboard_uc_root\"",
        "WAREHOUSE_NAME=\"CHEC Dashboard Warehouse\"",
        "APP_WAREHOUSE_ID=\"\"",
        "GRANT_APP_WAREHOUSE_ACCESS=\"true\"",
        "CHECK_CLASSIC_SKU_FALLBACKS=\"false\"",
        "FRESH_INSTALL_RESET_STALE_BUNDLE_STATE=\"true\"",
        "USE_CLASSIC_JOBS=\"false\"",
        "APP_SUMMARY_INTERPRETABILITY_ENABLED=\"true\"",
        "APP_MODEL_BACKEND=\"mock\"",
        "APP_DATABRICKS_MODEL_ENDPOINT=\"\"",
        "APP_GEMINI_SECRET_RESOURCE_KEY=\"\"",
        "FRESH_INSTALL_STAGE=\"all\"",
    ]:
        assert expected_text in template_text

    for stage_name in [
        "azure",
        "foundation",
        "dashboard",
        "chatbot",
        "app",
        "permissions",
        "validate",
    ]:
        assert f"selected_stage {stage_name}" in orchestrator_text

    ordered_calls = [
        "az databricks workspace create",
        "databricks warehouses create",
        "databricks bundle validate",
        "databricks bundle deploy",
        "upload_normalized_vano_assets.sh",
        "publish_phase2_dashboard.sh",
        "upload_chatbot_assets.sh",
        "deploy_phase35_databricks_app.sh",
        "apply_phase35_app_permissions.sh",
        "gold_timeseries_daily_attribution",
    ]
    positions = [orchestrator_text.index(call) for call in ordered_calls]
    assert positions == sorted(positions)
    assert ".env.databricks-fresh-install" in orchestrator_text
    assert "stage_override" in orchestrator_text
    assert "upsert_env APP_WAREHOUSE_ID" in orchestrator_text
    assert "GRANT_APP_WAREHOUSE_ACCESS" in orchestrator_text
    assert "No Unity Catalog metastore is attached" in orchestrator_text
    assert "reset_stale_bundle_state" in orchestrator_text
    assert "Moved stale local Databricks bundle state" in orchestrator_text
    assert "provider_config" in orchestrator_text
    assert "ensure_uc_catalog" in orchestrator_text
    assert "derive_uc_storage_defaults" in orchestrator_text
    assert "App /ready returned HTTP" in orchestrator_text
    assert "Databricks App OAuth is protecting the endpoint" in orchestrator_text
    assert "az storage account create" in orchestrator_text
    assert "az databricks access-connector create" in orchestrator_text
    assert "databricks storage-credentials create --json" in orchestrator_text
    assert "databricks external-locations create" in orchestrator_text
    assert "--storage-root" in orchestrator_text
    assert "databricks auth token" in orchestrator_text

    subprocess.run(["bash", "-n", str(orchestrator)], check=True)


def test_phase1_notebooks_and_guardrails_exist() -> None:
    expected_files = [
        "_shared_phase1.py",
        "00_bootstrap_uc.py",
        "01_stage_bronze_tables.py",
        "02_validate_ingest.py",
        "03_build_silver_gold.py",
        "04_probability_explorer.py",
        "05_stage_ml_assets.py",
        "06_map_explorer.py",
    ]
    for file_name in expected_files:
        assert (NOTEBOOK_DIR / file_name).exists()

    explorer_text = _read(NOTEBOOK_DIR / "04_probability_explorer.py")
    assert "define_probability_widgets()" in explorer_text

    map_text = _read(NOTEBOOK_DIR / "06_map_explorer.py")
    assert "define_map_widgets()" in map_text
    assert 'gold", "gold_map_points"' in map_text
    assert "scatter_geo" in map_text
    assert "family_group" in map_text

    build_gold_text = _read(NOTEBOOK_DIR / "03_build_silver_gold.py")
    assert '.withColumn("municipio", F.lit("Sin municipio"))' not in build_gold_text
    assert 'F.coalesce(F.col("municipio_vano"), F.col("municipio_trafo"), F.lit("Sin municipio"))' in build_gold_text
    assert "gold_map_line_segments" in build_gold_text
    assert "gold_map_filter_index" in build_gold_text
    assert "gold_map_event_days" in build_gold_text
    assert "gold_timeseries_event_details" in build_gold_text
    assert "gold_timeseries_daily_attribution" in build_gold_text
    assert "gold_timeseries_environment_daily" in build_gold_text
    assert '.withColumn("map_period"' in build_gold_text
    assert '.withColumn("map_day"' in build_gold_text

    shared_text = _read(NOTEBOOK_DIR / "_shared_phase1.py")
    assert "def define_probability_widgets" in shared_text
    assert '"agent_config"' in shared_text
    assert '"agent_tools"' in shared_text
    assert '"agent_observability"' in shared_text
    assert "def define_map_widgets" in shared_text
    assert 'dbutils_obj.widgets.dropdown(' in shared_text
    assert '"criteria"' in shared_text
    assert '"point_kind"' in shared_text
    assert '"geometry_kind"' in shared_text
    assert '"selected_circuit"' in shared_text
    assert '"selected_municipio"' in shared_text
    assert '"target_column"' in shared_text
    assert '"selected_family"' in shared_text
    assert "Spark Connect rejects Arrow half-precision floats" in shared_text
    assert 'numeric_series = numeric_series.astype("float64")' in shared_text
    assert "isinstance(series.dtype, pd.PeriodDtype)" in shared_text
    assert "def write_pandas_frame_to_delta" in shared_text
    assert "target_chunk_bytes: int = 64 * 1024 * 1024" in shared_text
    assert 'writer = writer.option("overwriteSchema", "true")' in shared_text

    ml_text = _read(NOTEBOOK_DIR / "05_stage_ml_assets.py")
    assert "phase1_secret_guardrail" in ml_text
    assert "excluded_from_sync" in ml_text
    assert "databricks-secret-scope" in ml_text
    assert "phase1_artifact_inventory" in ml_text

    bootstrap_text = _read(NOTEBOOK_DIR / "00_bootstrap_uc.py")
    assert "SHOW CATALOGS LIKE" in bootstrap_text
    assert "CREATE CATALOG IF NOT EXISTS" not in bootstrap_text
    assert "CREATE VOLUME IF NOT EXISTS {table_name(" in bootstrap_text
    assert "'agent_config', 'skills'" in bootstrap_text
    assert "CREATE VOLUME IF NOT EXISTS {volume_path(" not in bootstrap_text
    assert "phase1_manifest_json" in bootstrap_text
    assert "phase1_source_inventory" in bootstrap_text
    assert "phase1_table_registry" in bootstrap_text
    assert "phase1_artifact_inventory" in bootstrap_text

    bronze_text = _read(NOTEBOOK_DIR / "01_stage_bronze_tables.py")
    assert "AVAILABLE_IN_VOLUME" in bronze_text
    assert "Upload raw phase 1 assets to the source volume" in bronze_text
    assert '"parquet"' in bronze_text
    assert 'if load_mode == "parquet"' in bronze_text
    assert "write_pandas_frame_to_delta(spark, normalized_frame, bronze_table_name)" in bronze_text

    validate_text = _read(NOTEBOOK_DIR / "02_validate_ingest.py")
    assert "primary_key" in validate_text
    assert "foreign_key_" in validate_text
    assert "weather_feature_columns" in validate_text
    assert "central_fact_row_count" in validate_text
    assert "source_hash" in validate_text
    assert "full_reconstruction" in validate_text

    preflight_script = _read(DATABRICKS_DIR / "scripts" / "preflight_phase1_deploy.sh")
    assert "run_with_retries()" in preflight_script
    assert "extract_json_payload()" in preflight_script
    assert "databricks metastores current -o json" in preflight_script
    assert "databricks clusters list-node-types -o json" in preflight_script
    assert "CHECK_CLASSIC_SKU_FALLBACKS" in preflight_script
    assert "Skipping Azure vCPU quota and SKU restriction checks" in preflight_script
    assert 'az vm list-usage -l "${REGION}" -o json' in preflight_script
    assert 'Standard_DC4as_v5' in preflight_script
    assert 'Standard_L4aos_v4' in preflight_script
    assert 'Standard_D4as_v5' in preflight_script
    assert 'Target catalog: ${CATALOG_NAME}' in preflight_script

    upload_script = _read(DATABRICKS_DIR / "scripts" / "upload_normalized_vano_assets.sh")
    assert "run_with_retries()" in upload_script
    assert "extract_json_payload()" in upload_script
    assert "OPENAI_API_Key.txt" not in upload_script
    assert "databricks fs cp" in upload_script
    assert "databricks fs ls" in upload_script
    assert "Skipping ${relative_path}; already uploaded" in upload_script
    assert "evento_vano_trafo.parquet" in upload_script
    assert "normalization_manifest.json" in upload_script
    assert "municipio_enrichment/municipio_lookup_manifest.json" in upload_script
    assert 'CATALOG_NAME="${CATALOG_NAME:-chec_dbx_demo}"' in upload_script

    publish_notebooks_script = _read(DATABRICKS_DIR / "scripts" / "publish_phase2_notebooks.sh")
    assert "/Shared/CHEC Phase2 Pilot/Notebooks" in publish_notebooks_script
    assert "04_probability_explorer.py" in publish_notebooks_script
    assert "06_map_explorer.py" in publish_notebooks_script
    assert "databricks workspace import" in publish_notebooks_script

    publish_dashboard_script = _read(DATABRICKS_DIR / "scripts" / "publish_phase2_dashboard.sh")
    assert "CHEC Summary Pilot" in publish_dashboard_script
    assert "databricks lakeview publish" in publish_dashboard_script
    assert "PUBLISH_EMBED_CREDENTIALS" in publish_dashboard_script
    assert "DASHBOARD_NAME_SUFFIX" in publish_dashboard_script
    assert "endswith($suffix)" in publish_dashboard_script

    sync_dashboard_script = _read(DATABRICKS_DIR / "scripts" / "sync_phase2_dashboard_from_workspace.sh")
    assert "databricks lakeview get" in sync_dashboard_script
    assert ".serialized_dashboard" in sync_dashboard_script
    assert "DASHBOARD_NAME_SUFFIX" in sync_dashboard_script
    assert "OUTPUT_PATH" in sync_dashboard_script

    stage_app_script = _read(DATABRICKS_DIR / "scripts" / "stage_phase35_databricks_app.py")
    assert "APP_WAREHOUSE_ID" in stage_app_script
    assert "APP_GOLD_SCHEMA" in stage_app_script
    assert "copytree(repo_root / \"src\"" in stage_app_script
    assert "ignore=IGNORE_PATTERNS" in stage_app_script
    assert "shutil.ignore_patterns(" in stage_app_script
    assert "requirements_template" in stage_app_script
    assert "app.yaml" in stage_app_script

    deploy_app_script = _read(DATABRICKS_DIR / "scripts" / "deploy_phase35_databricks_app.sh")
    assert "databricks apps create" in deploy_app_script
    assert "databricks apps update" in deploy_app_script
    assert 'APP_CHATBOT_CONVERSATION_BACKEND="${APP_CHATBOT_CONVERSATION_BACKEND:-databricks_sql}"' in deploy_app_script
    assert 'APP_CHATBOT_CONVERSATION_SCHEMA="${APP_CHATBOT_CONVERSATION_SCHEMA:-agent}"' in deploy_app_script
    assert "APP_CHATBOT_MEMORY_MAX_TURNS" in deploy_app_script
    assert "setup_chatbot_conversation_tables()" in deploy_app_script
    assert "setup_phase3_conversation_tables.py" in deploy_app_script
    assert "APP_CHATBOT_CONTEXT_TOOLS_SCHEMA" in deploy_app_script
    assert "setup_chatbot_context_tools()" in deploy_app_script
    assert "setup_phase4_context_tools.py" in deploy_app_script
    assert 'APP_RETRIEVER_BACKEND="${APP_RETRIEVER_BACKEND:-databricks_ai_search}"' in deploy_app_script
    assert "APP_AI_SEARCH_ENDPOINT_NAME" in deploy_app_script
    assert "APP_AI_SEARCH_INDEX_FULL_NAME" in deploy_app_script
    assert "APP_AI_SEARCH_EMBEDDING_ENDPOINT_NAME" in deploy_app_script
    assert "databricks-qwen3-embedding-0-6b" in deploy_app_script
    assert "setup_chatbot_ai_search()" in deploy_app_script
    assert "setup_phase5_ai_search.py" in deploy_app_script
    assert "chatbot_ai_search_index" in deploy_app_script
    assert "APP_CHATBOT_OBSERVABILITY_ENABLED" in deploy_app_script
    assert "APP_CHATBOT_TELEMETRY_SCHEMA" in deploy_app_script
    assert "APP_CHATBOT_EVAL_REPORT_ONLY" in deploy_app_script
    assert "APP_CHATBOT_EVAL_LLM_JUDGES_ENABLED" in deploy_app_script
    assert "APP_MLFLOW_TRACKING_URI" in deploy_app_script
    assert "APP_MLFLOW_EXPERIMENT_NAME" in deploy_app_script
    assert "APP_MLFLOW_PROMPT_NAME" in deploy_app_script
    assert "APP_MLFLOW_PROMPT_ALIAS" in deploy_app_script
    assert "setup_chatbot_observability()" in deploy_app_script
    assert "setup_phase9_observability.py" in deploy_app_script
    assert 'APP_LLM_PROVIDER="${APP_LLM_PROVIDER:-databricks_model_serving}"' in deploy_app_script
    assert 'APP_MODEL_BACKEND="${APP_MODEL_BACKEND:-mock}"' in deploy_app_script
    assert 'APP_DATABRICKS_MODEL_ENDPOINT="${APP_DATABRICKS_MODEL_ENDPOINT:-}"' in deploy_app_script
    assert "APP_LLM_ENDPOINT_NAME" in deploy_app_script
    assert "databricks-qwen3-next-80b-a3b-instruct" in deploy_app_script
    assert "chatbot_llm_endpoint" in deploy_app_script
    assert "serving_endpoint" in deploy_app_script
    assert "CAN_QUERY" in deploy_app_script
    assert "CAN_MANAGE" not in deploy_app_script
    assert "APP_CHATBOT_CORPUS_VOLUME_RESOURCE_KEY" in deploy_app_script
    assert "APP_CHATBOT_SKILLS_VOLUME_RESOURCE_KEY" in deploy_app_script
    assert "agent_config.skills" in deploy_app_script
    assert "APP_CHATBOT_SKILLS_VOLUME_PATH" in deploy_app_script
    assert "ensure_chatbot_skill_lifecycle_dirs()" in deploy_app_script
    assert "active draft archive" in deploy_app_script
    assert "APP_WAREHOUSE_ID=\"${APP_WAREHOUSE_ID}\"" in deploy_app_script
    assert "APP_CHATBOT_ENABLED=\"${APP_CHATBOT_ENABLED}\"" in deploy_app_script
    assert "APP_LLM_PROVIDER=\"${APP_LLM_PROVIDER}\"" in deploy_app_script
    assert "export APP_MODEL_BACKEND" in deploy_app_script
    assert "export APP_DATABRICKS_MODEL_ENDPOINT" in deploy_app_script
    assert "APP_RETRIEVER_BACKEND=\"${APP_RETRIEVER_BACKEND}\"" in deploy_app_script
    assert "stage_phase35_databricks_app.py" in deploy_app_script
    assert "APP_GEMINI_SECRET_RESOURCE_KEY" in deploy_app_script
    assert "APP_GEMINI_SECRET_SCOPE" in deploy_app_script
    assert "APP_GEMINI_SECRET_KEY" in deploy_app_script
    assert 'APP_GEMINI_SECRET_RESOURCE_KEY="${APP_GEMINI_SECRET_RESOURCE_KEY:-}"' in deploy_app_script
    assert "require_env APP_WAREHOUSE_ID" in deploy_app_script
    assert "READ_VOLUME" in deploy_app_script
    assert "GEMINI_API_KEY" not in deploy_app_script
    assert "databricks workspace delete" in deploy_app_script
    assert "--recursive" in deploy_app_script
    assert "databricks workspace import-dir" in deploy_app_script
    assert "databricks apps deploy" in deploy_app_script
    assert "SNAPSHOT" in deploy_app_script

    app_permissions_script = _read(DATABRICKS_DIR / "scripts" / "apply_phase35_app_permissions.sh")
    assert "databricks apps get-permission-levels" in app_permissions_script
    assert "databricks apps get" in app_permissions_script
    assert "databricks apps set-permissions" in app_permissions_script
    assert "APP_SERVICE_PRINCIPAL_NAME" in app_permissions_script
    assert "APP_SERVICE_PRINCIPAL_APPLICATION_ID" in app_permissions_script
    assert "APP_UC_PRINCIPAL" in app_permissions_script
    assert "APP_WAREHOUSE_ID" in app_permissions_script
    assert "DATABRICKS_SQL_WAREHOUSE_ID" in app_permissions_script
    assert "GRANT_APP_WAREHOUSE_ACCESS" in app_permissions_script
    assert "databricks permissions update warehouses" in app_permissions_script
    assert 'permission_level: "CAN_USE"' in app_permissions_script
    assert "databricks grants update catalog" in app_permissions_script
    assert "databricks grants update schema" in app_permissions_script
    assert "APP_CONVERSATION_SCHEMA" in app_permissions_script
    assert "GRANT_CHATBOT_CONVERSATION_ACCESS" in app_permissions_script
    assert "APP_CONTEXT_TOOLS_SCHEMA" in app_permissions_script
    assert "GRANT_CHATBOT_CONTEXT_TOOL_ACCESS" in app_permissions_script
    assert "APP_CONTEXT_TOOL_FUNCTIONS" in app_permissions_script
    assert "APP_CONTEXT_TOOL_VIEWS" in app_permissions_script
    assert "APP_AI_SEARCH_INDEX_FULL_NAME" in app_permissions_script
    assert "GRANT_CHATBOT_AI_SEARCH_ACCESS" in app_permissions_script
    assert "APP_TELEMETRY_SCHEMA" in app_permissions_script
    assert "agent_observability" in app_permissions_script
    assert "GRANT_CHATBOT_OBSERVABILITY_ACCESS" in app_permissions_script
    assert "APP_MLFLOW_EXPERIMENT_NAME" in app_permissions_script
    assert "GRANT_CHATBOT_MLFLOW_EXPERIMENT_ACCESS" in app_permissions_script
    assert "databricks experiments get-by-name" in app_permissions_script
    assert "databricks experiments update-permissions" in app_permissions_script
    assert "APP_LLM_ENDPOINT_NAME" in app_permissions_script
    assert "GRANT_CHATBOT_LLM_ENDPOINT_ACCESS" in app_permissions_script
    assert "databricks serving-endpoints update-permissions" in app_permissions_script
    assert "databricks grants update function" in app_permissions_script
    assert "databricks grants update table" in app_permissions_script
    assert 'add: ["USE_SCHEMA", "EXECUTE"]' in app_permissions_script
    assert "EXECUTE" in app_permissions_script
    assert "MODIFY" in app_permissions_script
    assert "USE_CATALOG" in app_permissions_script
    assert "USE_SCHEMA" in app_permissions_script
    assert "SELECT" in app_permissions_script
    assert "CAN_USE" in app_permissions_script
    assert "CAN_MANAGE" in app_permissions_script

    app_template = _read(DATABRICKS_DIR / "apps" / "chec_dash_parity" / "app.yaml")
    assert "DATA_BACKEND" in app_template
    assert "API_TRANSPORT" in app_template
    assert "DATABRICKS_SQL_WAREHOUSE_ID" in app_template
    assert "CHATBOT_CORPUS_DIR" in app_template
    assert "CHATBOT_CORPUS_VOLUME_DIR" in app_template
    assert "CHATBOT_CONVERSATION_BACKEND" in app_template
    assert "CHATBOT_CONVERSATION_SCHEMA" in app_template
    assert "CHATBOT_CONTEXT_TOOLS_SCHEMA" in app_template
    assert "CHATBOT_MEMORY_MAX_TURNS" in app_template
    assert "CHATBOT_OBSERVABILITY_ENABLED" in app_template
    assert "CHATBOT_TELEMETRY_SCHEMA" in app_template
    assert "CHATBOT_EVAL_REPORT_ONLY" in app_template
    assert "CHATBOT_EVAL_LLM_JUDGES_ENABLED" in app_template
    assert "CHATBOT_EVAL_ENFORCE" in app_template
    assert "MLFLOW_TRACKING_URI" in app_template
    assert "MLFLOW_EXPERIMENT_NAME" in app_template
    assert "MLFLOW_PROMPT_NAME" in app_template
    assert "MLFLOW_PROMPT_ALIAS" in app_template
    assert "RETRIEVER_BACKEND" in app_template
    assert "AI_SEARCH_ENDPOINT_NAME" in app_template
    assert "AI_SEARCH_INDEX_NAME" in app_template
    assert "AI_SEARCH_TOP_K" in app_template
    assert "AI_SEARCH_QUERY_TYPE" in app_template
    assert "AI_SEARCH_EMBEDDING_ENDPOINT_NAME" in app_template
    assert "AI_SEARCH_ENDPOINT_TYPE" in app_template
    assert "valueFrom: \"__AI_SEARCH_INDEX_RESOURCE_KEY__\"" in app_template
    assert "LLM_ENDPOINT_NAME" in app_template
    assert "valueFrom: \"__LLM_ENDPOINT_RESOURCE_KEY__\"" in app_template
    assert "LLM_MAX_TOKENS" in app_template
    assert "LLM_TEMPERATURE" in app_template
    assert "valueFrom: \"__CHATBOT_CORPUS_VOLUME_RESOURCE_KEY__\"" in app_template
    assert "gunicorn" in app_template
    assert "- sh" in app_template
    assert '- -c' in app_template
    assert '${DATABRICKS_APP_PORT}' in app_template

    app_wsgi = _read(DATABRICKS_DIR / "apps" / "chec_dash_parity" / "databricks_app_wsgi.py")
    assert "dash_app.server" in app_wsgi

    app_requirements = _read(DATABRICKS_DIR / "apps" / "chec_dash_parity" / "requirements.txt")
    assert "dash==2.18.1" in app_requirements
    assert "databricks-sql-connector" in app_requirements
    assert "mlflow[databricks]>=3.3,<4" in app_requirements
    assert "pytest" not in app_requirements

    permissions_script = _read(DATABRICKS_DIR / "scripts" / "apply_phase2_pilot_permissions.sh")
    assert 'PILOT_REVIEWER_PRINCIPAL="${PILOT_REVIEWER_PRINCIPAL:-users}"' in permissions_script
    assert "resolve_permission_level()" in permissions_script
    assert "databricks permissions get-permission-levels" in permissions_script
    assert "GRANT_REVIEWER_NOTEBOOK_ACCESS" in permissions_script
    assert "GRANT_REVIEWER_DATA_ACCESS" in permissions_script
    assert "CAN_READ" in permissions_script
    assert "CAN_EDIT" in permissions_script
    assert "CAN_MANAGE_RUN" in permissions_script
    assert "USE_CATALOG" in permissions_script
    assert "USE_SCHEMA" in permissions_script
    assert "SELECT" in permissions_script
    assert "DASHBOARD_NAME_SUFFIX" in permissions_script

    dashboard_text = _read(DATABRICKS_DIR / "dashboards" / "chec_summary_pilot.lvdash.json")
    dashboard_json = json.loads(dashboard_text)
    assert list(dashboard_json.keys()) == ["datasets", "pages"]
    assert dashboard_json["datasets"][0]["name"] == "summary_daily"
    assert "queryLines" in dashboard_json["datasets"][0]
    assert dashboard_json["datasets"][0]["catalog"] == "chec_dbx_demo"
    assert dashboard_json["datasets"][0]["schema"] == "gold"
    assert dashboard_json["pages"][0]["displayName"] == "Resumen"
    assert "Piloto de resumen CHEC" in dashboard_text
    assert "Rango de fechas" in dashboard_text
    assert "Familia de eventos" in dashboard_text
    assert "Eventos totales" in dashboard_text
    assert "Usuarios afectados" in dashboard_text
    assert "Tendencia mensual de eventos" in dashboard_text
    assert "Tendencia mensual de UITI" in dashboard_text
    assert "Date Range" not in dashboard_text
    assert "Event Family" not in dashboard_text
    assert "Total Events" not in dashboard_text
    assert "Affected Users" not in dashboard_text
    assert "filter-date-range-picker" in dashboard_text
    assert '"widgetType": "counter"' in dashboard_text
    assert '"widgetType": "bar"' in dashboard_text
    assert "gold_impact_daily" in dashboard_text
    assert "sum(uiti_total)" in dashboard_text
    assert '"name": "main_query"' in dashboard_text

    readme_text = _read(DATABRICKS_DIR / "README.md")
    assert "scripts/preflight_phase1_deploy.sh" in readme_text
    assert "serverless" in readme_text.casefold()
    assert "chec_phase1_bootstrap_classic" in readme_text
    assert "chec_phase1_ingest_validation_classic" in readme_text
    assert "chec_dbx_demo" in readme_text
    assert "CHEC Summary Pilot" in readme_text
    assert "publish_phase2_dashboard.sh" in readme_text
    assert "publish_phase2_notebooks.sh" in readme_text
    assert "sync_phase2_dashboard_from_workspace.sh" in readme_text
    assert "GRANT_REVIEWER_NOTEBOOK_ACCESS=true" in readme_text
    assert "GRANT_REVIEWER_DATA_ACCESS=true" in readme_text
    assert "workspace `users` group" in readme_text

    upload_chatbot_assets_script = _read(DATABRICKS_DIR / "scripts" / "upload_chatbot_assets.sh")
    assert "validate_chatbot_skills.py" in upload_chatbot_assets_script
    assert "VALIDATE_CHATBOT_SKILLS" in upload_chatbot_assets_script
    assert "SKILLS_VOLUME_ROOT" in upload_chatbot_assets_script
    assert '"active"' in upload_chatbot_assets_script
    assert '"draft"' in upload_chatbot_assets_script
    assert '"archive"' in upload_chatbot_assets_script
    assert '"knowledge"' in upload_chatbot_assets_script
    assert '"prompts"' in upload_chatbot_assets_script
    assert '"contracts"' in upload_chatbot_assets_script
    assert "KNOWLEDGE_SOURCE_DIR" in upload_chatbot_assets_script
    assert "PROMPTS_SOURCE_DIR" in upload_chatbot_assets_script
    assert "CONTRACTS_SOURCE_DIR" in upload_chatbot_assets_script
    assert "structured_context_builder.yml" in upload_chatbot_assets_script
    assert "what_if_simulation_assistant.yml" in upload_chatbot_assets_script
    assert "evidence_report_writer.yml" in upload_chatbot_assets_script
    assert "what_if_simulation_assistant.v1.md" in upload_chatbot_assets_script
    assert "what_if_result.schema.json" in upload_chatbot_assets_script
    assert "variable_context.yml" in upload_chatbot_assets_script
    assert "variable_context.md" in upload_chatbot_assets_script
    assert "variable_interactions.yml" in upload_chatbot_assets_script
    assert "variable_interactions.md" in upload_chatbot_assets_script

    validate_chatbot_skills_script = _read(DATABRICKS_DIR / "scripts" / "validate_chatbot_skills.py")
    assert "get_skill_status" in validate_chatbot_skills_script
    assert "Skill validation failed" in validate_chatbot_skills_script

    setup_conversation_script = _read(DATABRICKS_DIR / "scripts" / "setup_phase3_conversation_tables.py")
    assert "CREATE SCHEMA IF NOT EXISTS" in setup_conversation_script
    assert "agent_conversations" in setup_conversation_script
    assert "agent_messages" in setup_conversation_script
    assert "agent_feedback" in setup_conversation_script
    assert "CHATBOT_CONVERSATION_SCHEMA" in setup_conversation_script
    assert "llm_provider" in setup_conversation_script
    assert "model_endpoint_name" in setup_conversation_script
    assert "analysis_stage" in setup_conversation_script
    assert "capability_id" in setup_conversation_script
    assert "capability_status" in setup_conversation_script
    assert "safe_fallback_used" in setup_conversation_script
    assert "validation_status" in setup_conversation_script
    assert "contract_hash" in setup_conversation_script
    assert "stage_metadata_json" in setup_conversation_script
    assert "agent_tool_calls_json" in setup_conversation_script
    assert "agent_skipped_tools_json" in setup_conversation_script
    assert "agent_route_summary_json" in setup_conversation_script
    assert "structured_answer_json" in setup_conversation_script
    assert "answer_validation_json" in setup_conversation_script
    assert "citation_validation_json" in setup_conversation_script
    assert "compliance_validation_json" in setup_conversation_script
    assert "prompt_name" in setup_conversation_script
    assert "prompt_version" in setup_conversation_script
    assert "prompt_hash" in setup_conversation_script
    assert "mlflow_trace_id" in setup_conversation_script
    assert "mlflow_run_id" in setup_conversation_script
    assert "latency_ms" in setup_conversation_script
    assert "ALTER TABLE" in setup_conversation_script

    setup_observability_script = _read(DATABRICKS_DIR / "scripts" / "setup_phase9_observability.py")
    assert "analysis_stage" in setup_observability_script
    assert "capability_id" in setup_observability_script
    assert "validation_status" in setup_observability_script
    assert "contract_hash" in setup_observability_script
    assert "TURN_TRACE_COLUMNS" in setup_observability_script

    setup_context_tools_script = _read(DATABRICKS_DIR / "scripts" / "setup_phase4_context_tools.py")
    assert "CREATE SCHEMA IF NOT EXISTS" in setup_context_tools_script
    assert "agent_tools" in setup_context_tools_script
    assert "gold_agent_view_context" in setup_context_tools_script
    assert "gold_agent_event_context" in setup_context_tools_script
    assert "gold_agent_asset_context" in setup_context_tools_script
    assert "gold_agent_circuit_history" in setup_context_tools_script
    assert "gold_timeseries_daily_attribution" in setup_context_tools_script
    assert "get_dashboard_context" in setup_context_tools_script
    assert "get_reliability_summary" in setup_context_tools_script
    assert "get_compliance_context" in setup_context_tools_script
    assert "get_event_context" in setup_context_tools_script
    assert "get_asset_context" in setup_context_tools_script
    assert "get_circuit_history" in setup_context_tools_script
    assert "get_timeseries_interpretability_context" in setup_context_tools_script
    assert "source_function" in setup_context_tools_script
    assert "source_view" in setup_context_tools_script
    assert "context_hash" in setup_context_tools_script

    setup_ai_search_script = _read(DATABRICKS_DIR / "scripts" / "setup_phase5_ai_search.py")
    assert "silver.technical_doc_chunks" in setup_ai_search_script
    assert "gold.technical_doc_chunks_current" in setup_ai_search_script
    assert "technical_doc_chunks_current_index" in setup_ai_search_script
    assert "chec-agent-search" in setup_ai_search_script
    assert "databricks-qwen3-embedding-0-6b" in setup_ai_search_script
    assert "TRIGGERED" in setup_ai_search_script
    assert "hybrid" in setup_ai_search_script
    assert "vector-search-endpoints" in setup_ai_search_script
    assert "vector-search-indexes" in setup_ai_search_script
    assert "delta.enableChangeDataFeed" in setup_ai_search_script

    setup_observability_script = _read(DATABRICKS_DIR / "scripts" / "setup_phase9_observability.py")
    assert "agent_observability" in setup_observability_script
    assert "agent_turn_traces" in setup_observability_script
    assert "agent_feedback_events" in setup_observability_script
    assert "agent_evaluation_results" in setup_observability_script
    assert "agent_release_reports" in setup_observability_script
    assert "agent_evaluation_examples" in setup_observability_script
    assert "mlflow.genai.register_prompt" in setup_observability_script
    assert "workspace.mkdirs" in setup_observability_script
    assert "MLflow experiment parent directory" in setup_observability_script
    assert "chec_chatbot_answer_prompt" in setup_observability_script
    assert "needs_sme_review" in setup_observability_script
    assert "uiti_impact_01" in setup_observability_script
    assert "memory_05" in setup_observability_script

    run_eval_script = _read(DATABRICKS_DIR / "scripts" / "run_phase9_evaluation.py")
    assert "agent_turn_traces" in run_eval_script
    assert "agent_evaluation_results" in run_eval_script
    assert "agent_release_reports" in run_eval_script
    assert "build_release_report" in run_eval_script
    assert "CHATBOT_EVAL_ENFORCE" in run_eval_script

    deploy_app_script = _read(DATABRICKS_DIR / "scripts" / "deploy_phase35_databricks_app.sh")
    assert "APP_CHATBOT_ENABLED=\"${APP_CHATBOT_ENABLED:-true}\"" in deploy_app_script
    assert "export APP_CHATBOT_ENABLED" in deploy_app_script

    phase7_doc = _read(ROOT / "docs" / "phase7_mcp_genie_readiness.md")
    assert "Databricks managed MCP servers" in phase7_doc
    assert "AI Search managed MCP server" in phase7_doc
    assert "Unity Catalog functions managed MCP server" in phase7_doc
    assert "Genie Space managed MCP server" in phase7_doc
    assert "general Databricks SQL MCP server is deferred" in phase7_doc
    assert "read/write" in phase7_doc

    root_readme = _read(ROOT / "README.md")
    assert "Fresh Azure + Databricks Deployment" in root_readme
    assert "docs/AZURE_DATABRICKS_FRESH_INSTALL.md" in root_readme
    assert "Databricks App is the current canonical deployment target" in root_readme
    assert "databricks_model_serving" in root_readme
    assert "databricks_ai_search" in root_readme
    assert "prototype-only fallback" in root_readme

    databricks_readme = _read(DATABRICKS_DIR / "README.md")
    assert "Databricks App / Agentic RAG Flow" in databricks_readme
    assert "../docs/AZURE_DATABRICKS_FRESH_INSTALL.md" in databricks_readme
    assert "agent_observability" in databricks_readme

    parity_doc = _read(ROOT / "docs" / "phase35_databricks_app_parity.md")
    assert "Historical note" in parity_doc
    assert "docs/AZURE_DATABRICKS_FRESH_INSTALL.md" in parity_doc
    assert "databricks_model_serving" in parity_doc
    assert "databricks_ai_search" in parity_doc
    assert "databricks_sql" in parity_doc
    assert "agent_observability" in parity_doc

    fresh_install_doc = _read(ROOT / "docs" / "AZURE_DATABRICKS_FRESH_INSTALL.md")
    for expected_text in [
        "Fresh Azure + Databricks Install Runbook",
        "Quick Start: One-Command Fresh Install",
        "databricks/fresh_install.env.example",
        "fresh_install_databricks.sh",
        "FRESH_INSTALL_STAGE",
        "Azure subscription",
        "Azure CLI",
        "Databricks CLI",
        "Unity Catalog",
        "Databricks Asset Bundle",
        "upload_normalized_vano_assets.sh",
        "upload_chatbot_assets.sh",
        "deploy_phase35_databricks_app.sh",
        "apply_phase35_app_permissions.sh",
        "/chatbot/status",
        "MLflow",
        "AI Search",
        "Model Serving",
        "evaluation report",
        "agent_observability",
        "Prompt Registry",
        "Annex A: Installing Local Prerequisites",
        "Python 3.12",
        "venv",
        "jq",
        "git --version",
        "databricks current-user me",
        "az login",
        "corporate proxy",
        "gold_timeseries_daily_attribution",
        "APP_GEMINI_SECRET_RESOURCE_KEY=\"\"",
    ]:
        assert expected_text in fresh_install_doc

    for text in [
        _read(DATABRICKS_DIR / "databricks.yml"),
        _read(DATABRICKS_DIR / "scripts" / "deploy_phase35_databricks_app.sh"),
        _read(DATABRICKS_DIR / "scripts" / "stage_phase35_databricks_app.py"),
        _read(DATABRICKS_DIR / "scripts" / "publish_phase2_dashboard.sh"),
        _read(DATABRICKS_DIR / "README.md"),
        _read(ROOT / "docs" / "phase35_databricks_app_parity.md"),
        _read(ROOT / "docs" / "phase2_databricks_consumption_pilot.md"),
    ]:
        assert "4437a6195e05c59c" not in text


def test_phase35_app_staging_uses_chatbot_volume_resource() -> None:
    env = os.environ.copy()
    env.update(
        {
            "APP_CHATBOT_ENABLED": "true",
            "APP_CHATBOT_CORPUS_VOLUME_RESOURCE_KEY": "chatbot_corpus_volume",
            "APP_CHATBOT_CORPUS_SUBDIR": "chatbot_corpus",
            "APP_CHATBOT_SKILLS_VOLUME_RESOURCE_KEY": "chatbot_skills_volume",
            "APP_CHATBOT_SKILLS_SUBDIR": "active",
        }
    )
    subprocess.run(
        [sys.executable, "databricks/scripts/stage_phase35_databricks_app.py"],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    build_root = DATABRICKS_DIR / "build" / "chec_dash_parity"
    app_yaml = _read(build_root / "app.yaml")

    assert "CHATBOT_CORPUS_VOLUME_DIR" in app_yaml
    assert "CHATBOT_CORPUS_DIR" in app_yaml
    assert "valueFrom: \"chatbot_corpus_volume\"" in app_yaml
    assert "CHATBOT_CORPUS_SUBDIR" in app_yaml
    assert "value: \"chatbot_corpus\"" in app_yaml
    assert "CHATBOT_SKILLS_VOLUME_DIR" in app_yaml
    assert "valueFrom: \"chatbot_skills_volume\"" in app_yaml
    assert "CHATBOT_SKILLS_SUBDIR" in app_yaml
    assert "value: \"active\"" in app_yaml
    assert not (build_root / "data" / "chatbot_corpus").exists()


def test_phase35_app_staging_renders_conversation_memory_env() -> None:
    env = os.environ.copy()
    env.update(
        {
            "APP_CHATBOT_CONVERSATION_BACKEND": "databricks_sql",
            "APP_CHATBOT_CONVERSATION_SCHEMA": "agent",
            "APP_CHATBOT_CONTEXT_TOOLS_SCHEMA": "agent_tools",
            "APP_CHATBOT_MEMORY_MAX_TURNS": "3",
        }
    )
    subprocess.run(
        [sys.executable, "databricks/scripts/stage_phase35_databricks_app.py"],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    app_yaml = _read(DATABRICKS_DIR / "build" / "chec_dash_parity" / "app.yaml")

    assert "CHATBOT_CONVERSATION_BACKEND" in app_yaml
    assert "value: \"databricks_sql\"" in app_yaml
    assert "CHATBOT_CONVERSATION_SCHEMA" in app_yaml
    assert "value: \"agent\"" in app_yaml
    assert "CHATBOT_CONTEXT_TOOLS_SCHEMA" in app_yaml
    assert "value: \"agent_tools\"" in app_yaml
    assert "CHATBOT_MEMORY_MAX_TURNS" in app_yaml
    assert "value: \"3\"" in app_yaml


def test_phase35_app_staging_renders_summary_interpretability_env() -> None:
    env = os.environ.copy()
    env.update(
        {
            "APP_SUMMARY_INTERPRETABILITY_ENABLED": "true",
            "APP_SUMMARY_INTERPRETABILITY_MAX_POINTS": "7",
            "APP_SUMMARY_INTERPRETABILITY_HIGH_ROBUST_Z": "2.8",
            "APP_SUMMARY_INTERPRETABILITY_LOW_ROBUST_Z": "-2.2",
            "APP_SUMMARY_INTERPRETABILITY_DELTA_ROBUST_Z": "2.5",
            "APP_SUMMARY_INTERPRETABILITY_TOP_CONTRIBUTOR_PCT": "0.15",
            "APP_SUMMARY_INTERPRETABILITY_SUSTAINED_MIN_DAYS": "4",
            "APP_SUMMARY_INTERPRETABILITY_INCLUDE_AGENT_TEXT_DEFAULT": "false",
            "APP_SUMMARY_INTERPRETABILITY_CACHE_SECONDS": "90",
        }
    )
    subprocess.run(
        [sys.executable, "databricks/scripts/stage_phase35_databricks_app.py"],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    app_yaml = _read(DATABRICKS_DIR / "build" / "chec_dash_parity" / "app.yaml")

    assert "SUMMARY_INTERPRETABILITY_ENABLED" in app_yaml
    assert "SUMMARY_INTERPRETABILITY_MAX_POINTS" in app_yaml
    assert "value: \"7\"" in app_yaml
    assert "SUMMARY_INTERPRETABILITY_TOP_CONTRIBUTOR_PCT" in app_yaml
    assert "value: \"0.15\"" in app_yaml
    assert "SUMMARY_INTERPRETABILITY_INCLUDE_AGENT_TEXT_DEFAULT" in app_yaml
    assert "value: \"false\"" in app_yaml
    assert "SUMMARY_INTERPRETABILITY_CACHE_SECONDS" in app_yaml
    assert "value: \"90\"" in app_yaml


def test_phase35_app_staging_renders_observability_env() -> None:
    env = os.environ.copy()
    env.update(
        {
            "APP_CHATBOT_OBSERVABILITY_ENABLED": "true",
            "APP_CHATBOT_TELEMETRY_SCHEMA": "agent_observability",
            "APP_CHATBOT_EVAL_REPORT_ONLY": "true",
            "APP_CHATBOT_EVAL_LLM_JUDGES_ENABLED": "false",
            "APP_CHATBOT_EVAL_ENFORCE": "false",
            "APP_MLFLOW_TRACKING_URI": "databricks",
            "APP_MLFLOW_EXPERIMENT_NAME": "/Shared/chec_dash_parity/agent_observability",
            "APP_MLFLOW_PROMPT_NAME": "chec_chatbot_answer_prompt",
            "APP_MLFLOW_PROMPT_ALIAS": "production",
        }
    )
    subprocess.run(
        [sys.executable, "databricks/scripts/stage_phase35_databricks_app.py"],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    app_yaml = _read(DATABRICKS_DIR / "build" / "chec_dash_parity" / "app.yaml")

    assert "CHATBOT_OBSERVABILITY_ENABLED" in app_yaml
    assert "value: \"true\"" in app_yaml
    assert "CHATBOT_TELEMETRY_SCHEMA" in app_yaml
    assert "value: \"agent_observability\"" in app_yaml
    assert "CHATBOT_EVAL_REPORT_ONLY" in app_yaml
    assert "MLFLOW_TRACKING_URI" in app_yaml
    assert "value: \"databricks\"" in app_yaml
    assert "MLFLOW_EXPERIMENT_NAME" in app_yaml
    assert "/Shared/chec_dash_parity/agent_observability" in app_yaml
    assert "MLFLOW_PROMPT_NAME" in app_yaml
    assert "chec_chatbot_answer_prompt" in app_yaml
    assert "MLFLOW_PROMPT_ALIAS" in app_yaml
    assert "value: \"production\"" in app_yaml


def test_phase35_app_staging_renders_ai_search_env() -> None:
    env = os.environ.copy()
    env.update(
        {
            "APP_RETRIEVER_BACKEND": "databricks_ai_search",
            "APP_AI_SEARCH_ENDPOINT_NAME": "chec-agent-search",
            "APP_AI_SEARCH_INDEX_RESOURCE_KEY": "chatbot_ai_search_index",
            "APP_AI_SEARCH_TOP_K": "8",
            "APP_AI_SEARCH_QUERY_TYPE": "hybrid",
            "APP_AI_SEARCH_EMBEDDING_ENDPOINT_NAME": "databricks-qwen3-embedding-0-6b",
            "APP_AI_SEARCH_ENDPOINT_TYPE": "STANDARD",
        }
    )
    subprocess.run(
        [sys.executable, "databricks/scripts/stage_phase35_databricks_app.py"],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    app_yaml = _read(DATABRICKS_DIR / "build" / "chec_dash_parity" / "app.yaml")

    assert "RETRIEVER_BACKEND" in app_yaml
    assert "value: \"databricks_ai_search\"" in app_yaml
    assert "AI_SEARCH_ENDPOINT_NAME" in app_yaml
    assert "value: \"chec-agent-search\"" in app_yaml
    assert "AI_SEARCH_INDEX_NAME" in app_yaml
    assert "valueFrom: \"chatbot_ai_search_index\"" in app_yaml
    assert "AI_SEARCH_TOP_K" in app_yaml
    assert "value: \"8\"" in app_yaml
    assert "AI_SEARCH_QUERY_TYPE" in app_yaml
    assert "value: \"hybrid\"" in app_yaml
    assert "databricks-qwen3-embedding-0-6b" in app_yaml
    assert "value: \"STANDARD\"" in app_yaml


def test_phase35_app_staging_renders_model_serving_env() -> None:
    env = os.environ.copy()
    env.update(
        {
            "APP_LLM_PROVIDER": "databricks_model_serving",
            "APP_MODEL_BACKEND": "databricks",
            "APP_DATABRICKS_MODEL_ENDPOINT": "chec_predictive_endpoint",
            "APP_LLM_ENDPOINT_RESOURCE_KEY": "chatbot_llm_endpoint",
            "APP_LLM_MAX_TOKENS": "1200",
            "APP_LLM_TEMPERATURE": "0.2",
        }
    )
    subprocess.run(
        [sys.executable, "databricks/scripts/stage_phase35_databricks_app.py"],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    app_yaml = _read(DATABRICKS_DIR / "build" / "chec_dash_parity" / "app.yaml")

    assert "LLM_PROVIDER" in app_yaml
    assert "value: \"databricks_model_serving\"" in app_yaml
    assert "MODEL_BACKEND" in app_yaml
    assert "value: \"databricks\"" in app_yaml
    assert "DATABRICKS_MODEL_ENDPOINT" in app_yaml
    assert "value: \"chec_predictive_endpoint\"" in app_yaml
    assert "LLM_ENDPOINT_NAME" in app_yaml
    assert "valueFrom: \"chatbot_llm_endpoint\"" in app_yaml
    assert "LLM_MAX_TOKENS" in app_yaml
    assert "value: \"1200\"" in app_yaml
    assert "LLM_TEMPERATURE" in app_yaml
    assert "value: \"0.2\"" in app_yaml


def test_phase35_app_staging_defaults_to_agentic_databricks_runtime() -> None:
    env = os.environ.copy()
    for key in (
        "APP_CHATBOT_ENABLED",
        "APP_LLM_PROVIDER",
        "APP_RETRIEVER_BACKEND",
        "APP_WAREHOUSE_ID",
    ):
        env.pop(key, None)

    subprocess.run(
        [sys.executable, "databricks/scripts/stage_phase35_databricks_app.py"],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    app_yaml = _read(DATABRICKS_DIR / "build" / "chec_dash_parity" / "app.yaml")

    assert "CHATBOT_ENABLED" in app_yaml
    assert "value: \"true\"" in app_yaml
    assert "LLM_PROVIDER" in app_yaml
    assert "value: \"databricks_model_serving\"" in app_yaml
    assert "RETRIEVER_BACKEND" in app_yaml
    assert "value: \"databricks_ai_search\"" in app_yaml
    assert "LLM_PROVIDER\n    value: \"mock\"" not in app_yaml
    assert "CHATBOT_ENABLED\n    value: \"false\"" not in app_yaml


def test_phase35_app_staging_can_bind_gemini_secret_resource() -> None:
    env = os.environ.copy()
    env.update(
        {
            "APP_CHATBOT_ENABLED": "true",
            "APP_GEMINI_SECRET_RESOURCE_KEY": "gemini_api_key",
        }
    )
    subprocess.run(
        [sys.executable, "databricks/scripts/stage_phase35_databricks_app.py"],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    app_yaml = _read(DATABRICKS_DIR / "build" / "chec_dash_parity" / "app.yaml")

    assert "GEMINI_API_KEY" in app_yaml
    assert "valueFrom: \"gemini_api_key\"" in app_yaml


def test_phase35_app_staging_omits_gemini_secret_by_default() -> None:
    env = os.environ.copy()
    env.pop("APP_GEMINI_SECRET_RESOURCE_KEY", None)
    env.pop("APP_GEMINI_SECRET_SCOPE", None)
    env.pop("APP_GEMINI_SECRET_KEY", None)
    subprocess.run(
        [sys.executable, "databricks/scripts/stage_phase35_databricks_app.py"],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    app_yaml = _read(DATABRICKS_DIR / "build" / "chec_dash_parity" / "app.yaml")

    assert "GEMINI_API_KEY" not in app_yaml
