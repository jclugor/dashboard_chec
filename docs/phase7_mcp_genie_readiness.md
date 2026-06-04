# Phase 7 MCP and Genie Readiness

Phase 7 keeps runtime orchestration inside the CHEC app. The deployed chatbot uses a deterministic allowlisted router, existing Unity Catalog function contracts, Databricks AI Search retrieval, and Databricks Model Serving. Runtime MCP and Genie are intentionally not enabled in this phase.

## Why MCP and Genie Stay Out of Runtime

- Phase 7 needs a narrow governance boundary: only read-only context functions, local fallbacks, and the configured AI Search index can run.
- The app already has curated Phase 4 Unity Catalog functions for deterministic dashboard, reliability, compliance, event, asset, and circuit-history context.
- The app already has a Phase 5 AI Search index for bounded document retrieval, so document search does not need dynamic MCP discovery yet.
- Genie requires a curated Genie Space, service-principal access, warehouse permissions, polling, result-shape validation, and acceptance tests before client-facing runtime use.
- The general Databricks SQL MCP server is deferred because it is broader than this app needs and can be read/write. Phase 7 does not expose broad SQL, arbitrary SQL, user-provided table names, or write-capable tools.

## Recommended Future MCP Servers

- AI Search managed MCP server for document retrieval against the governed CHEC technical index.
- Unity Catalog functions managed MCP server for the existing `chec_dbx_demo.agent_tools` functions.
- Genie Space managed MCP server only after a CHEC-specific Genie Space is curated and tested.

Do not enable the general Databricks SQL MCP server for the first client-facing release. If SQL MCP is ever considered, it should be isolated to internal engineering workflows with separate permissions and tests.

## Genie Prerequisites

- Curate a CHEC Genie Space with only approved gold tables and documented semantic instructions.
- Grant the app service principal access to the Genie Space and the backing SQL warehouse.
- Define bounded questions the chatbot may delegate to Genie.
- Implement async polling with timeouts, exponential backoff, and user-visible non-fatal errors.
- Persist Genie `conversation_id`, `message_id`, generated SQL metadata, and result citations.
- Add acceptance tests for successful answers, no-result answers, pending/timeout states, malformed responses, permission failures, and follow-up context handling.

## References

- Databricks managed MCP servers: https://docs.databricks.com/aws/en/generative-ai/mcp/managed-mcp
- Databricks structured data tools and Genie Spaces: https://docs.databricks.com/aws/en/generative-ai/agent-framework/structured-retrieval-tools
- Genie Conversation API: https://docs.databricks.com/gcp/en/genie/conversation-api
