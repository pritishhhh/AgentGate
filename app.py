"""Vercel discovers this FastAPI instance; the persistent backend uses agentgate serve."""

from src.agentgate.vercel_app import create_frontend

app = create_frontend()
