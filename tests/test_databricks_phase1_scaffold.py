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
    manifest = json.loads(_read(DATABRICKS_DIR / "manifests" / "phase1_assets.json"))

    assert manifest["bundle_name"] == "chec_phase1"
    assert manifest["catalog_name"] == "chec_dbx_demo"
    assert manifest["workspace_root_path"] == (
        "/Workspace/Users/${workspace.current_user.userName}/.bundle/chec_phase1/dev/files"
    )
    assert manifest["reference_notebook_folders"] == [
        "references/legacy_notebooks",
        "references/legacy_preprocessing",
    ]

    raw_sources = manifest["raw_sources"]
    assert len(raw_sources) == 17
    assert sum(1 for entry in raw_sources if entry["load_mode"] == "pickle") == 10
    assert sum(1 for entry in raw_sources if entry["load_mode"] == "copy_only") == 7

    bronze_tables = {
        entry["bronze_table"]
        for entry in raw_sources
        if entry.get("bronze_table")
    }
    assert bronze_tables == {
        "bronze_trafos",
        "bronze_apoyos",
        "bronze_switches",
        "bronze_redmt",
        "bronze_super_eventos",
        "bronze_eventos_interruptor",
        "bronze_eventos_tramo_linea",
        "bronze_eventos_transformador",
        "bronze_vegetacion",
        "bronze_rayos",
    }

    sensitive_files = manifest["sensitive_files"]
    assert sensitive_files == [
        {
            "relative_path": "OPENAI_API_Key.txt",
            "disposition": "exclude_from_sync",
            "reason": "move_to_secret_scope",
        }
    ]

    ml_artifacts = {entry["relative_path"] for entry in manifest["ml_artifacts"]}
    assert ml_artifacts == {"model.pth", "mask.npy"}

    gold_tables = {entry["table_name"] for entry in manifest["gold_tables"]}
    assert gold_tables == {
        "gold_saidi_saifi_daily",
        "gold_saidi_saifi_circuit_summary",
        "gold_probability_inputs",
        "gold_map_points",
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
    assert "dashboard_warehouse_id:" in bundle_text
    assert "4437a6195e05c59c" in bundle_text
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
        "../notebooks/05_stage_ml_assets.py",
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
        "stage_ml_assets",
    ]:
        assert f"task_key: {task_key}" in jobs_text


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
    assert "gold_map_line_segments" in build_gold_text
    assert "gold_map_filter_index" in build_gold_text
    assert "gold_map_event_days" in build_gold_text
    assert '.withColumn("map_period"' in build_gold_text
    assert '.withColumn("map_day"' in build_gold_text

    shared_text = _read(NOTEBOOK_DIR / "_shared_phase1.py")
    assert "def define_probability_widgets" in shared_text
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
    assert "CREATE VOLUME IF NOT EXISTS {volume_path(" not in bootstrap_text
    assert "phase1_manifest_json" in bootstrap_text
    assert "phase1_source_inventory" in bootstrap_text
    assert "phase1_table_registry" in bootstrap_text
    assert "phase1_artifact_inventory" in bootstrap_text

    bronze_text = _read(NOTEBOOK_DIR / "01_stage_bronze_tables.py")
    assert "AVAILABLE_IN_VOLUME" in bronze_text
    assert "Upload raw phase 1 assets to the source volume" in bronze_text
    assert "write_pandas_frame_to_delta(spark, normalized_frame, bronze_table_name)" in bronze_text

    validate_text = _read(NOTEBOOK_DIR / "02_validate_ingest.py")
    assert "observed_date_columns" in validate_text
    assert 'F.min(F.col(column)).alias(f"{column}_min")' in validate_text
    assert 'F.max(F.col(column)).alias(f"{column}_max")' in validate_text
    assert '"Combined date bounds across "' in validate_text

    preflight_script = _read(DATABRICKS_DIR / "scripts" / "preflight_phase1_deploy.sh")
    assert "run_with_retries()" in preflight_script
    assert "extract_json_payload()" in preflight_script
    assert "databricks metastores current -o json" in preflight_script
    assert "databricks clusters list-node-types -o json" in preflight_script
    assert 'az vm list-usage -l "${REGION}" -o json' in preflight_script
    assert 'Standard_DC4as_v5' in preflight_script
    assert 'Standard_L4aos_v4' in preflight_script
    assert 'Standard_D4as_v5' in preflight_script
    assert 'Target catalog: ${CATALOG_NAME}' in preflight_script

    upload_script = _read(DATABRICKS_DIR / "scripts" / "upload_phase1_assets.sh")
    assert "run_with_retries()" in upload_script
    assert "extract_json_payload()" in upload_script
    assert "OPENAI_API_Key.txt" not in upload_script
    assert "databricks fs cp" in upload_script
    assert "databricks fs ls" in upload_script
    assert "Skipping ${relative_path}; already uploaded" in upload_script
    assert "TRAFOS.pkl" in upload_script
    assert "model.pth" in upload_script
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
    assert "APP_CHATBOT_CORPUS_VOLUME_RESOURCE_KEY" in deploy_app_script
    assert "APP_GEMINI_SECRET_RESOURCE_KEY" in deploy_app_script
    assert "APP_GEMINI_SECRET_SCOPE" in deploy_app_script
    assert "APP_GEMINI_SECRET_KEY" in deploy_app_script
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
    assert "databricks grants update catalog" in app_permissions_script
    assert "databricks grants update schema" in app_permissions_script
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
    assert "Tendencia mensual de SAIDI" in dashboard_text
    assert "Date Range" not in dashboard_text
    assert "Event Family" not in dashboard_text
    assert "Total Events" not in dashboard_text
    assert "Affected Users" not in dashboard_text
    assert "filter-date-range-picker" in dashboard_text
    assert '"widgetType": "counter"' in dashboard_text
    assert '"widgetType": "bar"' in dashboard_text
    assert "sum(saidi_total)" in dashboard_text
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


def test_phase35_app_staging_uses_chatbot_volume_resource() -> None:
    env = os.environ.copy()
    env.update(
        {
            "APP_CHATBOT_ENABLED": "true",
            "APP_CHATBOT_CORPUS_VOLUME_RESOURCE_KEY": "chatbot_corpus_volume",
            "APP_CHATBOT_CORPUS_SUBDIR": "chatbot_corpus",
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
    assert not (build_root / "data" / "chatbot_corpus").exists()


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
