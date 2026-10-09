"""A real MCP SDK client; no LLM or API key required to test the protocol."""

import asyncio
import os

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main():
    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {os.environ['AGENTGATE_TOKEN']}"}
    ) as client:
        async with streamable_http_client("http://127.0.0.1:8000/mcp/", http_client=client) as (
            read,
            write,
            _,
        ):
            async with ClientSession(read, write) as session:
                await session.initialize()
                print("Tools:", [t.name for t in (await session.list_tools()).tools])
                print(
                    "Allowed:",
                    (await session.call_tool("search_documents", {"query": "support"})).structuredContent,
                )
                print(
                    "Denied:",
                    (await session.call_tool("query_records", {"dataset": "payroll"})).structuredContent,
                )


if __name__ == "__main__":
    asyncio.run(main())
