# Security model

## Assets, actors, and trust boundaries

Protected assets include tenant documents, dataset records, connector credentials, approved tool side effects, exported files, and audit evidence. A tool-using model, its generated arguments, user prompts, retrieved document text, and upstream tool responses are untrusted.

The operator, admin credential holder, policy store, resource classifications, connector configuration, and gateway process are trusted. An OS-level attacker who can replace files or read the process environment is outside this model. Administrator policy changes deliberately change the boundary; no model request can grant itself that authority.

The enforcement point is `Gateway.invoke`. REST and MCP route every tool through it; the bundled agent runner has no direct executor access. External agents must likewise lack direct backend credentials/network routes. AgentGate cannot govern calls that bypass it.

## Controls and intended invariants

1. **Identity:** random tokens contain 256 bits of entropy and are stored as SHA-256 digests. Tenant, role, and agent ID are not accepted as tool arguments. Revocation is rechecked on each action.
2. **Authorization:** unlisted tools and labels default to denial. Search filters metadata before exposing content. Direct reads use the same tenant/label rules. Dataset names and query bounds are enums, not SQL strings.
3. **Approval:** tickets bind identity, tool, and normalized arguments; approval expires in 10 minutes. A database-atomic state transition permits only one consumer. Policy authorization runs even for approved calls.
4. **Connectors:** destinations/methods are operator-owned. Redirects are rejected; strict schemas prevent arbitrary payload keys. Payload and response sizes are bounded. Backend credentials never enter model context.
5. **DLP:** complete text is inspected before it is exposed to the assistant or browser. Supported patterns are applied recursively. Export cells neutralize formula prefixes. Input prompts are redacted before inference.
6. **Audit:** argument hashes replace raw tool inputs. Results and prompts are not stored in audit events. HMAC-linked records detect modification, reordering, and insertion without the MAC key.
7. **Availability:** per-identity persistent sliding-window limits; four concurrent model runs; 16 concurrent tools; bounded agent steps, upstream timeouts, and request/response lengths.
8. **Browser and transport:** localhost Host allowlist, exact Origin allowlist, server credentials required for REST/MCP, same-origin UI, CSP, and no token persistence in browser storage.

## Honest limits

- This is a single-process, SQLite-backed local gateway. It does not include SSO, OAuth resource-server discovery, TLS termination, distributed coordination, or an enterprise identity provider.
- Redaction detects selected patterns. It does not detect every secret, every national identifier, encoded content, semantic confidentiality, or arbitrary obfuscation. It is not a complete DLP product.
- Least privilege contains unauthorized actions even when prompt injection changes a model's intent. It does not guarantee correct answers or detect every injection. An action that is permitted by policy can still be undesirable.
- The credential binds an agent service identity. End-user delegation and purpose-bound scopes require additional identity infrastructure; this implementation does not infer them from a prompt.
- Operator-configured endpoints are trusted. Fixed destinations prevent a model from choosing an arbitrary URL, but an overly broad upstream operation or administrator misconfiguration can reintroduce risk. Network-level egress controls remain valuable.
- Single-use approval is an **at-most-once attempt**. If a remote operation succeeds but the connection fails, the ticket remains consumed. There is no universal exactly-once delivery guarantee. Integrate upstream idempotency keys for workflows that need safe retry.
- Audit persistence occurs before returning a tool result, but external side effects and local file creation cannot be atomically committed with audit storage. A crash or disk failure can leave a completed side effect without a returned success record.
- An HMAC chain does not detect deleting the entire tail if its latest head is not anchored externally. An attacker who obtains both the database and MAC key can rewrite evidence. Export heads to external append-only storage for stronger guarantees.
- Initial credentials are in a plaintext local bootstrap file for operator convenience. Treat `data/` as sensitive, keep it out of Git/backups/shared folders, and remove the bootstrap file after securely distributing credentials.
- Do not claim the model benchmark proves universal attack resistance. Synthetic fixtures and a deliberately unsafe ablation do not establish real-world coverage.

## Deployment boundary

The default server binds to localhost. Remote deployment needs TLS, a configured Host allowlist, identity provisioning, protected secret storage, restrictive egress, backups, log retention, and resource limits. Keep the model and tool backends private. Use only your own or authorized systems for security evaluations.

## Reporting a problem

Open a repository issue with a minimal reproduction containing synthetic data. Exclude credentials, personal records, and private connector URLs. A security fix should include a failing boundary test before the implementation change.

