"""
FastAPI application entrypoint.

Serves:
  - REST API under /api/v1/*  (see app/api/routes/documents.py)
  - Interactive API docs at /docs (Swagger UI) and /redoc
  - The static HTML/CSS/JS dashboard frontend at /
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes.documents import router as documents_router
from app.core.config import get_settings
from app.core.database import init_db
from app.core.exceptions import AppError, app_error_handler, unhandled_exception_handler
from app.core.logging import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)
settings = get_settings()

@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("Starting %s in %s environment", settings.APP_NAME, settings.ENVIRONMENT)
    os.makedirs(settings.UPLOAD_TMP_DIR, exist_ok=True)
    init_db()
    logger.info("Database initialised.")
    yield


app = FastAPI(
    title=settings.APP_NAME,
    description="Intelligent Document Extraction, Validation & API Platform",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

app.include_router(documents_router, prefix=settings.API_V1_PREFIX)


# --- Static frontend -------------------------------------------------------
_FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
_FRONTEND_DIR = os.path.abspath(_FRONTEND_DIR)

if os.path.isdir(_FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=os.path.join(_FRONTEND_DIR, "static")), name="static")

    from fastapi.responses import FileResponse

    @app.get("/", include_in_schema=False)
    def serve_frontend():
        return FileResponse(os.path.join(_FRONTEND_DIR, "templates", "index.html"))

    @app.get("/status", include_in_schema=False)
    def serve_status_page():
        """Serve a browser-friendly view of the JSON health endpoint."""
        return FileResponse(os.path.join(_FRONTEND_DIR, "templates", "status.html"))
