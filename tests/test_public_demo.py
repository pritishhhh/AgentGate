import pytest
from fastapi.testclient import TestClient

from agentgate.public_demo import DEMO_TOKEN
from agentgate.vercel_app import create_frontend

AUTH = {"Authorization": "Bearer " + DEMO_TOKEN}


def test_public_login_works_without_hosted_backend_and_writes_no_files(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    with TestClient(create_frontend(backend="")) as client:
        profile = client.get("/public/demo").json()
        assert profile["token"] == DEMO_TOKEN
        assert profile["read_only"]
        assert client.get("/demo/api/me").status_code == 401
        me = client.get("/demo/api/me", headers=AUTH)
        assert me.status_code == 200
        assert me.json()["role"] == "public-demo"
        assert me.json()["tenant"] == "demo"
        assert me.json()["can_run_agent"] is False
        assert client.get("/api/me", headers=AUTH).status_code == 503
    assert list(tmp_path.iterdir()) == []


def test_native_public_token_is_isolated_from_operator_store(environment):
    _, tokens, app, client = environment
    assert client.get("/api/me", headers=AUTH).status_code == 401
    assert (
        client.get(
            "/demo/api/me", headers={"Authorization": "Bearer " + tokens["admin"]["token"]}
        ).status_code
        == 401
    )
    assert not any(p["role"] == "public-demo" for p in app.state.store.principals())
    assert client.get("/demo/api/me", headers=AUTH).status_code == 200


def test_demo_tools_execute_shared_gateway_and_emit_real_audit():
    with TestClient(create_frontend(backend="")) as client:
        allowed = client.post(
            "/demo/api/tools/invoke",
            headers=AUTH,
            json={"tool": "query_records", "arguments": {"dataset": "tickets", "limit": 5}},
        )
        result = allowed.json()
        assert allowed.status_code == 200
        assert result["decision"] == "allow"
        assert result["result"]["rows"][0]["ticket"] == 1
        assert result["result"]["rows"][0]["customer_email"] == "[REDACTED:email]"
        assert result["audit_event"]["decision"] == "allow"
        assert result["audit_event"]["request_id"] == result["request_id"]
        events = client.get("/demo/api/audit", headers=AUTH).json()["events"]
        assert len(events) == 1
        assert "customer@example.test" not in str(events)
        allowed = client.post(
            "/demo/api/tools/invoke",
            headers=AUTH,
            json={"tool": "read_document", "arguments": {"document_id": "demo-support-guide"}},
        )
        assert allowed.status_code == 200
        assert "escalate" in allowed.json()["result"]["document"]["content"]


@pytest.mark.parametrize(
    "tool,arguments,reason",
    [
        ("query_records", {"dataset": "payroll"}, "resource_not_permitted"),
        ("read_document", {"document_id": "demo-other-tenant"}, "resource_not_permitted"),
        ("read_document", {"document_id": "demo-payroll-policy"}, "resource_not_permitted"),
        ("read_document", {"document_id": "support-guide"}, "resource_not_permitted"),
        ("query_records", {"dataset": "tickets", "role": "admin"}, "invalid_arguments"),
        ("export_report", {"dataset": "tickets"}, "tool_not_permitted"),
        (
            "create_record",
            {"dataset": "issues", "record": {"title": "Unauthorized", "status": "open"}},
            "tool_not_permitted",
        ),
        (
            "invoke_connector",
            {"connector": "helpdesk", "operation": "create", "payload": {}},
            "tool_not_permitted",
        ),
    ],
)
def test_public_visitor_enforcement(tool, arguments, reason):
    with TestClient(create_frontend(backend="")) as client:
        response = client.post(
            "/demo/api/tools/invoke", headers=AUTH, json={"tool": tool, "arguments": arguments}
        )
        assert response.json()["decision"] == "deny"
        assert response.json()["reason"] == reason
        assert response.json()["audit_event"]["decision"] == "deny"


def test_public_admin_and_agent_routes_are_blocked_and_body_is_bounded():
    with TestClient(create_frontend(backend="")) as client:
        for method, path in [
            ("POST", "/api/principals"),
            ("GET", "/api/principals"),
            ("PUT", "/api/policy"),
            ("POST", "/api/approvals/example/decision"),
            ("POST", "/api/agent/run"),
            ("GET", "/api/audit/verify"),
        ]:
            assert client.request(method, "/demo" + path, headers=AUTH, json={}).status_code == 403
        assert client.post("/demo/api/tools/invoke", headers=AUTH, content=b"x" * 65537).status_code == 413
        assert client.get("/demo/api/approvals", headers=AUTH).json()["approvals"] == []
        assert client.get("/demo/api/model", headers=AUTH).json()["ready"] is False
