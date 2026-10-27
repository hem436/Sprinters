from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import DEFAULT_CONFIG_PATH, Config, Secrets, load_config
from app.main import create_app


@pytest.fixture
def config(tmp_path: Path) -> Config:
    env = {
        "APP__PATHS__OBSERVABILITY_DB": str(tmp_path / "observability.db"),
        "APP__PATHS__KNOWLEDGE_DB": str(tmp_path / "knowledge.db"),
        "APP__PATHS__BUSINESS_DB": str(tmp_path / "business.db"),
        # Nothing listens here, so the Qdrant check fails fast.
        "APP__QDRANT__URL": "http://127.0.0.1:9",
        "APP__HEALTH__TIMEOUT_S": "0.5",
    }
    cfg = load_config(DEFAULT_CONFIG_PATH, environ=env)
    cfg.secrets = Secrets(portkey_api_key="pk-test")
    return cfg


@pytest.fixture
def client(config: Config) -> TestClient:
    return TestClient(create_app(config), raise_server_exceptions=False)
