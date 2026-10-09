import asyncio
import threading

from agentgate.models import ToolCall


async def test_queued_call_uses_latest_approval_policy(environment):
    _, tokens, app, _ = environment
    gateway = app.state.gateway
    principal = app.state.store.authenticate(tokens["support"]["token"])
    gateway.tool_slots = asyncio.Semaphore(0)
    initial_checked = threading.Event()
    authorize = gateway.authorize

    def observed_authorize(*args):
        result = authorize(*args)
        initial_checked.set()
        return result

    gateway.authorize = observed_authorize
    task = asyncio.create_task(
        gateway.invoke(principal, ToolCall(tool="query_records", arguments={"dataset": "tickets"}))
    )
    assert await asyncio.to_thread(initial_checked.wait, 3)
    policy = gateway.policy().model_dump()
    policy["version"] += 1
    policy["approval_tools"].append("query_records")
    assert app.state.store.set_policy(policy, 1)
    gateway.tool_slots.release()
    result = await task
    assert result["decision"] == "approval_required"
    assert "result" not in result


async def test_queued_call_rechecks_revocation(environment):
    _, tokens, app, _ = environment
    gateway = app.state.gateway
    principal = app.state.store.authenticate(tokens["support"]["token"])
    gateway.tool_slots = asyncio.Semaphore(0)
    initial_checked = threading.Event()
    authorize = gateway.authorize

    def observed_authorize(*args):
        result = authorize(*args)
        initial_checked.set()
        return result

    gateway.authorize = observed_authorize
    task = asyncio.create_task(
        gateway.invoke(principal, ToolCall(tool="query_records", arguments={"dataset": "tickets"}))
    )
    assert await asyncio.to_thread(initial_checked.wait, 3)
    app.state.store.revoke(principal.id)
    gateway.tool_slots.release()
    assert (await task)["reason"] == "identity_revoked"
