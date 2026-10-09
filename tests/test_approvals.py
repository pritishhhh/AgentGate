import asyncio
import time

from agentgate.models import ToolCall

from .conftest import headers
from .test_boundary import invoke


def ticket_for(env):
    response = invoke(env, "export_report", {"dataset": "tickets", "limit": 3})
    assert response.status_code == 202
    return response.json()["approval_id"]


def approve(env, ticket):
    _, tokens, _, client = env
    return client.post(
        f"/api/approvals/{ticket}/decision", json={"decision": "approved"}, headers=headers(tokens, "admin")
    )


def test_pending_approval_does_not_execute_export(environment):
    settings, tokens, _, client = environment
    ticket = ticket_for(environment)
    assert not (settings.data_dir / "exports").exists()
    response = client.post(
        f"/api/approvals/{ticket}/decision", json={"decision": "approved"}, headers=headers(tokens)
    )
    assert response.status_code == 403
    assert (
        invoke(environment, "export_report", {"dataset": "tickets", "limit": 3}, approval=ticket).status_code
        == 403
    )


def test_exact_approval_executes_once_and_download_is_owned(environment):
    _, tokens, _, client = environment
    ticket = ticket_for(environment)
    assert approve(environment, ticket).status_code == 200
    result = invoke(environment, "export_report", {"dataset": "tickets", "limit": 3}, approval=ticket).json()
    assert result["ok"]
    download = result["result"]["download"]
    content = client.get(download, headers=headers(tokens))
    assert content.status_code == 200
    assert "customer1@example.test" not in content.text
    assert "[REDACTED:email]" in content.text
    assert client.get(download, headers=headers(tokens, "finance")).status_code == 404
    assert (
        invoke(environment, "export_report", {"dataset": "tickets", "limit": 3}, approval=ticket).status_code
        == 403
    )


def test_approval_cannot_be_reused_for_changed_arguments_or_identity(environment):
    ticket = ticket_for(environment)
    approve(environment, ticket)
    assert (
        invoke(environment, "export_report", {"dataset": "tickets", "limit": 4}, approval=ticket).status_code
        == 403
    )
    assert (
        invoke(
            environment, "export_report", {"dataset": "payroll", "limit": 3}, "finance", ticket
        ).status_code
        == 403
    )
    assert (
        invoke(environment, "export_report", {"dataset": "tickets", "limit": 3}, approval=ticket).status_code
        == 200
    )


def test_expired_approval_cannot_execute(environment):
    _, _, app, _ = environment
    ticket = ticket_for(environment)
    approve(environment, ticket)
    with app.state.store.connect() as db:
        db.execute("UPDATE approvals SET expires=? WHERE id=?", (time.time() - 1, ticket))
    assert (
        invoke(environment, "export_report", {"dataset": "tickets", "limit": 3}, approval=ticket).status_code
        == 403
    )


async def test_simultaneous_replay_only_executes_one_export(environment):
    settings, tokens, app, _ = environment
    ticket = ticket_for(environment)
    approve(environment, ticket)
    principal = app.state.store.authenticate(tokens["support"]["token"])
    call = ToolCall(tool="export_report", arguments={"dataset": "tickets", "limit": 3}, approval_id=ticket)
    results = await asyncio.gather(*[app.state.gateway.invoke(principal, call) for _ in range(8)])
    assert sum(r["ok"] for r in results) == 1
    assert len(list((settings.data_dir / "exports").glob("*.csv"))) == 1
