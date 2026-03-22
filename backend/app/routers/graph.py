from fastapi import APIRouter, HTTPException, Query
from psycopg.errors import QueryCanceled, UndefinedTable

from app.db import DatabaseUnavailableError
from app.services.graph_service import fetch_graph, fetch_node_details

router = APIRouter(prefix="/api/graph", tags=["graph"])


@router.get("")
def get_graph(limit: int = Query(default=800, ge=10, le=5000)):
    try:
        return fetch_graph(limit=limit)
    except DatabaseUnavailableError:
        raise HTTPException(status_code=503, detail="Database unavailable. Check Supabase credentials.")
    except UndefinedTable:
        raise HTTPException(status_code=500, detail="Database schema not initialized. Run backend/sql/schema.sql in Supabase.")
    except QueryCanceled:
        raise HTTPException(status_code=504, detail="Database query timed out while reading graph data.")


@router.get("/node/{node_id}")
def get_node(node_id: str):
    try:
        details = fetch_node_details(node_id=node_id)
    except DatabaseUnavailableError:
        raise HTTPException(status_code=503, detail="Database unavailable. Check Supabase credentials.")
    except UndefinedTable:
        raise HTTPException(status_code=500, detail="Database schema not initialized. Run backend/sql/schema.sql in Supabase.")
    except QueryCanceled:
        raise HTTPException(status_code=504, detail="Database query timed out while reading node data.")

    if not details:
        raise HTTPException(status_code=404, detail="Node not found")
    return details
