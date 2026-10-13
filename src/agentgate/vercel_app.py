"""Stateless dashboard/proxy entrypoint. All identity and execution state stays in the backend."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .deployment import backend_origin
from .public_demo import create_public_demo, demo_profile

SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'",
}


def create_frontend(backend: str | None = None, *, transport=None):
    configured = os.getenv("AGENTGATE_BACKEND_URL", "") if backend is None else backend
    origin = backend_origin(configured) if configured else None

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(
            transport=transport,
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(310, connect=5, write=10, pool=5),
            limits=httpx.Limits(max_connections=32, max_keepalive_connections=16),
        ) as client:
            app.state.client = client
            yield

    app = FastAPI(
        title="AgentGate frontend", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan
    )

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response

    @app.get("/public/demo")
    def visitor():
        return demo_profile()

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
    @app.api_route("/mcp", methods=["GET", "POST", "DELETE", "OPTIONS"])
    @app.api_route("/mcp/{path:path}", methods=["GET", "POST", "DELETE", "OPTIONS"])
    @app.api_route("/health", methods=["GET", "HEAD"])
    @app.api_route("/docs", methods=["GET", "HEAD"])
    @app.api_route("/openapi.json", methods=["GET", "HEAD"])
    async def proxy(request: Request):
        if not origin:
            return JSONResponse(
                {
                    "detail": "Backend not connected. Host the AgentGate backend and set AGENTGATE_BACKEND_URL in Vercel."
                },
                status_code=503,
            )
        # Send only protocol/authentication headers, never cookies or a client-supplied Host.
        headers = {
            name: request.headers[name]
            for name in (
                "authorization",
                "content-type",
                "accept",
                "origin",
                "mcp-session-id",
                "mcp-protocol-version",
                "last-event-id",
            )
            if name in request.headers
        }
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 65536:
                return JSONResponse({"detail": "request_too_large"}, status_code=413)
        path = "/mcp/" if request.url.path == "/mcp" else request.url.path
        target = origin + path + ("?" + request.url.query if request.url.query else "")
        client = app.state.client
        try:
            response = await client.send(
                client.build_request(request.method, target, headers=headers, content=bytes(body)),
                stream=True,
            )
        except httpx.HTTPError:
            return JSONResponse(
                {"detail": "Backend unavailable. Check the backend URL and server."}, status_code=502
            )
        if response.is_redirect:
            await response.aclose()
            return JSONResponse(
                {"detail": "Backend redirect rejected; configure its final HTTPS origin."}, status_code=502
            )
        forwarded = {
            name: response.headers[name]
            for name in (
                "content-type",
                "content-disposition",
                "mcp-session-id",
                "mcp-protocol-version",
                "retry-after",
            )
            if name in response.headers
        }
        forwarded["X-Accel-Buffering"] = "no"

        async def stream():
            try:
                async for chunk in response.aiter_bytes():
                    yield chunk
            finally:
                await response.aclose()

        return StreamingResponse(stream(), status_code=response.status_code, headers=forwarded)

    app.mount("/demo", create_public_demo())
    app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="dashboard")
    return app
