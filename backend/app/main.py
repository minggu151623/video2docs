import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, FileResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.storage import uid
from app.db.session import create_db, migrate
from app.api.routes import router


def create_app(settings=None):
    settings = settings or get_settings()
    engine, Session = create_db(settings)

    @asynccontextmanager
    async def lifespan(app):
        os.umask(0o077)
        migrate(settings)
        yield
        engine.dispose()

    app = FastAPI(title="Video2docs", version="0.1.0", lifespan=lifespan, docs_url="/api/docs")
    app.state.settings, app.state.Session = settings, Session
    app.state.session_token = secrets.token_urlsafe(32)
    app.state.csrf_token = secrets.token_urlsafe(32)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"])

    def error_response(exc, request_id):
        return JSONResponse(
            {
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "retryable": exc.retryable,
                    "request_id": request_id,
                    "details": exc.details,
                }
            },
            status_code=exc.status,
        )

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        request_id = uid()
        origin = request.headers.get("origin")
        try:
            if origin and origin not in settings.origins:
                raise AppError("ORIGIN_FORBIDDEN", "Origin không được phép.", 403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                raise AppError("ORIGIN_FORBIDDEN", "Không chấp nhận truy cập cross-site.", 403)
            if request.url.path.startswith("/api/v1") and request.url.path not in (
                "/api/v1/health",
                "/api/v1/session",
            ):
                if not secrets.compare_digest(
                    request.cookies.get("v2d_session", ""), app.state.session_token
                ):
                    raise AppError("SESSION_REQUIRED", "Tải lại giao diện local để mở phiên.", 401)
                if request.method not in ("GET", "HEAD", "OPTIONS"):
                    if not origin or not secrets.compare_digest(
                        request.headers.get("x-csrf-token", ""), app.state.csrf_token
                    ):
                        raise AppError("CSRF_REQUIRED", "CSRF token hoặc Origin không hợp lệ.", 403)
            if request.method == "OPTIONS":
                response = JSONResponse({})
                response.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
                response.headers["Access-Control-Allow-Headers"] = "Content-Type,X-CSRF-Token,Idempotency-Key"
            else:
                maximum = (
                    settings.max_upload_mb * 1024 * 1024 + 1024 * 1024
                    if request.url.path.endswith("/assets")
                    else 3 * 1024 * 1024
                )
                try:
                    length = int(request.headers.get("content-length", "0"))
                except ValueError:
                    raise AppError("INVALID_LENGTH", "Content-Length không hợp lệ.", 400)
                if length > maximum:
                    raise AppError("UPLOAD_TOO_LARGE", "Request vượt giới hạn dung lượng.", 413)
                original_receive, received, exceeded = request._receive, 0, False

                async def limited_receive():
                    nonlocal received, exceeded
                    message = await original_receive()
                    received += len(message.get("body", b""))
                    if received > maximum:
                        exceeded = True
                        from starlette.formparsers import MultiPartException

                        raise MultiPartException("UPLOAD_TOO_LARGE")
                    return message

                request._receive = limited_receive
                response = await call_next(request)
                if exceeded:
                    raise AppError("UPLOAD_TOO_LARGE", "Request vượt giới hạn dung lượng.", 413)
            if origin in settings.origins:
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Access-Control-Allow-Credentials"] = "true"
                response.headers["Vary"] = "Origin"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "same-origin"
            response.headers["X-Request-ID"] = request_id
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
            )
            return response
        except AppError as exc:
            return error_response(exc, request_id)

    @app.exception_handler(AppError)
    async def app_error(request, exc):
        return error_response(exc, uid())

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        return error_response(
            AppError(
                "VALIDATION_ERROR",
                "Dữ liệu nhập không hợp lệ.",
                422,
                details={"fields": [list(e["loc"]) for e in exc.errors()]},
            ),
            uid(),
        )

    @app.exception_handler(Exception)
    async def internal_error(request, exc):
        return error_response(AppError("INTERNAL_ERROR", "Lỗi nội bộ; kiểm tra log backend.", 500), uid())

    @app.get("/api/v1/session")
    def session(request: Request):
        ref = request.headers.get("referer", "")
        parsed = urlparse(ref)
        referring_origin = f"{parsed.scheme}://{parsed.netloc}"
        if request.headers.get("origin") not in settings.origins and referring_origin not in settings.origins:
            raise AppError("BOOTSTRAP_FORBIDDEN", "Mở UI local để lấy phiên.", 403)
        response = JSONResponse({"csrf_token": app.state.csrf_token})
        response.set_cookie(
            "v2d_session", app.state.session_token, httponly=True, samesite="strict", max_age=43200
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    app.include_router(router)
    frontend = Path(__file__).resolve().parents[2] / "frontend/dist"

    @app.get("/{path:path}")
    def ui(path: str):
        if path.startswith("api/"):
            raise AppError("NOT_FOUND", "Không tìm thấy endpoint.", 404)
        target = frontend / path
        if not target.resolve().is_relative_to(frontend.resolve()):
            raise AppError("NOT_FOUND", "Không tìm thấy trang.", 404)
        if target.is_file():
            return FileResponse(target)
        if (frontend / "index.html").is_file():
            return FileResponse(frontend / "index.html")
        return JSONResponse({"message": "Build frontend: cd frontend && npm ci && npm run build"}, 503)

    return app


app = create_app()
