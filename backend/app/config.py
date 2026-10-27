"""Config loader: config/app.yaml, then APP__SECTION__KEY environment overrides.

Secrets (admin password, API keys) come only from the environment or .env.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = BACKEND_DIR / "config" / "app.yaml"
ENV_PREFIX = "APP__"


class AppSection(BaseModel):
    name: str = "enterprise-knowledge-assistant"
    version: str = "0.1.0"
    log_level: str = "INFO"


class ApiSection(BaseModel):
    cors_origins: list[str] = Field(default_factory=list)


class PathsSection(BaseModel):
    data_dir: str = "data"
    knowledge_db: str = "data/knowledge.db"
    business_db: str = "data/business.db"
    observability_db: str = "data/observability.db"

    def resolve(self, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else BACKEND_DIR / path


class QdrantSection(BaseModel):
    url: str = "http://localhost:6333"
    collection: str = "chunks"
    timeout_s: float = 2.0


class HealthSection(BaseModel):
    timeout_s: float = 2.0


class Secrets(BaseModel):
    admin_user: str = "admin"
    admin_password: str | None = None
    portkey_api_key: str | None = None
    llm_api_key: str | None = None
    gemini_api_key: str | None = None

    @classmethod
    def from_env(cls) -> Secrets:
        return cls(
            admin_user=os.getenv("ADMIN_USER") or "admin",
            admin_password=os.getenv("ADMIN_PASSWORD") or None,
            portkey_api_key=os.getenv("PORTKEY_API_KEY") or None,
            llm_api_key=os.getenv("LLM_API_KEY") or None,
            gemini_api_key=os.getenv("GEMINI_API_KEY") or None,
        )


class Config(BaseModel):
    """Typed sections for the service; other owners' sections stay as raw dicts."""

    model_config = ConfigDict(extra="allow")

    app: AppSection = Field(default_factory=AppSection)
    api: ApiSection = Field(default_factory=ApiSection)
    paths: PathsSection = Field(default_factory=PathsSection)
    qdrant: QdrantSection = Field(default_factory=QdrantSection)
    health: HealthSection = Field(default_factory=HealthSection)
    secrets: Secrets = Field(default_factory=Secrets, exclude=True)

    def get(self, dotted: str, default: Any = None) -> Any:
        """Read any key by its contract name, for example get("obs.grounding_min")."""
        node: Any = self.model_dump()
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node


def _parse_env_value(raw: str) -> Any:
    # YAML parsing turns "0.8" into a float and "true" into a bool, like the file does.
    return yaml.safe_load(raw) if raw != "" else ""


def _apply_env_overrides(data: dict[str, Any], environ: dict[str, str]) -> None:
    for key, raw in environ.items():
        if not key.startswith(ENV_PREFIX):
            continue
        parts = [p.lower() for p in key[len(ENV_PREFIX):].split("__") if p]
        if not parts:
            continue
        node = data
        for part in parts[:-1]:
            child = node.get(part)
            if not isinstance(child, dict):
                child = {}
                node[part] = child
            node = child
        node[parts[-1]] = _parse_env_value(raw)


def load_config(path: Path | None = None, environ: dict[str, str] | None = None) -> Config:
    load_dotenv(BACKEND_DIR.parent / ".env", override=False)   # the repo-root .env that Compose also reads
    config_path = path or Path(os.getenv("APP_CONFIG", DEFAULT_CONFIG_PATH))
    with open(config_path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    _apply_env_overrides(data, dict(os.environ) if environ is None else environ)
    config = Config.model_validate(data)
    config.secrets = Secrets.from_env()
    return config


@lru_cache(maxsize=1)
def get_config() -> Config:
    return load_config()
