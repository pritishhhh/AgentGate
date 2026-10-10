import json
import math
import statistics
import tempfile
import time
from pathlib import Path

from .bootstrap import initialize
from .config import Settings
from .control_evaluation import evaluate_controls
from .gateway import TOOL_MODELS, Gateway
from .models import ToolCall
from .store import Store


async def evaluate(output: Path):
    """Authorization ablation with forced tool calls, not a model prompt-injection success benchmark."""
    with tempfile.TemporaryDirectory(prefix="agentgate-evaluation-") as directory:
        settings = Settings(data_dir=Path(directory), requests_per_minute=10000)
        tokens = initialize(settings.data_dir)
        store = Store(settings.data_dir)
        gateway = Gateway(settings, store)
        support = store.authenticate(tokens["support"]["token"])
        finance = store.authenticate(tokens["finance"]["token"])
        cases = []
        for limit in range(1, 11):
            cases.extend(
                [
                    (
                        "support_to_payroll",
                        support,
                        "query_records",
                        {"dataset": "payroll", "limit": limit},
                        False,
                    ),
                    (
                        "finance_to_tickets",
                        finance,
                        "query_records",
                        {"dataset": "tickets", "limit": limit},
                        False,
                    ),
                    (
                        "unauthorized_export",
                        support,
                        "export_report",
                        {"dataset": "payroll", "limit": limit},
                        False,
                    ),
                    (
                        "permitted_support_query",
                        support,
                        "query_records",
                        {"dataset": "tickets", "limit": limit},
                        True,
                    ),
                    (
                        "permitted_finance_query",
                        finance,
                        "query_records",
                        {"dataset": "payroll", "limit": limit},
                        True,
                    ),
                    (
                        "permitted_search",
                        support,
                        "search_documents",
                        {"query": "support", "limit": limit},
                        True,
                    ),
                ]
            )
        cases.extend(
            [
                ("cross_tenant_document", support, "read_document", {"document_id": "other-tenant"}, False),
                ("restricted_document", support, "read_document", {"document_id": "payroll-policy"}, False),
                ("permitted_document", support, "read_document", {"document_id": "support-guide"}, True),
                ("permitted_public_document", finance, "read_document", {"document_id": "welcome"}, True),
            ]
        )
        records = []
        for family, principal, tool, arguments, permitted in cases:
            args = TOOL_MODELS[tool][0].model_validate(arguments)
            labels = gateway.policy().classifications.get(principal.role, [])
            # Explicit unsafe baseline: bypass ONLY authorization/approval for synthetic disposable data.
            # It is unreachable over REST or MCP and never used by the live agent.
            baseline = await gateway.execute(principal, tool, args, labels)
            start = time.perf_counter()
            protected = await gateway.invoke(principal, ToolCall(tool=tool, arguments=arguments))
            duration = (time.perf_counter() - start) * 1000
            records.append(
                {
                    "family": family,
                    "expected_permitted": permitted,
                    "tool": tool,
                    "arguments": arguments,
                    "baseline_executed": baseline is not None,
                    "protected_decision": protected["decision"],
                    "reason": protected.get("reason"),
                    "end_to_end_ms": round(duration, 3),
                }
            )
        attacks = [r for r in records if not r["expected_permitted"]]
        legitimate = [r for r in records if r["expected_permitted"]]
        latencies = sorted(r["end_to_end_ms"] for r in records)
        controls = await evaluate_controls(gateway, store, tokens)
        report = {
            "benchmark": "forced-tool authorization ablation",
            "cases": len(records),
            "attack_cases": len(attacks),
            "legitimate_cases": len(legitimate),
            "distinct_families": len({r["family"] for r in records}),
            "baseline_unauthorized_execution_rate": sum(r["baseline_executed"] for r in attacks)
            / len(attacks),
            "protected_unauthorized_execution_rate": sum(r["protected_decision"] == "allow" for r in attacks)
            / len(attacks),
            "legitimate_completion_rate": sum(r["protected_decision"] == "allow" for r in legitimate)
            / len(legitimate),
            "false_block_rate": sum(r["protected_decision"] != "allow" for r in legitimate) / len(legitimate),
            "mean_end_to_end_ms": round(statistics.mean(latencies), 3),
            "p95_end_to_end_ms": latencies[math.ceil(len(latencies) * 0.95) - 1],
            "stateful_controls": controls,
            "audit_chain": store.verify_audit(),
            "limitations": [
                "Synthetic data; 10 scenario families with parameter variations.",
                "Forced tool calls measure authorization, not whether an LLM follows an injected prompt.",
                "The unsafe baseline deliberately removes authorization; it is not a production comparison.",
                "Timing includes local tool work and audit persistence; excludes model inference and network clients.",
            ],
            "results": records,
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    summary = {k: v for k, v in report.items() if k not in ("results", "stateful_controls")}
    summary["stateful_controls"] = {k: v for k, v in controls.items() if k != "results"}
    return summary
