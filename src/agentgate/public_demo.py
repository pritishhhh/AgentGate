"""Isolated public sandbox: actual gateway calls, synthetic resources, no privileged credentials."""

import hashlib
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .config import Settings
from .gateway import Gateway
from .models import DatasetDefinition, Policy, ToolCall
from .store import Store

# Deliberately public; this token is a visitor selector, never an administrator secret.
DEMO_TOKEN = "ag_demo_visitor_readonly"
DEMO_ID = "public-demo-visitor"
DEMO_ROLE = "public-demo"
READ_TOOLS = ["search_documents", "read_document", "query_records"]


def demo_profile():
    return {
        "enabled": True,
        "token": DEMO_TOKEN,
        "api_prefix": "/demo",
        "name": "Public visitor",
        "read_only": True,
    }


class DemoBoundary:
    def __init__(self, app, store):
        self.app, self.store = app, store

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {key.decode().lower(): value.decode() for key, value in scope["headers"]}
        principal = (
            self.store.authenticate(headers.get("authorization", "").removeprefix("Bearer "))
            if headers.get("authorization", "").startswith("Bearer ")
            else None
        )
        if principal is None:
            return await JSONResponse({"detail": "invalid_demo_credentials"}, 401)(scope, receive, send)
        scope.setdefault("state", {})["principal"] = principal
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
        return await self.app(scope, bounded_receive, send)


def create_public_demo():
    store = Store(None)
    store.set_policy(
        Policy(
            version=1,
            roles={DEMO_ROLE: READ_TOOLS},
            classifications={DEMO_ROLE: ["public", "support", "development", "security"]},
            approval_tools=[],
        ).model_dump()
    )
    with store.connect() as db:
        db.execute(
            "INSERT INTO principals VALUES(?,?,?,?,?,?)",
            (
                DEMO_ID,
                "Public visitor",
                DEMO_ROLE,
                "demo",
                1,
                hashlib.sha256(DEMO_TOKEN.encode()).hexdigest(),
            ),
        )
        db.executemany(
            "INSERT INTO documents VALUES(?,?,?,?,?)",
            [
                (
                    "demo-welcome",
                    "demo",
                    "public",
                    "Demo handbook",
                    "Synthetic demo workspace for document, developer and incident workflows.",
                ),
                (
                    "demo-support-guide",
                    "demo",
                    "support",
                    "Support escalation guide",
                    "Review the support queue, classify the issue, and escalate unresolved billing questions. Synthetic contact: alice@example.test.",
                ),
                (
                    "demo-developer-guide",
                    "demo",
                    "development",
                    "Development triage guide",
                    "Review issues, reproduce the login timeout, and request human approval before creating an issue in the full backend.",
                ),
                (
                    "demo-incident-runbook",
                    "demo",
                    "security",
                    "Incident response runbook",
                    "Review alerts, assign severity and notify an analyst. Consequential actions require a privileged workflow.",
                ),
                (
                    "demo-payroll-policy",
                    "demo",
                    "finance",
                    "Restricted payroll policy",
                    "This synthetic finance document is outside the public visitor's classifications.",
                ),
                (
                    "demo-other-tenant",
                    "other-demo",
                    "support",
                    "Other tenant document",
                    "This synthetic document must remain isolated from the demo tenant.",
                ),
            ],
        )
    for name, label, record in [
        (
            "tickets",
            "support",
            {
                "ticket": 1,
                "subject": "Synthetic billing question",
                "customer_email": "customer@example.test",
                "status": "open",
            },
        ),
        (
            "issues",
            "development",
            {"title": "Synthetic login timeout", "status": "open", "category": "development"},
        ),
        ("alerts", "security", {"title": "Synthetic failed sign-ins", "severity": "high", "count": 12}),
        ("payroll", "finance", {"employee": "Synthetic employee", "salary": 50000}),
    ]:
        store.add_dataset(DatasetDefinition(name=name, tenant="demo", classification=label))
        store.create_record("demo", name, record)
    gateway = Gateway(Settings(data_dir=Path(__file__).parent / "defaults"), store)
    app = FastAPI(title="AgentGate public read-only demo", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store, app.state.gateway = store, gateway
    app.add_middleware(DemoBoundary, store=store)

    def current(request: Request):
        return request.state.principal

    @app.get("/api/me")
    def me(principal=Depends(current)):
        return {**principal.model_dump(), "public_demo": True, "can_run_agent": False}

    @app.get("/api/tools")
    def tools(principal=Depends(current)):
        return {"tools": gateway.schemas()}

    @app.get("/api/datasets")
    def datasets(principal=Depends(current)):
        return {
            "datasets": store.datasets(principal.tenant, gateway.policy().classifications[principal.role])
        }

    @app.get("/api/policy")
    def policy(principal=Depends(current)):
        return gateway.policy()

    @app.get("/api/model")
    def model(principal=Depends(current)):
        return {
            "ready": False,
            "public_demo": True,
            "provider": "Public read-only demo",
            "model": "Live AI requires the full backend",
        }

    @app.get("/api/approvals")
    def approvals(principal=Depends(current)):
        return {"approvals": store.approvals(principal)}

    @app.get("/api/audit")
    def audit(principal=Depends(current)):
        return {"events": store.events(principal)}

    @app.post("/api/tools/invoke")
    async def invoke(call: ToolCall, principal=Depends(current)):
        result = await gateway.invoke(principal, call)
        # Return the actual audit record so separate serverless instances still show this request's decision.
        result["audit_event"] = store.event_by_request(principal.id, result["request_id"])
        return JSONResponse(result, result.get("status", 200))

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def restricted(path: str, principal=Depends(current)):
        raise HTTPException(
            403, "Public demo is read-only. Live AI and administrator actions require the full backend."
        )

    return app
