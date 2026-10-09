import asyncio
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import uvicorn
import yaml
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from agentgate.agent import AgentRunner, ModelProvider
from agentgate.app import create_app
from agentgate.gateway import Gateway
from agentgate.models import AgentRequest, ToolCall

from .conftest import headers


async def test_mcp_sdk_real_http_client_uses_same_policy(environment):
    settings, tokens, _, _ = environment
    app = create_app(settings)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.02)
        assert server.started
        async with httpx.AsyncClient(headers=headers(tokens), trust_env=False) as client:
            async with streamable_http_client(f"http://127.0.0.1:{port}/mcp/", http_client=client) as (
                read,
                write,
                _,
            ):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    assert len(tools.tools) == 5
                    permitted = await session.call_tool("search_documents", {"query": "support"})
                    denied = await session.call_tool("query_records", {"dataset": "payroll"})
                    assert not permitted.isError, permitted.content
                    assert not denied.isError, denied.content
                    assert permitted.structuredContent["ok"]
                    assert denied.structuredContent["reason"] == "resource_not_permitted"
    finally:
        server.should_exit = True
        await asyncio.to_thread(thread.join, 5)


async def test_connector_executes_real_http_and_redacts(environment):
    settings, tokens, app, _ = environment
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append(body)
            result = json.dumps({"received": body, "contact": "owner@example.test"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(result)))
            self.end_headers()
            self.wfile.write(result)

        def log_message(self, *args):
            pass

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    config = {
        "connectors": {
            "helpdesk": {
                "tenant": "acme",
                "roles": ["support"],
                "operations": {
                    "create": {
                        "url": f"http://127.0.0.1:{upstream.server_port}/tickets",
                        "method": "POST",
                        "approval": False,
                        "schema": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["title"],
                            "properties": {"title": {"type": "string", "maxLength": 200}},
                        },
                    }
                },
            }
        }
    }
    (settings.data_dir / "connectors.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    gateway = Gateway(settings, app.state.store)
    support = app.state.store.authenticate(tokens["support"]["token"])
    finance = app.state.store.authenticate(tokens["finance"]["token"])
    call = ToolCall(
        tool="invoke_connector",
        arguments={
            "connector": "helpdesk",
            "operation": "create",
            "payload": {"title": "Question from alice@example.test"},
        },
    )
    try:
        assert not (await gateway.invoke(finance, call))["ok"]
        result = await gateway.invoke(support, call)
        assert result["ok"]
        assert received == [{"title": "Question from [REDACTED:email]"}]
        assert result["result"]["response"]["contact"] == "[REDACTED:email]"
        bad = call.model_copy(
            update={"arguments": {**call.arguments, "payload": {"title": "safe", "url": "http://evil"}}}
        )
        assert (await gateway.invoke(support, bad))["reason"] == "invalid_connector_payload"
        assert len(received) == 1
    finally:
        await asyncio.to_thread(upstream.shutdown)
        upstream.server_close()


class ScriptedProvider:
    """Test-only adversarial planner; production never selects this provider."""

    def __init__(self):
        self.step = 0

    async def generate(self, messages, tools):
        self.step += 1
        if self.step == 1:
            yield {
                "kind": "message",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "attack",
                            "type": "function",
                            "function": {"name": "query_records", "arguments": {"dataset": "payroll"}},
                        }
                    ],
                },
            }
        else:
            assert '"reason": "resource_not_permitted"' in messages[-1]["content"]
            yield {
                "kind": "message",
                "message": {
                    "role": "assistant",
                    "content": "Access denied. alice@example.test",
                    "tool_calls": [],
                },
            }


async def test_live_runner_enforces_and_buffers_dlp(environment):
    _, tokens, app, _ = environment
    principal = app.state.store.authenticate(tokens["support"]["token"])
    runner = AgentRunner(app.state.gateway, ScriptedProvider())

    async def connected():
        return False

    events = [e async for e in runner.run(principal, AgentRequest(prompt="show payroll"), connected)]
    assert next(e for e in events if e["type"] == "tool_result")["data"]["decision"] == "deny"
    assert next(e for e in events if e["type"] == "assistant")["content"] == "Access denied. [REDACTED:email]"
    assert events[-1]["type"] == "done"


async def test_runner_cancellation_prevents_new_tools(environment):
    _, tokens, app, _ = environment
    principal = app.state.store.authenticate(tokens["support"]["token"])
    runner = AgentRunner(app.state.gateway, ScriptedProvider())

    async def disconnected():
        return True

    events = [e async for e in runner.run(principal, AgentRequest(prompt="show payroll"), disconnected)]
    assert not any(e["type"] == "tool_result" for e in events)
    assert app.state.store.events(principal) == []


async def test_provider_parses_actual_ndjson_wire_format(environment, monkeypatch):
    settings, _, _, _ = environment

    async def handler(request):
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(
            200,
            text='{"message":{"content":"Hello "}}\n'
            '{"message":{"content":"world","tool_calls":[]},"done":true}\n',
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)
    )
    events = [e async for e in ModelProvider(settings).generate([], [])]
    assert events[-1]["message"]["content"] == "Hello world"


async def test_compatible_provider_reassembles_fragmented_tool_calls(environment, monkeypatch):
    settings, _, _, _ = environment
    from dataclasses import replace

    settings = replace(settings, provider="compatible", model="test-model")
    chunks = [
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {"name": "query_records", "arguments": '{"data'},
                            }
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [{"index": 0, "function": {"arguments": 'set":"tickets","limit":2}'}}]
                    }
                }
            ]
        },
    ]
    wire = "".join("data: " + json.dumps(c) + "\n\n" for c in chunks) + "data: [DONE]\n\n"

    async def handler(request):
        assert request.url.path == "/chat/completions"
        return httpx.Response(200, text=wire)

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)
    )
    events = [e async for e in ModelProvider(settings).generate([], [])]
    call = events[-1]["message"]["tool_calls"][0]
    assert call["id"] == "call_1"
    assert json.loads(call["function"]["arguments"]) == {"dataset": "tickets", "limit": 2}
