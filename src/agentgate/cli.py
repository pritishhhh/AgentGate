import argparse
import asyncio
import json
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

from .bootstrap import initialize
from .config import Settings
from .evaluation import evaluate
from .store import Store


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="AgentGate security gateway")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Initialize policy, credentials, and synthetic example data")
    init.add_argument("--no-seed", action="store_true", help="Start with an empty document/record store")
    credentials = commands.add_parser(
        "credentials", help="Read an initial credential locally; never use in shared logs"
    )
    credentials.add_argument("--role", choices=["admin", "support", "finance"], required=True)
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
    ingest.add_argument("--classification", choices=["public", "support", "finance"], required=True)
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.command == "init":
        initialize(settings.data_dir, seed=not args.no_seed)
        print(f"Initialized {settings.data_dir}. Initial credentials are in credentials.json (Git-ignored).")
        print("Use agentgate credentials --role support to view an initial credential locally.")
    elif args.command == "credentials":
        content = json.loads((settings.data_dir / "credentials.json").read_text(encoding="utf-8"))
        print(content[args.role]["token"])
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
        print(json.dumps(asyncio.run(evaluate(args.output)), indent=2))
    elif args.command == "doctor":
        from .agent import ModelProvider

        print(json.dumps(asyncio.run(ModelProvider(settings).check()), indent=2))
    elif args.command == "ingest":
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
