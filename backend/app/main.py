from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers.chat import router as chat_router
from app.routers.graph import router as graph_router
from app.routers.health import router as health_router
from app.routers.ingestion import router as ingestion_router

app = FastAPI(title="Order-to-Cash Graph API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.allowed_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(graph_router)
app.include_router(chat_router)
app.include_router(ingestion_router)
