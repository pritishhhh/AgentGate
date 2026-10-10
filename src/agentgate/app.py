import asyncio
import json
import re
from contextlib import asynccontextmanager
from importlib.resources import files

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .agent import AgentRunner, ModelProvider
from .config import Settings
from .gateway import GateError, Gateway
from .mcp_server import build_mcp
from .models import AgentRequest, ApprovalDecision, PolicyUpdate, RegisterPrincipal, ToolCall
from .store import Store


class SecurityMiddleware:
    """Pure ASGI middleware: preserve streaming and bound incoming JSON before parsing."""

    def __init__(self, app, store, settings):
        self.app, self.store, self.settings = app, store, settings

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        path = scope["path"]
        origin = headers.get("origin")
        host = headers.get("host", "").split(":")[0]
        if host not in self.settings.allowed_hosts:
            return await JSONResponse({"detail": "untrusted_host"}, 400)(scope, receive, send)
        if origin and origin not in self.settings.allowed_origins:
            return await JSONResponse({"detail": "untrusted_origin"}, 403)(scope, receive, send)
        if path.startswith("/api/") or path.startswith("/mcp"):
            raw = headers.get("authorization", "")
            principal = (
                await asyncio.to_thread(self.store.authenticate, raw[7:])
                if raw.startswith("Bearer ")
                else None
            )
            if principal is None:
                return await JSONResponse({"detail": "invalid_credentials"}, 401)(scope, receive, send)
            scope.setdefault("state", {})["principal"] = principal
        # Buffer bounded bodies, including chunked requests, before Starlette/MCP parses JSON.
        if scope["method"] in ("POST", "PUT", "PATCH"):
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                body.extend(message.get("body", b""))
                if len(body) > 65536:
                    return await JSONResponse({"detail": "request_too_large"}, 413)(scope, receive, send)
                if not message.get("more_body", False):
                    break
            delivered = False

            async def bounded_receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()
        else:
            bounded_receive = receive

        async def secure_send(message):
            if message["type"] == "http.response.start":
                message["headers"] += [
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"cache-control", b"no-store"),
                    (
                        b"content-security-policy",
                        b"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'",
                    ),
                ]
            await send(message)

        await self.app(scope, bounded_receive, secure_send)


def create_app(settings: Settings | None = None, provider=None):
    settings = settings or Settings.from_env()
    store = Store(settings.data_dir)
    gateway = Gateway(settings, store)
    mcp = build_mcp(gateway)
    mcp_app = mcp.streamable_http_app()
    runner = AgentRunner(gateway, provider)

    @asynccontextmanager
    async def lifespan(app):
        async with mcp.session_manager.run():
            yield

    app = FastAPI(title="AgentGate", version="1.0.0", lifespan=lifespan)
    app.state.store, app.state.gateway, app.state.runner = store, gateway, runner
    app.add_middleware(SecurityMiddleware, store=store, settings=settings)

    def current(request: Request):
        return request.state.principal

    def admin(principal=Depends(current)):
        if principal.role != "admin":
            raise HTTPException(403, "admin_required")
        return principal

    @app.exception_handler(GateError)
    async def gate_error(request, exc):
        return JSONResponse({"detail": exc.code}, exc.status)

    @app.get("/health")
    def health():
        return {"status": "ok", "initialized": store.get_setting("policy") is not None, "version": "1.0.0"}

    @app.get("/api/me")
    def me(principal=Depends(current)):
        return principal

    @app.get("/api/model")
    async def model(principal=Depends(current)):
        return {
            "provider": settings.provider,
            "model": settings.model,
            **await ModelProvider(settings).check(),
        }

    @app.get("/api/tools")
    def tools(principal=Depends(current)):
        return {"tools": gateway.schemas()}

    @app.get("/api/datasets")
    def datasets(principal=Depends(current)):
        labels = gateway.policy().classifications.get(principal.role, [])
        return {"datasets": store.datasets(principal.tenant, labels)}

    @app.post("/api/tools/invoke")
    async def invoke(call: ToolCall, principal=Depends(current)):
        result = await gateway.invoke(principal, call)
        return JSONResponse(
            result,
            status_code=result.get("status", 202 if result["decision"] == "approval_required" else 200),
        )

    @app.post("/api/agent/run")
    async def agent_run(body: AgentRequest, request: Request, principal=Depends(current)):
        if not await asyncio.to_thread(store.rate_allowed, principal.id, settings.requests_per_minute):
            raise HTTPException(429, "rate_limit_exceeded")

        async def stream():
            async for event in runner.run(principal, body, request.is_disconnected):
                yield "data: " + json.dumps(event) + "\n\n"

        return StreamingResponse(
            stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
        )

    @app.get("/api/audit")
    def audit(after: int = 0, principal=Depends(current)):
        return {"events": store.events(principal, max(0, after))}

    @app.get("/api/audit/verify")
    def verify(principal=Depends(admin)):
        return store.verify_audit()

    @app.get("/api/events")
    async def events(request: Request, after: int = 0, principal=Depends(current)):
        async def stream():
            cursor = max(0, after)
            while not await request.is_disconnected():
                # Active streams cease when a credential is revoked.
                active = await asyncio.to_thread(store.principals)
                if not any(p["id"] == principal.id and p["active"] for p in active):
                    return
                rows = await asyncio.to_thread(store.events, principal, cursor)
                for row in rows:
                    cursor = row["seq"]
                    yield "id: " + str(cursor) + "\ndata: " + json.dumps(row) + "\n\n"
                if not rows:
                    yield ": keepalive\n\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(
            stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
        )

    @app.get("/api/approvals")
    def approvals(principal=Depends(current)):
        return {"approvals": store.approvals(principal)}

    @app.post("/api/approvals/{ticket}/decision")
    def approve(ticket: str, body: ApprovalDecision, principal=Depends(admin)):
        if not store.decide(ticket, principal.id, body.decision):
            raise HTTPException(409, "approval_unavailable")
        store.audit(principal.id, {"tool": "approval", "decision": body.decision, "approval_id": ticket})
        return {"ok": True}

    @app.get("/api/exports/{export_id}")
    def download(export_id: str, principal=Depends(current)):
        if not re.fullmatch(r"[a-f0-9]{32}", export_id):
            raise HTTPException(404, "export_unavailable")
        artifact = store.get_export(export_id, principal.id)
        if not artifact:
            raise HTTPException(404, "export_unavailable")
        return FileResponse(
            settings.data_dir / "exports" / artifact["filename"],
            filename="agentgate-report.csv",
            media_type="text/csv",
        )

    @app.get("/api/policy")
    def policy(principal=Depends(current)):
        return gateway.policy()

    @app.put("/api/policy")
    def update_policy(body: PolicyUpdate, principal=Depends(admin)):
        if body.policy.version != body.expected_version + 1:
            raise HTTPException(400, "policy_version_must_increment")
        if not store.set_policy(body.policy.model_dump(), body.expected_version):
            raise HTTPException(409, "policy_version_conflict")
        store.audit(
            principal.id,
            {"tool": "policy_update", "decision": "allow", "policy_version": body.policy.version},
        )
        return body.policy

    @app.get("/api/principals")
    def principals(principal=Depends(admin)):
        return {"principals": store.principals()}

    @app.post("/api/principals")
    def register(body: RegisterPrincipal, principal=Depends(admin)):
        if body.role not in gateway.policy().roles:
            raise HTTPException(400, "role_not_configured")
        registered, token = store.issue(body.name, body.role, body.tenant)
        store.audit(
            principal.id, {"tool": "identity_register", "decision": "allow", "target_id": registered.id}
        )
        return {"principal": registered, "token": token}

    @app.delete("/api/principals/{principal_id}")
    def revoke(principal_id: str, principal=Depends(admin)):
        if principal_id == principal.id:
            raise HTTPException(400, "cannot_revoke_current_admin")
        if not store.revoke(principal_id):
            raise HTTPException(404, "identity_unavailable")
        store.audit(principal.id, {"tool": "identity_revoke", "decision": "allow", "target_id": principal_id})
        return {"ok": True}

    app.mount("/mcp", mcp_app)
    app.mount(
        "/", StaticFiles(directory=str(files("agentgate").joinpath("static")), html=True), name="dashboard"
    )
    return app
