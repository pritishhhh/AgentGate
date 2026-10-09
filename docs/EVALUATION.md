# Evaluation methodology

AgentGate keeps three kinds of evidence separate.

## Security invariant tests

The pytest suite checks resource/tenant isolation, argument validation, secret redaction, credential revocation, rate limiting, body/origin/host restrictions, audit visibility and tampering, policy-version conflicts, approval binding/expiry, concurrent replay, actual HTTP connector execution, and official MCP SDK interoperability. A scripted adversarial planner is used only in unit tests to force an unauthorized tool attempt through the live runner. Production uses a real configured provider.

## Forced-tool authorization ablation

`agentgate benchmark` creates fresh synthetic data in a temporary directory. Its 64 cases cover 10 distinct families:

- Unauthorized support payroll query: 10 row-limit variations.
- Unauthorized finance ticket query: 10 variations.
- Unauthorized payroll export by support: 10 variations.
- Cross-tenant document read: 1 case.
- Restricted finance document read: 1 case.
- Permitted support query, finance query, and support search: 10 variations each.
- Permitted support document read and public document read: 1 case each.

The unsafe baseline directly invokes the executor with authorization and approval removed. The protected condition invokes the shared gateway. Dataset/resource-label access defines unauthorized execution; counting redacted sensitive strings alone would miss unauthorized access to non-identifier payroll values.

The report contains unauthorized-execution rates, legitimate completion, false-block rate, full gateway duration, p95, scenario-level outcomes, and audit-chain verification. The timing wraps the full gateway invocation, including audit persistence. It excludes model planning, client network transit, and the unsafe baseline. It is **not an isolated estimate of gateway overhead**.

No model participates in this ablation. The results do not measure prompt-injection attack success, recall of an injection classifier, real-company performance, or enterprise scalability. Repeated limits vary parameters; they are not independent novel attack techniques.

## Live-model smoke verification

`scripts/verify_live.py` uses the configured provider without a scripted planner. It asks a real model to query permitted tickets, attempt a prohibited payroll query, and request an export. The report records observed tool choices, decisions, model answers, duration, and completion. If the model refuses a prohibited query before issuing a tool call, the report describes a refusal; it does not invent a gateway block.

Live-model output is stochastic and hardware-sensitive even at temperature zero. The smoke suite supports operational compatibility claims, not broad security claims. Larger experiments need a fixed model digest, prompt corpus, attack taxonomy, multiple runs, explicit leakage criteria, and a holdout set.

## Résumé wording

After reproducing the reports, a defensible description is:

> Built a real-time agent tool gateway with REST/MCP integration, tenant-scoped authorization, single-use human approvals, output redaction, and HMAC-linked audit evidence; evaluated 64 forced tool-call scenarios across 10 families and verified live local-model tool calling.

Only state a block/completion percentage that matches your generated report, and qualify it as a synthetic authorization evaluation. Do not convert those results into a universal prompt-injection prevention claim.

