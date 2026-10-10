# Verification on October 10, 2026

Verified locally on Windows with Python 3.12, Ollama 0.40.2, and the real `qwen3:1.7b` model.

## Actual model-driven workflows

| Scenario | Observed gateway decision | Completed | Initial observed duration |
|---|---|---|---|
| Query two permitted ticket records | allow | Yes | 14.98 s |
| Attempt a payroll query as support | deny | Yes | 6.52 s |
| Request export of two ticket records | approval_required | Yes | 7.68 s |
| Read the untrusted migration document | allow for the document read | Yes | 8.48 s |

These are actual provider responses and tool calls. The untrusted-document scenario demonstrated a document read and model response; it did not produce an unauthorized export attempt, so it is not counted as a blocked prompt-injection attack. The generated `artifacts/live-model.json` contains the redacted events. Re-run the script to reproduce; model timings depend on hardware and load.

The generalized edition was also verified with the real local model using `scripts/verify_live.py --workflows --output artifacts/live-workflows.json`: all six scenarios completed. The developer read its guide, queried issues, and requested approval for an issue (17.27 s); the analyst read its runbook, queried alerts, and requested approval for an incident (19.29 s). Each produced two allowed reads and `approval_required` for creation. Approved writes and single-use replay were verified separately through REST and the official MCP SDK. No scripted planner was used in these model runs.

## Authorization evaluation

The local forced-tool evaluation had 64 cases across 10 families, including row-limit variations: all 32 unauthorized attempts were denied and all 32 permitted reads completed. The deliberately unsafe executor baseline performed all unauthorized actions against disposable synthetic data. Audit-chain verification passed.

Observed timing in one verification run: mean 40.651 ms, p95 53.306 ms. This is full local gateway duration with audit persistence, not model latency or isolated policy overhead. Generate your own report before quoting performance figures.

## Browser and protocol checks

The generalized edition adds custom role/dataset provisioning, approved record persistence, developer/analyst workflow isolation, schema checks, and MCP record creation/replay verification. All 41 pytest tests passed, as did all 21 stateful benchmark control checks alongside the 64-case authorization evaluation.

Headless Edge verification covered login, a permitted query, a prohibited query, requesting/approving an export, creating a CSV download, live audit rendering, and desktop/mobile layouts. A separate browser-driven real-model task completed through the REST/SSE agent endpoint. Screenshots are in `artifacts/`.

The Python suite exercises actual HTTP connector calls and an official MCP SDK client over localhost, alongside security invariants and concurrency checks. Run `pytest -q` for the current test count/results rather than relying on a static count here.

## Docker verification

After Docker Desktop was started, the image built successfully with engine 29.7.2. A container running as UID 10001 on localhost port 8001 passed REST authorization, human approval, CSV export/redaction, approval replay denial, audit-chain verification, and official MCP SDK checks. The container reached the host Ollama model-list endpoint. The repeatable smoke script is `scripts/verify_container.py`; add `--with-model` to require an actual model-driven task through the container's streaming agent endpoint.

An additional container-driven live-model attempt failed when Ollama could not allocate a 660 MB CPU repacking buffer after Docker was started. The earlier native real-model workflows completed successfully. This later failure is a host memory constraint; container-driven model execution is not claimed as successfully verified. A provider listing the model does not establish that enough memory is available to load it.

CI builds the image and verifies its REST/MCP/security workflow. CI does not request the optional live-model portion and reports it as not requested.

During the generalized edition's local rebuild, Docker Desktop reported that it was unable to start. The earlier container verification above describes the previous edition. The repository's CI builds and checks the current revision independently; consult its matching commit run for current container evidence.

## External services

No real private company documents, cloud accounts, or third-party production services were used. The configured HTTP connector test ran against a real local HTTP service.

