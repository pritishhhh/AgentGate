import asyncio

from agentgate.models import DatasetDefinition, ToolCall

from .conftest import headers


def test_custom_role_dataset_and_reserved_admin(environment):
    _, tokens, app, client = environment
    store = app.state.store
    policy = store.get_setting("policy")
    policy["roles"]["researcher"] = ["query_records"]
    policy["classifications"]["researcher"] = ["research"]
    store.set_policy(policy)
    store.add_dataset(DatasetDefinition(name="experiments", tenant="acme", classification="research"))
    store.create_record("acme", "experiments", {"measurement": 7})
    issued = client.post(
        "/api/principals",
        headers=headers(tokens, "admin"),
        json={"name": "Research", "role": "researcher", "tenant": "acme"},
    )
    assert issued.status_code == 200
    auth = {"Authorization": "Bearer " + issued.json()["token"]}
    assert client.get("/api/principals", headers=auth).status_code == 403
    response = client.post(
        "/api/tools/invoke",
        headers=auth,
        json={"tool": "query_records", "arguments": {"dataset": "experiments"}},
    )
    assert response.json()["result"]["rows"] == [{"measurement": 7}]
    assert [d["name"] for d in client.get("/api/datasets", headers=auth).json()["datasets"]] == [
        "experiments"
    ]
    assert (
        client.post(
            "/api/principals",
            headers=headers(tokens, "admin"),
            json={"name": "Unknown", "role": "ghost", "tenant": "acme"},
        ).status_code
        == 400
    )


def test_three_workflows_and_approval_bound_write(environment):
    _, tokens, app, client = environment
    for role, document, dataset, category in [
        ("developer", "developer-guide", "issues", "development"),
        ("analyst", "incident-runbook", "incidents", "security"),
    ]:
        auth = headers(tokens, role)
        assert (
            client.post(
                "/api/tools/invoke",
                headers=auth,
                json={"tool": "read_document", "arguments": {"document_id": document}},
            ).status_code
            == 200
        )
        body = {
            "tool": "create_record",
            "arguments": {
                "dataset": dataset,
                "record": {"title": "Triage example", "status": "open", "category": category},
            },
        }
        before = len(app.state.store.records("acme", dataset, 50))
        pending = client.post("/api/tools/invoke", headers=auth, json=body).json()
        assert pending["decision"] == "approval_required"
        assert len(app.state.store.records("acme", dataset, 50)) == before
        assert (
            client.post(
                f"/api/approvals/{pending['approval_id']}/decision",
                headers=headers(tokens, "admin"),
                json={"decision": "approved"},
            ).status_code
            == 200
        )
        body["approval_id"] = pending["approval_id"]
        assert client.post("/api/tools/invoke", headers=auth, json=body).json()["decision"] == "allow"
        assert client.post("/api/tools/invoke", headers=auth, json=body).status_code == 403
        assert len(app.state.store.records("acme", dataset, 50)) == before + 1
    assert (
        client.post(
            "/api/tools/invoke",
            headers=headers(tokens),
            json={"tool": "read_document", "arguments": {"document_id": "support-guide"}},
        ).status_code
        == 200
    )


def test_catalog_and_write_cannot_be_spoofed(environment):
    _, tokens, app, client = environment
    auth = headers(tokens, "developer")
    for arguments in [
        {"dataset": "issues", "role": "admin", "record": {"title": "Bad", "status": "open"}},
        {"dataset": "issues", "record": {"title": "Bad", "status": "open", "command": "whoami"}},
        {"dataset": "issues", "record": {"title": "Bad", "status": 1}},
        {"dataset": "incidents", "record": {"title": "Bad", "status": "open"}},
    ]:
        assert (
            client.post(
                "/api/tools/invoke", headers=auth, json={"tool": "create_record", "arguments": arguments}
            ).json()["decision"]
            == "deny"
        )
    assert not app.state.store.add_dataset(
        DatasetDefinition(name="issues", tenant="acme", classification="public")
    )
    assert app.state.store.dataset("acme", "issues")["classification"] == "development"


def test_write_redaction_and_queued_policy_change(environment):
    _, tokens, app, _ = environment
    gateway, store = app.state.gateway, app.state.store
    developer = store.authenticate(tokens["developer"]["token"])

    async def exercise():
        call = ToolCall(
            tool="create_record",
            arguments={
                "dataset": "issues",
                "record": {"title": "Contact alice@example.test", "status": "open"},
            },
        )
        pending = await gateway.invoke(developer, call)
        store.decide(pending["approval_id"], "admin", "approved")
        result = await gateway.invoke(
            developer, call.model_copy(update={"approval_id": pending["approval_id"]})
        )
        assert result["decision"] == "allow"
        assert result["redactions"]
        assert "alice@example.test" not in str(store.records("acme", "issues", 50))
        gateway.tool_slots = asyncio.Semaphore(0)
        task = asyncio.create_task(
            gateway.invoke(developer, ToolCall(tool="query_records", arguments={"dataset": "issues"}))
        )
        await asyncio.sleep(0.05)
        policy = store.get_setting("policy")
        policy["roles"]["developer"] = []
        policy["version"] += 1
        store.set_policy(policy)
        gateway.tool_slots.release()
        assert (await task)["reason"] == "tool_not_permitted"

    asyncio.run(exercise())
