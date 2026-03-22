from typing import Any, Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str


class GraphNode(BaseModel):
    id: str
    type: str
    label: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    source: str
    target: str
    source_type: str
    target_type: str
    relationship_label: str


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class ChatRequest(BaseModel):
    message: str = Field(min_length=2)


class ChatResponse(BaseModel):
    answer: str
    status: Literal["ok", "offtopic", "error"]


class IngestRequest(BaseModel):
    reset_graph_tables: bool = False


class IngestResponse(BaseModel):
    status: str
    entities_loaded: int
    nodes_loaded: int
    edges_loaded: int
    notes: list[str]
