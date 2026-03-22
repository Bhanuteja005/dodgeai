from fastapi import APIRouter, HTTPException
from psycopg.errors import QueryCanceled, UndefinedTable

from app.db import DatabaseUnavailableError
from app.models import IngestRequest, IngestResponse
from app.services.ingestion_service import run_ingestion

router = APIRouter(prefix="/api/ingestion", tags=["ingestion"])


@router.post("/run", response_model=IngestResponse)
def run_ingestion_job(payload: IngestRequest):
    try:
        result = run_ingestion(reset_graph_tables=payload.reset_graph_tables)
    except DatabaseUnavailableError:
        raise HTTPException(status_code=503, detail="Database unavailable. Check Supabase credentials.")
    except UndefinedTable:
        raise HTTPException(status_code=500, detail="Database schema not initialized. Run backend/sql/schema.sql in Supabase.")
    except QueryCanceled:
        raise HTTPException(status_code=504, detail="Ingestion timed out while processing database operations.")

    return IngestResponse(**result)
