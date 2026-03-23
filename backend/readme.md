# Backend Overview (simple)

This backend handles dataset ingestion, graph storage, query translation, and chat support.

## What it does

1. Reads source data from JSONL files under `backend/sap-o2c-data`.
2. Stores records in PostgreSQL table `o2c_entity_records`.
3. Builds graph relationships in `graph_edges` (links between orders, deliveries, invoices, payments, customers, products, etc.).
4. Exposes REST APIs used by frontend:
   - `GET /api/graph` — graph node and edge snapshot
   - `GET /api/graph/node/{id}` — node detail and neighbors
   - `GET /api/graph/clusters` — compute connected clusters
   - `POST /api/chat` — handle natural language query + data-backed response
   - `POST /api/ingestion/run` — refresh graph from source files
5. Persists chat logs in `chat_history` (message, answer, status, strategy, mapped node IDs).

## Chat pipeline (simple)

- Incoming message -> off-topic guardrail check
- If domain-relevant, convert to SQL using Gemini (LLM) with read-only guardrails
- If Gemini is unavailable or not confident, use built-in deterministic queries for required examples
- Execute SQL in Postgres, format the results in plain English
- Return chat answer plus matching `graph_node_ids` for UI focus

## Safety and limits

- Only SELECT queries allowed via `sql_guardrails.py`.
- Off-topic or unsafe queries receive a polite domain-limited response.
- Errors are handled and logged in chat history.

## How to run

1. Start PostgreSQL (local development) or use hosted DB.
2. Apply schema: `backend/sql/schema.sql`.
3. Install dependencies in `backend` and run `python run.py`.
4. Use `POST /api/ingestion/run` to ingest data.

## Deployed endpoints

- Frontend: https://dodgeai-one.vercel.app
- Backend: https://dodgeai-production.up.railway.app

---

This file focuses on backend components and is intentionally brief for easy reading.
