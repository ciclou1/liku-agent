import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app
from redis import asyncio as redis_asyncio
from sqlalchemy import text

from app.api.routes import router
from app.api.erp_routes import router as erp_router
from app.core.storage.paths import StoragePaths
from app.core.database_init import initialize_database
from app.exceptions import BusinessError
from app.core.config import get_settings
from app.monitoring.metrics import ACTIVE_REQUESTS, REQUEST_COUNT, REQUEST_LATENCY, configure_metrics, set_database_ready, set_redis_ready

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    StoragePaths().ensure()
    try:
        await initialize_database()
        set_database_ready("primary", True)
    except Exception:
        set_database_ready("primary", False)
        raise
    if get_settings().app_env == "test":
        set_redis_ready("broker", True)
    else:
        redis_client = redis_asyncio.from_url(get_settings().redis_url, socket_connect_timeout=2, socket_timeout=2)
        try:
            await redis_client.ping()
            set_redis_ready("broker", True)
        except Exception:
            set_redis_ready("broker", False)
        finally:
            await redis_client.aclose()
    yield


app = FastAPI(title="平衡利库智能体 API", version="0.1.0", lifespan=lifespan)
configure_metrics(get_settings().app_env, app.version)
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins.split(","), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        started = time.perf_counter()
        ACTIVE_REQUESTS.inc()
        try:
            response = await call_next(request)
            status_code = str(response.status_code)
            return response
        except Exception:
            status_code = "500"
            raise
        finally:
            path = request.url.path
            REQUEST_COUNT.labels(request.method, path, status_code).inc()
            REQUEST_LATENCY.labels(request.method, path).observe(time.perf_counter() - started)
            ACTIVE_REQUESTS.dec()


app.add_middleware(MetricsMiddleware)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        # 嵌入积木 ERP 需允许其 iframe 嵌入；未配置嵌入来源时保持 DENY
        frame_ancestors = get_settings().frame_ancestors
        if frame_ancestors:
            response.headers["Content-Security-Policy"] = f"frame-ancestors {frame_ancestors}"
        else:
            response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        return response


app.add_middleware(SecurityHeadersMiddleware)


@app.exception_handler(BusinessError)
async def business_error_handler(_: Request, exc: BusinessError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"code": exc.code, "message": exc.message})


app.include_router(router)
app.include_router(erp_router)
app.mount("/metrics", make_asgi_app())
