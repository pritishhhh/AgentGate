"""Prepare a static Vercel frontend and fixed HTTPS proxy routes; never package runtime data."""

import ipaddress
import json
import os
import shutil
from pathlib import Path
from urllib.parse import urlsplit


def build(root: Path, backend: str):
    url = urlsplit(backend)
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path not in ("", "/")
        or url.hostname in ("localhost", "host.docker.internal")
    ):
        raise ValueError("AGENTGATE_BACKEND_URL must be a public HTTPS origin without credentials or a path")
    try:
        address = ipaddress.ip_address(url.hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("The backend must be reachable from Vercel, not a private IP")
    origin = backend.rstrip("/")
    output = root / ".vercel" / "output"
    static = output / "static"
    static.mkdir(parents=True, exist_ok=True)
    source = root / "src" / "agentgate" / "static"
    # Explicit files prevent accidental publishing of data/credentials, even if the repo grows.
    for name in ("index.html", "app.js", "style.css", "fonts.css"):
        shutil.copyfile(source / name, static / name)
    config = {
        "version": 3,
        "routes": [
            {
                "src": "/.*",
                "headers": {
                    "Cache-Control": "no-store",
                    "X-Content-Type-Options": "nosniff",
                    "X-Frame-Options": "DENY",
                    "Referrer-Policy": "no-referrer",
                    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'",
                },
                "continue": True,
            },
            {"src": "/api/(.*)", "dest": origin + "/api/$1"},
            {"src": "/mcp/(.*)", "dest": origin + "/mcp/$1"},
            {"src": "/mcp", "dest": origin + "/mcp/"},
            {"src": "/(health|docs|openapi.json)", "dest": origin + "/$1"},
            {"handle": "filesystem"},
            {"src": "/", "dest": "/index.html"},
        ],
    }
    (output / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    return output


if __name__ == "__main__":
    destination = build(Path(__file__).resolve().parents[1], os.environ.get("AGENTGATE_BACKEND_URL", ""))
    print(f"Prepared {destination}. No deployment was made; a reachable persistent backend is required.")
