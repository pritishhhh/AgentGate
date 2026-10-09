"""Use AgentGate from any Python agent framework. Set AGENTGATE_TOKEN locally."""

import asyncio
import os

import httpx


async def main():
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8000", headers={"Authorization": f"Bearer {os.environ['AGENTGATE_TOKEN']}"}
    ) as client:
        response = await client.post(
            "/api/tools/invoke",
            json={"tool": "search_documents", "arguments": {"query": "support", "limit": 5}},
        )
        print(response.json())


if __name__ == "__main__":
    asyncio.run(main())
