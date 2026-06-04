#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import shutil


APP_NAME = "chec_dash_parity"

IGNORE_PATTERNS = shutil.ignore_patterns(
    "__pycache__",
    "*.pyc",
    "*.pyo",
    ".pytest_cache",
)


def _render_app_yaml(template_text: str) -> str:
    gemini_secret_resource_key = os.getenv("APP_GEMINI_SECRET_RESOURCE_KEY", "").strip()
    if gemini_secret_resource_key:
        gemini_api_key_env = (
            "  - name: GEMINI_API_KEY\n"
            f"    valueFrom: \"{gemini_secret_resource_key}\""
        )
    else:
        gemini_api_key_env = "  - name: GEMINI_API_KEY\n    value: \"\""

    replacements = {
        "__WAREHOUSE_ID__": os.getenv("APP_WAREHOUSE_ID", "4437a6195e05c59c"),
        "__CATALOG_NAME__": os.getenv("APP_CATALOG_NAME", "chec_dbx_demo"),
        "__GOLD_SCHEMA__": os.getenv("APP_GOLD_SCHEMA", "gold"),
        "__SILVER_SCHEMA__": os.getenv("APP_SILVER_SCHEMA", "silver"),
        "__LLM_PROVIDER__": os.getenv("APP_LLM_PROVIDER", "mock"),
        "__LLM_ENDPOINT_RESOURCE_KEY__": os.getenv("APP_LLM_ENDPOINT_RESOURCE_KEY", "chatbot_llm_endpoint"),
        "__LLM_MAX_TOKENS__": os.getenv("APP_LLM_MAX_TOKENS", "1200"),
        "__LLM_TEMPERATURE__": os.getenv("APP_LLM_TEMPERATURE", "0.2"),
        "__CHATBOT_ENABLED__": os.getenv("APP_CHATBOT_ENABLED", "false"),
        "__CHATBOT_CORPUS_VOLUME_RESOURCE_KEY__": os.getenv(
            "APP_CHATBOT_CORPUS_VOLUME_RESOURCE_KEY",
            "chatbot_corpus_volume",
        ),
        "__CHATBOT_CORPUS_SUBDIR__": os.getenv("APP_CHATBOT_CORPUS_SUBDIR", "chatbot_corpus"),
        "__CHATBOT_SKILLS_VOLUME_RESOURCE_KEY__": os.getenv(
            "APP_CHATBOT_SKILLS_VOLUME_RESOURCE_KEY",
            "chatbot_skills_volume",
        ),
        "__CHATBOT_SKILLS_SUBDIR__": os.getenv("APP_CHATBOT_SKILLS_SUBDIR", "active"),
        "__CHATBOT_RETRIEVAL_TOP_K__": os.getenv("APP_CHATBOT_RETRIEVAL_TOP_K", "5"),
        "__CHATBOT_MAX_CONTEXT_CHARS__": os.getenv("APP_CHATBOT_MAX_CONTEXT_CHARS", "12000"),
        "__SUMMARY_INTERPRETABILITY_ENABLED__": os.getenv("APP_SUMMARY_INTERPRETABILITY_ENABLED", "true"),
        "__SUMMARY_INTERPRETABILITY_MAX_POINTS__": os.getenv("APP_SUMMARY_INTERPRETABILITY_MAX_POINTS", "5"),
        "__SUMMARY_INTERPRETABILITY_HIGH_ROBUST_Z__": os.getenv("APP_SUMMARY_INTERPRETABILITY_HIGH_ROBUST_Z", "3.0"),
        "__SUMMARY_INTERPRETABILITY_LOW_ROBUST_Z__": os.getenv("APP_SUMMARY_INTERPRETABILITY_LOW_ROBUST_Z", "-2.5"),
        "__SUMMARY_INTERPRETABILITY_DELTA_ROBUST_Z__": os.getenv("APP_SUMMARY_INTERPRETABILITY_DELTA_ROBUST_Z", "3.0"),
        "__SUMMARY_INTERPRETABILITY_TOP_CONTRIBUTOR_PCT__": os.getenv(
            "APP_SUMMARY_INTERPRETABILITY_TOP_CONTRIBUTOR_PCT",
            "0.10",
        ),
        "__SUMMARY_INTERPRETABILITY_SUSTAINED_MIN_DAYS__": os.getenv(
            "APP_SUMMARY_INTERPRETABILITY_SUSTAINED_MIN_DAYS",
            "3",
        ),
        "__SUMMARY_INTERPRETABILITY_INCLUDE_AGENT_TEXT_DEFAULT__": os.getenv(
            "APP_SUMMARY_INTERPRETABILITY_INCLUDE_AGENT_TEXT_DEFAULT",
            "true",
        ),
        "__SUMMARY_INTERPRETABILITY_CACHE_SECONDS__": os.getenv(
            "APP_SUMMARY_INTERPRETABILITY_CACHE_SECONDS",
            "300",
        ),
        "__CHATBOT_CONVERSATION_BACKEND__": os.getenv("APP_CHATBOT_CONVERSATION_BACKEND", "memory"),
        "__CHATBOT_CONVERSATION_SCHEMA__": os.getenv("APP_CHATBOT_CONVERSATION_SCHEMA", "agent"),
        "__CHATBOT_CONTEXT_TOOLS_SCHEMA__": os.getenv("APP_CHATBOT_CONTEXT_TOOLS_SCHEMA", "agent_tools"),
        "__CHATBOT_MEMORY_MAX_TURNS__": os.getenv("APP_CHATBOT_MEMORY_MAX_TURNS", "8"),
        "__CHATBOT_OBSERVABILITY_ENABLED__": os.getenv("APP_CHATBOT_OBSERVABILITY_ENABLED", "false"),
        "__CHATBOT_TELEMETRY_SCHEMA__": os.getenv("APP_CHATBOT_TELEMETRY_SCHEMA", "agent_observability"),
        "__CHATBOT_EVAL_REPORT_ONLY__": os.getenv("APP_CHATBOT_EVAL_REPORT_ONLY", "true"),
        "__CHATBOT_EVAL_LLM_JUDGES_ENABLED__": os.getenv("APP_CHATBOT_EVAL_LLM_JUDGES_ENABLED", "false"),
        "__CHATBOT_EVAL_ENFORCE__": os.getenv("APP_CHATBOT_EVAL_ENFORCE", "false"),
        "__MLFLOW_TRACKING_URI__": os.getenv("APP_MLFLOW_TRACKING_URI", "databricks"),
        "__MLFLOW_EXPERIMENT_NAME__": os.getenv(
            "APP_MLFLOW_EXPERIMENT_NAME",
            "/Shared/chec_dash_parity/agent_observability",
        ),
        "__MLFLOW_PROMPT_NAME__": os.getenv("APP_MLFLOW_PROMPT_NAME", "chec_chatbot_answer_prompt"),
        "__MLFLOW_PROMPT_ALIAS__": os.getenv("APP_MLFLOW_PROMPT_ALIAS", "production"),
        "__RETRIEVER_BACKEND__": os.getenv("APP_RETRIEVER_BACKEND", "local_jsonl"),
        "__AI_SEARCH_ENDPOINT_NAME__": os.getenv("APP_AI_SEARCH_ENDPOINT_NAME", "chec-agent-search"),
        "__AI_SEARCH_INDEX_RESOURCE_KEY__": os.getenv(
            "APP_AI_SEARCH_INDEX_RESOURCE_KEY",
            "chatbot_ai_search_index",
        ),
        "__AI_SEARCH_TOP_K__": os.getenv("APP_AI_SEARCH_TOP_K", "8"),
        "__AI_SEARCH_QUERY_TYPE__": os.getenv("APP_AI_SEARCH_QUERY_TYPE", "hybrid"),
        "__AI_SEARCH_EMBEDDING_ENDPOINT_NAME__": os.getenv(
            "APP_AI_SEARCH_EMBEDDING_ENDPOINT_NAME",
            "databricks-qwen3-embedding-0-6b",
        ),
        "__AI_SEARCH_ENDPOINT_TYPE__": os.getenv("APP_AI_SEARCH_ENDPOINT_TYPE", "STANDARD"),
        "__GEMINI_MODEL__": os.getenv("APP_GEMINI_MODEL", "gemini-2.5-flash"),
        "__GEMINI_API_KEY_ENV__": gemini_api_key_env,
    }
    rendered = template_text
    for placeholder, value in replacements.items():
        rendered = rendered.replace(placeholder, value)
    return rendered


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    databricks_root = repo_root / "databricks"
    template_root = databricks_root / "apps" / APP_NAME
    build_root = databricks_root / "build" / APP_NAME

    if build_root.exists():
        shutil.rmtree(build_root)
    build_root.mkdir(parents=True, exist_ok=True)

    requirements_template = template_root / "requirements.txt"
    shutil.copy2(
        requirements_template if requirements_template.exists() else repo_root / "requirements.txt",
        build_root / "requirements.txt",
    )
    shutil.copy2(repo_root / "run_dash.py", build_root / "run_dash.py")
    shutil.copytree(repo_root / "src", build_root / "src", ignore=IGNORE_PATTERNS)

    shutil.copy2(
        template_root / "databricks_app_wsgi.py",
        build_root / "databricks_app_wsgi.py",
    )

    app_yaml_text = (template_root / "app.yaml").read_text(encoding="utf-8")
    (build_root / "app.yaml").write_text(_render_app_yaml(app_yaml_text), encoding="utf-8")
    (build_root / "README.md").write_text(
        "Generated by stage_phase35_databricks_app.py from the CHEC dashboard repo.\n",
        encoding="utf-8",
    )

    print(f"Staged Databricks app source at {build_root}")


if __name__ == "__main__":
    main()
