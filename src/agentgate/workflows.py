"""Synthetic examples for three independently useful agent workflows."""

from .models import DatasetDefinition
from .store import canonical

WRITE_TOOLS = [
    "search_documents",
    "read_document",
    "query_records",
    "create_record",
    "export_report",
    "invoke_connector",
]


def example_schema(kind):
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["title", "status"],
        "properties": {
            "title": {"type": "string", "minLength": 1, "maxLength": 200},
            "status": {"type": "string", "enum": ["open", "triaged", "resolved"]},
            "details": {"type": "string", "maxLength": 2000},
            "severity": {"type": "string", "enum": ["low", "medium", "high"]},
            "category": {"type": "string", "enum": [kind]},
        },
    }


def seed_workflows(store):
    definitions = [
        ("tickets", "support", None),
        ("payroll", "finance", None),
        ("issues", "development", example_schema("development")),
        ("alerts", "security", None),
        ("incidents", "security", example_schema("security")),
    ]
    for tenant in ("acme", "globex"):
        for name, label, schema in definitions:
            store.add_dataset(
                DatasetDefinition(name=name, tenant=tenant, classification=label, record_schema=schema)
            )
    with store.connect() as db:
        db.executemany(
            "INSERT OR IGNORE INTO documents VALUES(?,?,?,?,?)",
            [
                (
                    "developer-guide",
                    "acme",
                    "development",
                    "Development triage guide",
                    "Read issues, describe a reproducible bug, and request approval before creating a new issue. Never run arbitrary shell commands.",
                ),
                (
                    "incident-runbook",
                    "acme",
                    "security",
                    "Incident response runbook",
                    "Review alerts, assign severity, and request approval before recording an incident. A high severity alert should be investigated by an analyst.",
                ),
            ],
        )
        for tenant in ("acme", "globex"):
            for name, record in [
                (
                    "issues",
                    {
                        "title": "Login retry fails after timeout",
                        "status": "open",
                        "category": "development",
                        "details": "Reproduce by retrying after a 30 second timeout.",
                    },
                ),
                (
                    "alerts",
                    {
                        "title": "Repeated failed sign-ins",
                        "severity": "high",
                        "source": "synthetic identity log",
                        "count": 12,
                    },
                ),
            ]:
                if not db.execute(
                    "SELECT 1 FROM records WHERE tenant=? AND dataset=?", (tenant, name)
                ).fetchone():
                    db.execute(
                        "INSERT INTO records(tenant,dataset,content) VALUES(?,?,?)",
                        (tenant, name, canonical(record)),
                    )


def enable_example_policy(store):
    policy = store.get_setting("policy")
    version = policy["version"]
    for role, label in (("developer", "development"), ("analyst", "security")):
        policy["roles"].setdefault(role, WRITE_TOOLS.copy())
        policy["classifications"].setdefault(role, ["public", label])
        if label not in policy["classifications"].get("admin", []):
            policy["classifications"].setdefault("admin", []).append(label)
    if "create_record" not in policy["roles"].get("admin", []):
        policy["roles"].setdefault("admin", []).append("create_record")
    if "create_record" not in policy["approval_tools"]:
        policy["approval_tools"].append("create_record")
    policy["version"] = version + 1
    if not store.set_policy(policy, expected_version=version):
        raise RuntimeError("Policy changed concurrently; retry the examples command")
    store.audit(
        "local-operator",
        {"tool": "example_policy_install", "decision": "allow", "policy_version": policy["version"]},
    )
