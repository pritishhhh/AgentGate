# Hosting AgentGate

The local dashboard is at http://127.0.0.1:8000. Docker packages the entire backend and dashboard together. The backend needs a persistent writable `AGENTGATE_DATA_DIR` containing SQLite, the audit key, credentials, and exports. Run one application worker; back up that directory together.

## Vercel frontend with a persistent backend

### Import the repository through the Vercel dashboard

Keep the **FastAPI** application preset and root directory `./`. The root `app.py` exports the FastAPI frontend instance and `pyproject.toml` declares `tool.vercel.entrypoint = "app:app"`. This fixes the "No FastAPI entrypoint found" build failure. Leave build/output overrides unset for this preset.

This entrypoint serves the dashboard, a public read-only sandbox, and the full-backend API/MCP proxy. The login page exposes a deliberately public visitor token and a copy button. That token routes to `/demo/api/...` and opens an isolated synthetic tenant using the same `Gateway.invoke` enforcement and an in-memory SQLite store. It can execute document reads/search and dataset queries immediately, even without a hosted full backend.

The public demo has no administrator identities, no filesystem exports, no writes/approvals, no HTTP connector permission and no live model calls. Its database, audit key, and audit history are ephemeral per function instance. Each tool response includes its actual audit record so the browser can display the decisions for its own session even when subsequent requests land on another instance. These are real evaluated tool calls, not generated example audit rows. The UI labels synthetic resources, read-only access and unavailable live AI explicitly. Operator state is never created or copied into this database.

Private operator requests at `/api/...` still return **Backend not connected** (HTTP 503) until a full backend URL is configured. Public demo tokens do not authenticate against the private backend, and private operator tokens do not authenticate against the demo.

After hosting the persistent backend, add `AGENTGATE_BACKEND_URL=https://your-backend-host` to the Vercel project's environment variables and redeploy. Use the backend's real HTTPS origin with no path, query string, or credentials. The backend must allow the frontend's exact Origin. Use credentials issued by that backend; laptop credentials only work if its existing database is securely migrated. Do not put AgentGate login tokens in Vercel build configuration.

The full-backend proxy forwards only authentication/protocol headers, bounds request bodies, rejects upstream redirects, and streams tool/agent/audit responses. Private identity, permission, approval and audit decisions remain in that backend. Its proxy can run within Vercel function-duration limits; the full-backend audit UI reconnects when a stream ends. The public sandbox records only real demo decisions for the current browser session and does not present its transient audit as durable security evidence.

### Backend hosting requirements

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

This alternative creates `.vercel/output/config.json` and four explicitly selected static files using Vercel's [Build Output API](https://vercel.com/docs/build-output-api). The origin must use HTTPS, contain no credentials, and point to your actual backend. The build does not upload anything. With the Vercel CLI installed and linked to your own project, `vercel deploy --prebuilt` uploads that prepared frontend. The dashboard import described above instead uses the new FastAPI frontend/proxy entrypoint; neither method hosts the stateful execution backend inside Vercel.

Before sharing the deployed URL, verify login, a denied tool, approval/replay, CSV downloads, authenticated MCP calls, and SSE streams through the public proxy. Check frontend-origin and backend-host headers on your actual deployment; list both explicitly if the hosting proxy preserves the frontend Host header. Preview domains require their own exact origin entries. Proxy timeout limits may reconnect the audit stream or limit long agent runs. The frontend bundle is locally verified; no public Vercel deployment is claimed as tested.

## Entire backend on Vercel

A full serverless edition would replace SQLite with a shared database, exports with object storage, and the local audit key with managed durable key material. Approval consumption and rate limits must remain atomic across workers; audit updates need ordering/transaction guarantees. It would also require a remotely reachable model provider and request-duration checks. Merely moving the existing data directory to temporary function storage would lose security state and is insufficient.
