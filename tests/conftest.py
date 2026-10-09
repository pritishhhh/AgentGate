import pytest
from fastapi.testclient import TestClient

from agentgate.app import create_app
from agentgate.bootstrap import initialize
from agentgate.config import Settings


@pytest.fixture
def environment(tmp_path):
    settings = Settings(data_dir=tmp_path, requests_per_minute=1000)
    tokens = initialize(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        yield settings, tokens, app, client


def headers(tokens, role="support"):
    return {"Authorization": "Bearer " + tokens[role]["token"]}
