# A five-minute walkthrough

1. **Explain the boundary (30 seconds).** The model chooses actions; credentials, resource labels, and deterministic policy authorize them. Show the architecture diagram and identify the shared REST/MCP enforcement function.
2. **Run a legitimate task (60 seconds).** Log in as support, ask for the escalation guide, and show the real model's tool calls, redacted result, and audit entry.
3. **Prove a denial (45 seconds).** In Tool Lab, query payroll or read `other-tenant`. Show the denial and the absence of resource contents. Explain why caller-supplied identity fields are rejected.
4. **Show consequential-action control (90 seconds).** Request `export_report` with `{ "dataset": "tickets", "limit": 5 }`. In a separate admin session, approve the ticket. Retry the exact arguments with that ticket, download the redacted CSV, and demonstrate replay denial.
5. **Connect a real agent (30 seconds).** Run `examples/mcp_client.py` to show SDK initialization, discovery, an allowed tool, and a denied tool over actual HTTP.
6. **Present evidence and limits (45 seconds).** Show the pytest results and evaluation JSON. Clearly distinguish forced authorization cases from live-model prompts. Explain regex DLP limitations and the need for private backend network routes.

## Questions to prepare for

The general-purpose workflow extension is demonstrated in [WORKFLOWS.md](WORKFLOWS.md): development issue creation and incident triage use the same authorization and approval boundary as document assistance. Show a custom role/dataset to explain how the project adapts to different applications. Choose live-model tasks that actually completed on your machine; use the Tool Lab to inspect the deterministic controls independently.

- Why is an LLM-based allow/deny classifier insufficient as the authorization boundary?
- How does tenant isolation apply to search as well as direct document reads?
- What prevents changing tool arguments after an approval?
- What happens when two workers attempt to consume the same ticket?
- What happens when the tool succeeds but the network response fails?
- Why buffer assistant text before displaying it?
- What does the audit chain detect, and what does it not detect?
- How would you extend this to SSO, delegated users, distributed workers, and externally anchored logs?

For a submission, include the README, a short screen recording, test/evaluation artifacts, and a clear explanation of your own contribution. Keep credentials, model binaries, synthetic runtime databases, and private connector configuration out of the repository.

