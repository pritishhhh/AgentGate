# Hosting AgentGate

The local dashboard is at http://127.0.0.1:8000. Docker packages the entire backend and dashboard together. The backend needs a persistent writable `AGENTGATE_DATA_DIR` containing SQLite, the audit key, credentials, and exports. Run one application worker; back up that directory together.

## Vercel frontend with a persistent backend

Vercel supports [FastAPI functions](https://vercel.com/docs/frameworks/backend/fastapi), but this storage implementation is designed for a persistent server. Vercel's [file guidance](https://vercel.com/kb/guide/how-can-i-use-files-in-serverless-functions) recommends external persistent storage for writes. Localhost Ollama on your laptop is also unreachable from a public Vercel deployment.

For this edition, host the backend container on a server with a persistent mounted `/app/data` volume, HTTPS, and access to a model server. The Vercel frontend uses [external rewrites](https://vercel.com/docs/routing/rewrites) to proxy authenticated API/MCP requests to that fixed backend. The browser keeps its token in memory and never receives a model-provider credential.

Backend configuration must explicitly allow its public hostname and the frontend's exact origin:

```dotenv
AGENTGATE_DATA_DIR=/app/data
AGENTGATE_ALLOWED_HOSTS=localhost,127.0.0.1,api.your-domain.example
AGENTGATE_ALLOWED_ORIGINS=https://your-dashboard.vercel.app
AGENTGATE_MODEL_URL=http://ollama:11434
```

Replace the example domains. For model hosting, `ollama` here is an actual service on the backend's private Docker network, not your laptop loopback. Alternatively configure an accessible compatible provider. Compute and provider costs depend on the hosting service; the local setup requires no provider API key. Mount the persistent volume before initialization and keep runtime credentials out of images/Git.

Prepare a frontend-only deployment locally, using an already hosted backend:

```powershell
$env:AGENTGATE_BACKEND_URL = 'https://api.your-domain.example'
.\.venv\Scripts\python.exe scripts/build_vercel.py
```

This creates `.vercel/output/config.json` and four explicitly selected static files using Vercel's [Build Output API](https://vercel.com/docs/build-output-api). The origin must use HTTPS, contain no credentials, and point to your actual backend. The build does not upload anything. With the Vercel CLI installed and linked to your own project, `vercel deploy --prebuilt` uploads that prepared frontend. Avoid importing the Python repository as an automatic full-backend deployment for this storage edition.

Before sharing the deployed URL, verify login, a denied tool, approval/replay, CSV downloads, authenticated MCP calls, and SSE streams through the public proxy. Check frontend-origin and backend-host headers on your actual deployment; list both explicitly if the hosting proxy preserves the frontend Host header. Preview domains require their own exact origin entries. Proxy timeout limits may reconnect the audit stream or limit long agent runs. The frontend bundle is locally verified; no public Vercel deployment is claimed as tested.

## Entire backend on Vercel

A full serverless edition would replace SQLite with a shared database, exports with object storage, and the local audit key with managed durable key material. Approval consumption and rate limits must remain atomic across workers; audit updates need ordering/transaction guarantees. It would also require a remotely reachable model provider and request-duration checks. Merely moving the existing data directory to temporary function storage would lose security state and is insufficient.
