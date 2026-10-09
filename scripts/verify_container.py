"""Verify a running container without printing or persisting its bootstrap credentials."""

import argparse
import asyncio
import json
import subprocess

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--container", default="agentgate-docker-smoke")
    parser.add_argument("--url", default="http://127.0.0.1:8001")
    parser.add_argument(
        "--with-model", action="store_true", help="Also require a real model-driven agent task"
    )
    args = parser.parse_args()
    base = args.url.rstrip("/")
    async with httpx.AsyncClient(base_url=base, trust_env=False, timeout=5) as client:
        for attempt in range(60):
            try:
                response = await client.get("/health")
                response.raise_for_status()
                assert response.json()["initialized"]
                break
            except (httpx.HTTPError, AssertionError):
                if attempt == 59:
                    raise RuntimeError("Container did not become ready") from None
                await asyncio.sleep(0.25)
        credentials = json.loads(
            subprocess.check_output(["docker", "exec", args.container, "cat", "/data/credentials.json"])
        )
        support = {"Authorization": "Bearer " + credentials["support"]["token"]}
        admin = {"Authorization": "Bearer " + credentials["admin"]["token"]}
        allowed = await client.post(
            "/api/tools/invoke",
            headers=support,
            json={"tool": "query_records", "arguments": {"dataset": "tickets", "limit": 2}},
        )
        assert allowed.status_code == 200 and len(allowed.json()["result"]["rows"]) == 2
        denied = await client.post(
            "/api/tools/invoke",
            headers=support,
            json={"tool": "query_records", "arguments": {"dataset": "payroll"}},
        )
        assert denied.status_code == 403 and "result" not in denied.json()
        body = {"tool": "export_report", "arguments": {"dataset": "tickets", "limit": 2}}
        pending = await client.post("/api/tools/invoke", headers=support, json=body)
        assert pending.status_code == 202
        ticket = pending.json()["approval_id"]
        approved = await client.post(
            f"/api/approvals/{ticket}/decision", headers=admin, json={"decision": "approved"}
        )
        assert approved.status_code == 200
        result = await client.post("/api/tools/invoke", headers=support, json={**body, "approval_id": ticket})
        assert result.status_code == 200
        download = await client.get(result.json()["result"]["download"], headers=support)
        assert download.status_code == 200 and "[REDACTED:email]" in download.text
        replay = await client.post("/api/tools/invoke", headers=support, json={**body, "approval_id": ticket})
        assert replay.status_code == 403
        audit = await client.get("/api/audit/verify", headers=admin)
        assert audit.json()["valid"]
        readiness = (await client.get("/api/model", headers=support)).json()
        live_agent = "not_requested"
        if args.with_model:
            if not readiness["ready"]:
                raise RuntimeError("Requested live-model test, but the provider/model is unavailable")
            async with client.stream(
                "POST",
                "/api/agent/run",
                headers=support,
                json={"prompt": "Use query_records to fetch 2 tickets and report their statuses."},
                timeout=180,
            ) as response:
                response.raise_for_status()
                events = [
                    json.loads(line[6:]) async for line in response.aiter_lines() if line.startswith("data: ")
                ]
            assert any(e["type"] == "done" for e in events)
            assert any(e["type"] == "tool_result" and e["data"]["decision"] == "allow" for e in events)
            live_agent = "passed"
    async with httpx.AsyncClient(headers=support, trust_env=False) as client:
        async with streamable_http_client(base + "/mcp/", http_client=client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                assert len((await session.list_tools()).tools) == 5
                result = await session.call_tool("query_records", {"dataset": "payroll"})
                assert result.structuredContent["decision"] == "deny"
    uid = subprocess.check_output(["docker", "exec", args.container, "id", "-u"], text=True).strip()
    assert uid == "10001"
    print(
        json.dumps(
            {
                "container_verified": True,
                "uid": uid,
                "rest_authorization": "passed",
                "approval_and_csv": "passed",
                "approval_replay": "denied",
                "mcp": "passed",
                "audit_chain": "valid",
                "model_available_in_provider": readiness["ready"],
                "live_agent": live_agent,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
