import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    provider: str = "ollama"
    model: str = "qwen3:1.7b"
    model_url: str = "http://127.0.0.1:11434"
    model_key: str = ""
    requests_per_minute: int = 120
    allowed_origins: tuple[str, ...] = ("http://127.0.0.1:8000", "http://localhost:8000")
    allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost", "testserver")

    @classmethod
    def from_env(cls):
        return cls(
            data_dir=Path(os.getenv("AGENTGATE_DATA_DIR", "data")).resolve(),
            provider=os.getenv("AGENTGATE_PROVIDER", "ollama"),
            model=os.getenv("AGENTGATE_MODEL", "qwen3:1.7b"),
            model_url=os.getenv("AGENTGATE_MODEL_URL", "http://127.0.0.1:11434").rstrip("/"),
            model_key=os.getenv("AGENTGATE_MODEL_KEY", ""),
            requests_per_minute=int(os.getenv("AGENTGATE_REQUESTS_PER_MINUTE", "120")),
            allowed_hosts=tuple(
                host.strip()
                for host in os.getenv("AGENTGATE_ALLOWED_HOSTS", "127.0.0.1,localhost,testserver").split(",")
            ),
            allowed_origins=tuple(
                os.getenv("AGENTGATE_ALLOWED_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000").split(
                    ","
                )
            ),
        )
