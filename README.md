# Graph-Based Data Modeling and Query System

This project ingests Order-to-Cash data, builds a relationship graph, visualizes it, and supports natural-language querying with data-backed answers.

## What Is Implemented

- Graph ingestion from JSONL SAP O2C datasets in `backend/sap-o2c-data`.
- Node and edge modeling in PostgreSQL (`o2c_entity_records`, `graph_edges`).
- Interactive graph UI with node expansion and metadata panel.
- Chat interface connected to backend query services.
- Chat-to-graph mapping: assistant responses can focus and expand related graph nodes.
- Persistent chat history in PostgreSQL (`chat_history`) with question, answer, status, strategy, and mapped node IDs.
- Guardrails for off-topic and unsafe SQL.
- Quota-safe fallback responses when Gemini is unavailable.

## Architecture

![Architectre](architecture.png)

1. Ingestion
- Service: `backend/app/services/ingestion_service.py`
- Reads JSONL files per entity.
- Builds stable external IDs.
- Upserts records into `o2c_entity_records`.
- Applies relationship rules from `schema_profile.py` and writes edges to `graph_edges`.

2. Graph API
- Router: `backend/app/routers/graph.py`
- Service: `backend/app/services/graph_service.py`
- `GET /api/graph`: returns graph snapshot.
- `GET /api/graph/node/{node_id}`: returns node details + neighbors + edges.

3. Chat API
- Router: `backend/app/routers/chat.py`
- Tries NL->SQL via Gemini (`gemini_service.py`).
- Enforces read-only SQL guardrails (`sql_guardrails.py`).
- Executes SQL through `query_service.py`.
- Summarizes result via Gemini, or deterministic fallback.
- Deterministic fallback includes the assignment's required example queries:
	- products with highest billing-document associations,
	- full billing flow trace (Sales Order -> Delivery -> Billing -> Journal Entry),
	- incomplete/broken sales-order flow detection.
- Returns `graph_node_ids` to map answer entities into graph focus actions.
- Persists each chat exchange to `chat_history` for auditability and user review.

4. Frontend
- Framework: Next.js + React.
- Main UI: `frontend/src/components/marketing/dashboard.tsx`.
- Graph rendering: `react-force-graph-2d`.
- Chat pane + mapped node actions (`Show in graph`).

## Tech Stack

- Backend: FastAPI, Pydantic, psycopg, psycopg_pool
- Database: PostgreSQL
- Frontend: Next.js (App Router), React, Tailwind CSS
- Graph Viz: react-force-graph-2d
- LLM: Google Gemini API (with fallback path)

## AI Tools Used

- GitHub Copilot
- Claude

## Runbook

Backend:
1. Configure `backend/.env`.
2. Start PostgreSQL.
3. Apply schema: `backend/sql/schema.sql`.
4. Run API: `python backend/run.py`.
5. Ingest data: `POST /api/ingestion/run` with `{ "reset_graph_tables": true }`.

Frontend:
1. Configure `frontend/.env.local` with backend URL.
2. Run frontend dev server.
3. Open `/dashboard`.

## Architecture Decisions

- **PostgreSQL over graph DB**: Chose PostgreSQL for reliability and 
  SQL query generation compatibility with Gemini. Graph edges are 
  modeled as a relational edge table rather than a native graph DB.

- **Two-step LLM pattern**: Gemini first generates SQL, query executes 
  against PostgreSQL, results sent back to Gemini for natural language 
  summarization. This grounds all answers in real data.

- **Deterministic fallback**: When Gemini quota is exhausted, hardcoded 
  query logic handles the 3 required example queries ensuring the system 
  never fails silently.

- **Guardrails**: Off-topic detection happens before SQL generation. 
  Read-only SQL enforcement happens before execution. Two separate 
  layers of protection.

## Requirement Checklist

### Functional Requirements

1. Graph Construction: COMPLETED
- Nodes and edges are built from dataset entities and relationship rules.

2. Graph Visualization: COMPLETED
- Supports node click/expand, metadata inspection, and visible relationships.

3. Conversational Query Interface: COMPLETED
- NL query input, dataset-grounded answer output, backend query execution.

4. Example Query Coverage: COMPLETED
- Which products are associated with the highest number of billing documents?: COMPLETED
- Trace the full flow of a given billing document (Sales Order -> Delivery -> Billing -> Journal Entry): COMPLETED
- Identify sales orders with broken/incomplete flows (delivered not billed, billed without delivery): COMPLETED

5. Guardrails: COMPLETED
- Off-topic responses blocked.
- Unsafe SQL patterns blocked.
- Responses are derived from dataset queries.

### Optional Extensions

- NL to SQL translation: COMPLETED
- Highlight nodes referenced in responses: COMPLETED
- Graph mapping from chat answer to graph focus: COMPLETED
- Streaming responses: NOT IMPLEMENTED
- Conversation memory: PARTIAL (chat exchange persistence via `chat_history`)
- Advanced graph clustering: COMPLETED (`GET /api/graph/clusters`, dashboard cluster mode)

### Submission-Oriented Items

- Architecture and prompting explanation: COMPLETED (this README + backend docs)
- Working demo link: PENDING (deployment step)
- Public repository link: PENDING
- AI session logs packaging: PENDING

