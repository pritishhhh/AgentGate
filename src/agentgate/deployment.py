import ipaddress
from urllib.parse import urlsplit


def backend_origin(value: str) -> str:
    url = urlsplit(value)
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
    return value.rstrip("/")
