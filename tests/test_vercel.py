import importlib.util
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from agentgate.vercel_app import create_frontend


def test_vercel_entrypoint_without_backend_writes_no_state(monkeypatch, tmp_path):
    monkeypatch.delenv("AGENTGATE_BACKEND_URL", raising=False)
    monkeypatch.chdir(tmp_path)
    source = Path(__file__).resolve().parents[1] / "app.py"
    spec = importlib.util.spec_from_file_location("vercel_entrypoint", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with TestClient(module.app) as client:
        assert client.get("/").status_code == 200
        response = client.get("/api/me", headers={"Authorization": "Bearer local-only-token"})
        assert response.status_code == 503
        assert "Backend not connected" in response.json()["detail"]
        assert response.headers["cache-control"] == "no-store"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "backend",
    [
        "http://api.example.com",
        "https://localhost",
        "https://127.0.0.1",
        "https://user:secret@api.example.com",
        "https://api.example.com/path",
    ],
)
def test_vercel_rejects_invalid_backend(backend):
    with pytest.raises(ValueError):
        create_frontend(backend)


def test_vercel_proxy_auth_body_query_stream_and_download():
    received = []

    def upstream(request):
        received.append(request)
        if request.url.path == "/api/agent/run":
            return httpx.Response(
                200, headers={"Content-Type": "text/event-stream"}, content=b'data: {"type":"done"}\n\n'
            )
        if request.url.path.startswith("/api/exports/"):
            return httpx.Response(
                200,
                headers={
                    "Content-Type": "text/csv",
                    "Content-Disposition": "attachment; filename=report.csv",
                },
                content=b"title\nApproved issue\n",
            )
        return httpx.Response(403, json={"decision": "deny", "reason": "resource_not_permitted"})

    with TestClient(
        create_frontend("https://api.example.com", transport=httpx.MockTransport(upstream))
    ) as client:
        response = client.post(
            "/api/tools/invoke?after=7",
            headers={
                "Authorization": "Bearer example-token",
                "Origin": "https://dashboard.example.com",
                "Cookie": "private=ignored",
            },
            json={"tool": "query_records", "arguments": {"dataset": "payroll"}},
        )
        assert response.status_code == 403
        assert received[0].url.host == "api.example.com"
        assert received[0].url.query == b"after=7"
        assert received[0].headers["authorization"] == "Bearer example-token"
        assert received[0].headers["origin"] == "https://dashboard.example.com"
        assert "cookie" not in received[0].headers
        assert b'"dataset":"payroll"' in received[0].content
        stream = client.post("/api/agent/run", json={"prompt": "Read guide"})
        assert stream.text == 'data: {"type":"done"}\n\n'
        assert stream.headers["content-type"].startswith("text/event-stream")
        download = client.get("/api/exports/example")
        assert "Approved issue" in download.text
        assert "attachment" in download.headers["content-disposition"]
        client.post(
            "/mcp",
            headers={"MCP-Protocol-Version": "2025-03-26", "Accept": "application/json, text/event-stream"},
            json={"method": "initialize"},
        )
        assert received[-1].url.path == "/mcp/"
        assert received[-1].headers["mcp-protocol-version"] == "2025-03-26"
        before = len(received)
        assert client.post("/api/tools/invoke", content=b"x" * 65537).status_code == 413
        assert len(received) == before


def test_vercel_rejects_redirects_and_sanitizes_network_failure():
    def upstream(request):
        if request.url.path.endswith("redirect"):
            return httpx.Response(307, headers={"Location": "https://another.example.com"})
        raise httpx.ConnectError("sensitive upstream details", request=request)

    with TestClient(
        create_frontend("https://api.example.com", transport=httpx.MockTransport(upstream))
    ) as client:
        assert client.get("/api/redirect").status_code == 502
        response = client.get("/api/me")
        assert response.status_code == 502
        assert "sensitive" not in response.text
