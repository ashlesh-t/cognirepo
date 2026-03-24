"""
CogniRepo FastAPI application.

Run with:
    uvicorn api.main:app --reload

All routes except /login require a Bearer JWT obtained from POST /login.
"""
from fastapi import FastAPI

from api.auth import router as auth_router
from api.middleware import JWTMiddleware
from api.routes.episodic import router as episodic_router
from api.routes.memory import router as memory_router

app = FastAPI(
    title="CogniRepo API",
    description="REST adapter over the CogniRepo tools layer (FAISS semantic memory + episodic log + docs search).",
    version="0.1.0",
)

app.add_middleware(JWTMiddleware)

app.include_router(auth_router)
app.include_router(memory_router)
app.include_router(episodic_router)
