# O2C Graph Backend Setup (FastAPI + Local PostgreSQL + Gemini)

## Setup

1. Create env file:
   - copy `.env.example` to `.env`
2. Keep dataset in backend folder:
   - Use `backend/sap-o2c-data` (do not move dataset to frontend)
3. Start local PostgreSQL (recommended):
   - `docker compose up -d postgres`
   - In `.env`, set `SUPABASE_DB_URL=postgresql://postgres:postgres@127.0.0.1:5432/o2c_graph`
4. Alternative (no Docker, user-level Postgres on port 55432):
   - `"C:\Program Files\PostgreSQL\18\bin\initdb.exe" -D .local-pgdata -A trust -U postgres`
   - `"C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe" -D .local-pgdata -l .local-postgres.log -o " -p 55432" start`
   - `"C:\Program Files\PostgreSQL\18\bin\createdb.exe" -h 127.0.0.1 -p 55432 -U postgres o2c_graph`
   - `"C:\Program Files\PostgreSQL\18\bin\psql.exe" -h 127.0.0.1 -p 55432 -U postgres -d o2c_graph -f sql/schema.sql`
   - In `.env`, set `SUPABASE_DB_URL=postgresql://postgres@127.0.0.1:55432/o2c_graph`
5. Install dependencies:
   - `pip install -r requirements.txt`
6. Apply database schema:
   - If using Docker compose above, schema is auto-applied from `sql/schema.sql`.
   - Otherwise run `sql/schema.sql` manually on your target PostgreSQL database.
7. Start server:
   - `python run.py`
8. Ingest data:
   - `POST /api/ingestion/run` with body `{"reset_graph_tables": true}`

## API Endpoints

- `GET /api/health`
- `POST /api/ingestion/run`
- `GET /api/graph`
- `GET /api/graph/node/{node_id}`
- `POST /api/chat`

## Guardrails

- SQL generation uses a strict system prompt and off-topic fallback.
- Only a single `SELECT` / `WITH ... SELECT` statement is accepted.
- Non-read SQL keywords are blocked.
- User-facing responses never expose SQL.

## Important

The relationship profile in app/services/schema_profile.py now follows the confirmed key and link fields. If source files change, update this profile first.
