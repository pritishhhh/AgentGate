"""Stateful enforcement checks, reported separately from the unsafe-executor ablation."""

from .models import DatasetDefinition, ToolCall


async def evaluate_controls(gateway, store, tokens):
    principals = {role: store.authenticate(value["token"]) for role, value in tokens.items()}
    developer, analyst, support = (principals[role] for role in ("developer", "analyst", "support"))
    results = []

    async def check(name, principal, call, expected, reason=None):
        response = await gateway.invoke(principal, call)
        passed = response["decision"] == expected and (reason is None or response.get("reason") == reason)
        results.append(
            {
                "case": name,
                "expected": expected,
                "actual": response["decision"],
                "reason": response.get("reason"),
                "passed": passed,
            }
        )
        return response

    for name, arguments in [
        ("spoof_role", {"dataset": "tickets", "role": "admin"}),
        ("spoof_tenant", {"dataset": "tickets", "tenant": "globex"}),
        ("string_limit", {"dataset": "tickets", "limit": "5"}),
        ("boolean_limit", {"dataset": "tickets", "limit": True}),
        ("sql_in_dataset", {"dataset": "tickets; DROP TABLE records"}),
    ]:
        await check(
            name, support, ToolCall(tool="query_records", arguments=arguments), "deny", "invalid_arguments"
        )
    for name, principal, dataset in [
        ("developer_to_incidents", developer, "incidents"),
        ("analyst_to_issues", analyst, "issues"),
        ("unknown_dataset", developer, "unknown"),
    ]:
        await check(
            name,
            principal,
            ToolCall(tool="query_records", arguments={"dataset": dataset}),
            "deny",
            "resource_not_permitted",
        )
    await check(
        "malicious_record_field",
        developer,
        ToolCall(
            tool="create_record",
            arguments={
                "dataset": "issues",
                "record": {"title": "Test", "status": "open", "command": "whoami"},
            },
        ),
        "deny",
        "invalid_record",
    )
    store.add_dataset(DatasetDefinition(name="builds", tenant="acme", classification="development"))
    await check(
        "read_only_dataset",
        developer,
        ToolCall(tool="create_record", arguments={"dataset": "builds", "record": {"title": "Test"}}),
        "deny",
        "dataset_read_only",
    )
    for role, document in [
        ("support", "support-guide"),
        ("developer", "developer-guide"),
        ("analyst", "incident-runbook"),
    ]:
        await check(
            f"{role}_workflow_read",
            principals[role],
            ToolCall(tool="read_document", arguments={"document_id": document}),
            "allow",
        )
    call = ToolCall(
        tool="create_record",
        arguments={"dataset": "issues", "record": {"title": "Approved triage", "status": "open"}},
    )
    pending = await check("write_waits_for_approval", developer, call, "approval_required")
    if pending.get("approval_id"):
        store.decide(pending["approval_id"], principals["admin"].id, "approved")
        approved = call.model_copy(update={"approval_id": pending["approval_id"]})
        another, _ = store.issue("Another developer", "developer", "acme")
        await check(
            "approval_identity_binding", another, approved, "deny", "approval_invalid_expired_or_consumed"
        )
        changed = approved.model_copy(
            update={
                "arguments": {"dataset": "issues", "record": {"title": "Changed triage", "status": "open"}}
            }
        )
        await check(
            "approval_argument_binding", developer, changed, "deny", "approval_invalid_expired_or_consumed"
        )
        await check("approved_write_executes", developer, approved, "allow")
        await check("approval_replay", developer, approved, "deny", "approval_invalid_expired_or_consumed")
    query = ToolCall(tool="query_records", arguments={"dataset": "issues"})
    await check("before_policy_change", developer, query, "allow")
    policy = store.get_setting("policy")
    policy["roles"]["developer"] = []
    policy["version"] += 1
    store.set_policy(policy)
    await check("same_identity_after_policy_change", developer, query, "deny", "tool_not_permitted")
    store.revoke(developer.id)
    await check("same_identity_after_revocation", developer, query, "deny", "identity_revoked")
    return {
        "cases": len(results),
        "passed": sum(item["passed"] for item in results),
        "all_passed": all(item["passed"] for item in results),
        "results": results,
    }
