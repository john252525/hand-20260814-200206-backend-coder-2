import time
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text, select
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.exceptions import (
    AppError,
    ConflictError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)
from app.core.logging_config import setup_logging
from app.core.middleware import auth_middleware
from app.models import TenderSource

setup_logging()

app = FastAPI(
    title="Tender Pipeline API",
    version="1.0.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
    redoc_url="/redoc",
)

_START_TIME = time.time()

if settings.app_env == "development":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

ERROR_STATUS_MAP = {
    NotFoundError: 404,
    ConflictError: 409,
    UnauthorizedError: 401,
    ValidationError: 422,
}

@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    status = ERROR_STATUS_MAP.get(type(exc), 400)
    return JSONResponse(
        status_code=status,
        content={"success": False, "error": {"code": exc.code, "message": exc.message, "details": exc.details}},
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    detail = exc.detail
    if isinstance(detail, dict):
        code = detail.get("code", "HTTP_ERROR")
        message = detail.get("message", str(detail))
        details = detail.get("details")
    else:
        code = "HTTP_ERROR"
        message = str(detail)
        details = None
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "error": {"code": code, "message": message, "details": details}},
    )

app.middleware("http")(auth_middleware)
app.include_router(api_router, prefix="/api/v1")

async def check_database():
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
        return "healthy"
    except Exception:
        return "unhealthy"

async def check_redis():
    import redis.asyncio as aioredis
    try:
        r = aioredis.from_url(settings.redis_url, socket_connect_timeout=2)
        await r.ping()
        await r.aclose()
        return "healthy"
    except Exception:
        return "unhealthy"

async def check_tender_source():
    """Проверяем наличие хотя бы одного активного источника тендеров."""
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(TenderSource).where(TenderSource.is_active == True).limit(1)
            )
            return "healthy" if result.scalar_one_or_none() else "not_configured"
    except Exception:
        return "unhealthy"

@app.get("/api/v1/health", tags=["system"])
async def health():
    db_status = await check_database()
    redis_status = await check_redis()
    llm_status = "healthy" if settings.llm_api_key else "not_configured"
    source_status = await check_tender_source()
    overall = "healthy" if db_status == "healthy" and redis_status == "healthy" else "degraded"
    return {
        "success": True,
        "data": {
            "status": overall,
            "version": app.version,
            "uptime_seconds": int(time.time() - _START_TIME),
            "components": {
                "database": db_status,
                "redis": redis_status,
                "llm_api": llm_status,
                "tender_source_api": source_status,
            },
        },
    }

@app.get("/", tags=["system"])
async def root():
    return {"success": True, "data": {"message": "Tender Pipeline API is running"}}