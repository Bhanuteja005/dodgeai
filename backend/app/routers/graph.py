from fastapi import APIRouter, HTTPException, Query
from psycopg.errors import QueryCanceled, UndefinedTable

from app.db import DatabaseUnavailableError
from app.services.graph_clustering_service import fetch_graph_clusters
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


@router.get("/clusters")
def get_clusters(
    limit: int = Query(default=1200, ge=100, le=5000),
    min_cluster_size: int = Query(default=4, ge=2, le=100),
    max_clusters: int = Query(default=25, ge=1, le=200),
):
    try:
        return fetch_graph_clusters(
            limit=limit,
            min_cluster_size=min_cluster_size,
            max_clusters=max_clusters,
        )
    except DatabaseUnavailableError:
        raise HTTPException(status_code=503, detail="Database unavailable. Check Supabase credentials.")
    except UndefinedTable:
        raise HTTPException(status_code=500, detail="Database schema not initialized. Run backend/sql/schema.sql in Supabase.")
    except QueryCanceled:
        raise HTTPException(status_code=504, detail="Database query timed out while reading cluster data.")
