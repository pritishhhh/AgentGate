"""Create a submission archive from an explicit allowlist; never include runtime credentials or models."""

import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
output = root / "artifacts" / "AgentGate-source.zip"
allowed_files = [
    "README.md",
    "LICENSE",
    "pyproject.toml",
    "requirements.lock",
    "Dockerfile",
    "compose.yaml",
    ".dockerignore",
    ".gitignore",
    ".env.example",
]
allowed_directories = ["src", "tests", "examples", "scripts", "docs", ".github"]
paths = [root / name for name in allowed_files]
for name in allowed_directories:
    paths.extend(
        path for path in (root / name).rglob("*") if path.is_file() and "__pycache__" not in path.parts
    )
for name in (
    "evaluation.json",
    "live-model.json",
    "live-workflows.json",
    "dashboard.png",
    "agent-console.png",
    "tool-lab.png",
    "mobile.png",
    "login.png",
):
    paths.append(root / "artifacts" / name)
output.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(set(paths)):
        if path.is_file():
            relative = path.relative_to(root)
            if any(part in ("data", ".runtime", ".venv", ".git") for part in relative.parts):
                raise RuntimeError("Refusing to package a protected runtime path")
            archive.write(path, relative.as_posix())
print(
    f"Created {output.name}: {output.stat().st_size:,} bytes. Runtime data, models, and credentials excluded."
)
