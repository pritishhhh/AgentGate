import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

from .bootstrap import initialize
from .config import Settings
from .evaluation import evaluate
from .models import DatasetDefinition, Identifier
from .store import Store
from .workflows import enable_example_policy


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="AgentGate security gateway")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Initialize policy, credentials, and synthetic example data")
    init.add_argument("--no-seed", action="store_true", help="Start with an empty document/record store")
    credentials = commands.add_parser(
        "credentials", help="Read an initial credential locally; never use in shared logs"
    )
    credentials.add_argument("--role", required=True)
    credentials.add_argument(
        "--copy", action="store_true", help="Copy to the Windows clipboard without displaying the token"
    )
    commands.add_parser(
        "examples",
        help="Add developer/analyst example policy, data and local credentials without replacing existing tokens",
    )
    dataset = commands.add_parser(
        "register-dataset", help="Register immutable trusted dataset metadata from a JSON definition"
    )
    dataset.add_argument("path", type=Path)
    serve = commands.add_parser("serve", help="Serve dashboard, REST API, and MCP")
    serve.add_argument("--port", type=int, default=8000)
    commands.add_parser("verify-audit", help="Verify the HMAC audit chain")
    benchmark = commands.add_parser("benchmark", help="Run an isolated authorization ablation")
    benchmark.add_argument("--output", type=Path, default=Path("artifacts/evaluation.json"))
    commands.add_parser("doctor", help="Check model provider readiness")
    ingest = commands.add_parser("ingest", help="Import a UTF-8 text/Markdown document with trusted labels")
    ingest.add_argument("path", type=Path)
    ingest.add_argument("--id", required=True)
    ingest.add_argument("--tenant", required=True)
    ingest.add_argument("--classification", required=True)
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.command == "init":
        initialize(settings.data_dir, seed=not args.no_seed)
        print(f"Initialized {settings.data_dir}. Initial credentials are in credentials.json (Git-ignored).")
        print("Use agentgate credentials --role support to view an initial credential locally.")
    elif args.command == "credentials":
        content = json.loads((settings.data_dir / "credentials.json").read_text(encoding="utf-8"))
        if args.role not in content:
            parser.error(
                "No bootstrap credential for this role; issue one through the administrator dashboard"
            )
        token = content[args.role]["token"]
        if Store(settings.data_dir).authenticate(token) is None:
            parser.error("Credential is revoked; issue a new one through the administrator dashboard")
        if args.copy:
            if sys.platform != "win32":
                parser.error("--copy currently supports Windows; use your OS clipboard utility")
            subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    "$value = [Console]::In.ReadToEnd(); Set-Clipboard -Value $value",
                ],
                input=token,
                text=True,
                check=True,
                capture_output=True,
            )
            print(f"Copied the {args.role} credential. Paste into the dashboard Access token field.")
        else:
            print(token)
    elif args.command == "examples":
        initialize(settings.data_dir)
        store = Store(settings.data_dir)
        enable_example_policy(store)
        credential_path = settings.data_dir / "credentials.json"
        content = json.loads(credential_path.read_text(encoding="utf-8")) if credential_path.exists() else {}
        for role in ("developer", "analyst"):
            if not any(p["role"] == role and p["tenant"] == "acme" for p in store.principals()):
                principal, token = store.issue(f"{role.title()} operator", role, "acme")
                content[role] = {"principal_id": principal.id, "token": token}
        credential_path.write_text(json.dumps(content, indent=2), encoding="utf-8")
        print("Installed example workflows. Existing credentials and records preserved.")
    elif args.command == "register-dataset":
        from .datasets import validate_definition

        definition = DatasetDefinition.model_validate_json(args.path.read_text(encoding="utf-8"))
        validate_definition(definition)
        if not Store(settings.data_dir).add_dataset(definition):
            parser.error("Dataset already exists; trusted catalog entries cannot be overwritten")
        print(f"Registered {definition.name} for tenant {definition.tenant}.")
    elif args.command == "serve":
        if Store(settings.data_dir).get_setting("policy") is None:
            parser.error("Run agentgate init before serving")
        from .app import create_app

        uvicorn.run(create_app(settings), host="127.0.0.1", port=args.port, log_level="info")
    elif args.command == "verify-audit":
        report = Store(settings.data_dir).verify_audit()
        print(json.dumps(report, indent=2))
        if not report["valid"]:
            raise SystemExit(1)
    elif args.command == "benchmark":
        report = asyncio.run(evaluate(args.output))
        print(json.dumps(report, indent=2))
        if (
            not report["stateful_controls"]["all_passed"]
            or report["protected_unauthorized_execution_rate"]
            or report["false_block_rate"]
        ):
            raise SystemExit(1)
    elif args.command == "doctor":
        from .agent import ModelProvider

        print(json.dumps(asyncio.run(ModelProvider(settings).check()), indent=2))
    elif args.command == "ingest":
        from pydantic import TypeAdapter

        TypeAdapter(Identifier).validate_python(args.classification)
        if args.path.stat().st_size > 262144:
            parser.error("Documents must be no larger than 256 KiB")
        content = args.path.read_text(encoding="utf-8")
        store = Store(settings.data_dir)
        with store.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO documents VALUES(?,?,?,?,?)",
                (args.id, args.tenant, args.classification, args.path.stem, content),
            )
        print(f"Imported {args.id} for tenant {args.tenant}, classification {args.classification}.")


if __name__ == "__main__":
    main()
