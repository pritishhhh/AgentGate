import json
import time

import pytest

from .conftest import headers


def invoke(env, tool, arguments, role="support", approval=None):
    _, tokens, _, client = env
    body = {"tool": tool, "arguments": arguments}
    if approval:
        body["approval_id"] = approval
    return client.post("/api/tools/invoke", json=body, headers=headers(tokens, role))


@pytest.mark.parametrize(
    "role,tool,args",
    [
        ("support", "query_records", {"dataset": "payroll"}),
        ("support", "read_document", {"document_id": "payroll-policy"}),
        ("support", "read_document", {"document_id": "other-tenant"}),
        ("finance", "query_records", {"dataset": "tickets"}),
        ("finance", "read_document", {"document_id": "support-guide"}),
        ("support", "export_report", {"dataset": "payroll"}),
    ],
)
def test_resource_isolation(environment, role, tool, args):
    result = invoke(environment, tool, args, role)
    assert result.status_code == 403
    assert "result" not in result.json()
    assert result.json()["reason"] == "resource_not_permitted"


def test_search_filters_metadata_before_returning(environment):
    result = invoke(environment, "search_documents", {"query": "payroll"}).json()
    # The accessible injected document may mention payroll; the finance document must stay invisible.
    ids = [d["id"] for d in result["result"]["documents"]]
    assert "payroll-policy" not in ids
    assert "other-tenant" not in ids


@pytest.mark.parametrize(
    "tool,args",
    [
        ("read_document", {"document_id": "../../data/credentials.json"}),
        ("query_records", {"dataset": "tickets; DROP TABLE principals"}),
        ("query_records", {"dataset": "tickets", "limit": 100000}),
        ("query_records", {"dataset": "tickets", "limit": "5"}),
        ("query_records", {"dataset": "tickets", "role": "admin"}),
        ("search_documents", {"query": "support", "tenant": "globex"}),
        ("execute_shell", {"command": "whoami"}),
        (
            "invoke_connector",
            {"connector": "unregistered", "operation": "fetch", "payload": {"url": "http://example.test"}},
        ),
    ],
)
def test_untrusted_arguments_cannot_expand_permissions(environment, tool, args):
    response = invoke(environment, tool, args)
    assert response.status_code in (400, 403)
    assert response.json()["decision"] == "deny"


def test_dlp_and_audit_do_not_persist_raw_results(environment):
    _, tokens, app, client = environment
    result = invoke(environment, "read_document", {"document_id": "payroll-policy"}, "finance").json()
    assert result["redactions"] == {"ssn": 1, "api_key": 1}
    serialized = json.dumps(result)
    assert "123-45-6789" not in serialized
    assert "AGDEMO_abcdefghijklmnop1234" not in serialized
    events = client.get("/api/audit", headers=headers(tokens, "finance")).json()["events"]
    assert len(events) == 1
    assert "arguments" not in events[0] and "result" not in events[0]
    assert app.state.store.verify_audit()["valid"]


def test_identity_revocation_invalidates_existing_credentials(environment):
    _, tokens, _, client = environment
    identity = tokens["support"]["principal_id"]
    assert client.delete(f"/api/principals/{identity}", headers=headers(tokens, "admin")).status_code == 200
    assert client.get("/api/me", headers=headers(tokens)).status_code == 401


def test_viewer_cannot_read_other_identity_audit_or_admin_endpoints(environment):
    _, tokens, _, client = environment
    invoke(environment, "read_document", {"document_id": "payroll-policy"}, "finance")
    assert client.get("/api/audit", headers=headers(tokens)).json()["events"] == []
    assert client.get("/api/principals", headers=headers(tokens)).status_code == 403
    assert (
        client.post(
            "/api/principals",
            json={"name": "evil", "role": "admin", "tenant": "acme"},
            headers=headers(tokens),
        ).status_code
        == 403
    )


def test_origin_host_auth_and_body_limits(environment):
    _, tokens, _, client = environment
    assert client.get("/api/tools").status_code == 401
    assert (
        client.get("/api/tools", headers={**headers(tokens), "Origin": "https://evil.example"}).status_code
        == 403
    )
    assert client.get("/health", headers={"Host": "evil.example"}).status_code == 400
    response = client.post("/api/tools/invoke", content=b"x" * 65537, headers=headers(tokens))
    assert response.status_code == 413


def test_policy_updates_apply_and_stale_writes_are_rejected(environment):
    _, tokens, _, client = environment
    policy = client.get("/api/policy", headers=headers(tokens)).json()
    policy["roles"]["support"] = []
    policy["version"] = 2
    update = {"expected_version": 1, "policy": policy}
    assert client.put("/api/policy", json=update, headers=headers(tokens, "admin")).status_code == 200
    assert client.put("/api/policy", json=update, headers=headers(tokens, "admin")).status_code == 409
    assert (
        invoke(environment, "query_records", {"dataset": "tickets"}).json()["reason"] == "tool_not_permitted"
    )


def test_rate_limit(environment):
    _, tokens, app, client = environment
    principal = tokens["support"]["principal_id"]
    with app.state.store.connect() as db:
        db.executemany("INSERT INTO rate_limits VALUES(?,?)", [(principal, time.time())] * 1000)
    assert invoke(environment, "search_documents", {"query": "support"}).status_code == 429


def test_audit_tampering_is_detected(environment):
    _, _, app, _ = environment
    invoke(environment, "query_records", {"dataset": "tickets"})
    with app.state.store.connect() as db:
        db.execute("UPDATE audit SET event='{}' WHERE seq=1")
    report = app.state.store.verify_audit()
    assert report["valid"] is False and report["failed_at"] == 1
