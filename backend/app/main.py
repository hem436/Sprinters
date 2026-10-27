"""FastAPI app. Run locally: uvicorn app.main:app --reload (from backend/)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, documents, health, metrics, query, tools
from app.api.errors import install_error_handlers
from app.api.request_id import HEADER, RequestIdMiddleware
from app.config import Config, get_config
from app.logging_setup import setup_logging
from app.observability import store

log = logging.getLogger(__name__)


def create_app(config: Config | None = None) -> FastAPI:
    override = config is not None
    config = config or get_config()
    setup_logging(config.app.log_level)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        db_path = config.paths.resolve(config.paths.observability_db)
        try:
            store.init_db(db_path)
            store.seed_prices(db_path, store.load_price_file())
        except Exception:
            # The API still serves answers; /health shows the store as down.
            log.exception("could not prepare observability.db")
        yield

    app = FastAPI(title="Enterprise Knowledge Assistant", version=config.app.version, lifespan=lifespan)
    if override:
        # Tests pass their own config; routes read it through the same dependency.
        app.dependency_overrides[get_config] = lambda: config

    install_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.api.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[HEADER],
    )
    # Added last so it runs outermost: CORS and error responses get the id too.
    app.add_middleware(RequestIdMiddleware)

    for module in (health, auth, query, documents, metrics, tools):
        app.include_router(module.router)
    return app


app = create_app()
