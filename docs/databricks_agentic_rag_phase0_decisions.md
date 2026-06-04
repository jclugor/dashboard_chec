# Databricks Agentic RAG Phase 0 Decisions

This record locks the first demo defaults for the CHEC bounded agentic RAG assistant. It is a lightweight implementation decision record, not a client sign-off workflow.

## Demo Defaults

- Runtime: Databricks Apps remains the application runtime.
- Authorization: Databricks Apps app authorization is the demo default; users act through the app service principal permissions.
- Assistant mode: read-only. The assistant may retrieve and explain approved dashboard/document context, but it may not write business data or execute write actions.
- Agent pattern: bounded agentic RAG. The assistant may route between guided analysis, context packaging, retrieval, prompt assembly, and model generation, but tool access remains fixed by production code.
- Compliance language: responses must use evidence flags, missing-data language, and possible-risk wording. They must not state legal conclusions or definitive compliance outcomes.
- Skills: governed Markdown/YAML skill files are the future client control surface. Skills may tune instructions and output behavior, but may not add tools, credentials, SQL, Python, endpoints, permissions, or write actions.
- LLM configuration: provider-neutral configuration starts with `LLM_PROVIDER=mock`. Gemini is retained only as an optional prototype provider through `LLM_PROVIDER=gemini`; it is not the production default.

## Phase 1 Boundaries

- Keep the existing guided assistant UI and current chatbot routes compatible.
- Keep local JSONL retrieval as the active retrieval backend.
- Do not add Databricks AI Search, Delta conversation memory, MLflow trace persistence, arbitrary SQL generation, write-capable tools, or free-form chat UI in this phase.
- Unit tests must run without Databricks credentials or external LLM credentials.
