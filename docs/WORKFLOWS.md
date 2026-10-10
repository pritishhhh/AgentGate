# Configurable agent workflows

The agent, REST clients, and MCP clients share one gateway. Roles are policy keys, not a closed set in Python. Dataset labels and writable record schemas come from an immutable operator catalog keyed by tenant and name. Tool arguments cannot change this catalog or the authenticated identity.

## Try the bundled examples

Fresh installations contain support, finance, developer, analyst, and admin identities. For an existing installation run `agentgate examples` once; it adds example policy entries and synthetic resources, preserving existing tokens and records. It increments the policy version and enables approval for `create_record`. It does not recreate revoked example identities. Retrieve local credentials with `agentgate credentials --role developer --copy` or `--role analyst --copy` on Windows. Issue replacement credentials from the admin dashboard if needed.

1. Document assistance: as support, search `support`, then read `support-guide`. Payroll and other tenants remain inaccessible.
2. Developer automation: as developer, read `developer-guide`, query `issues`, and invoke `create_record` with the request below. A pending approval is returned before any new row is written.
3. Incident response: as analyst, read `incident-runbook`, query `alerts`, and request creation of an `incidents` record. The developer's issues remain inaccessible.

```json
{"tool":"create_record","arguments":{"dataset":"issues","record":{"title":"Investigate login timeout","status":"open","category":"development"}}}
```

```json
{"tool":"create_record","arguments":{"dataset":"incidents","record":{"title":"Investigate failed sign-ins","status":"triaged","severity":"high","category":"security"}}}
```

An administrator approves the returned ticket in a separate session. Retry the exact tool/arguments with `approval_id` at the top level. The database stores the redacted record and returns its real row ID; querying the same dataset retrieves it. Changed arguments, another identity, expired tickets, and replay fail. External HTTP connectors can bridge these workflows to an operator-selected issue tracker or incident system; the bundled examples do not claim external deployments.

## Configure a new workflow

Add a role such as `researcher` to `roles` and `classifications` in the policy editor, and publish the next version. Role names use lowercase letters, digits, underscores and hyphens, starting with a letter. For example:

```json
"roles": {"researcher": ["query_records", "create_record"]},
"classifications": {"researcher": ["research"]}
```

Merge these keys with the existing policy; preserve the admin role and other entries. Create a researcher identity using the admin dashboard. Register this JSON definition through `agentgate register-dataset experiments.json`:

```json
{
  "name": "experiments", "tenant": "acme", "classification": "research",
  "record_schema": {
    "type": "object", "additionalProperties": false, "required": ["title"],
    "properties": {"title": {"type": "string", "minLength": 1, "maxLength": 200}}
  }
}
```

`record_schema: null` makes a dataset read-only through agent tools. Schemas must reject additional properties; schema references are unsupported. Existing catalog definitions cannot be overwritten. Record schemas are validated before approval and again after redaction. Keep `create_record` in `approval_tools` when writes need human review. The authenticated `GET /api/datasets` returns only metadata allowed by the current tenant/classification policy; live model runs receive this catalog as context.

Use `agentgate ingest guide.md --id research-guide --tenant acme --classification research` for corresponding documents. The reserved `admin` identity alone manages policy, approvals, and credentials; copying its resource permissions into a new role does not grant those management endpoints.
