import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import clock
from .config import settings
from .db import Base, SessionLocal, engine
from .errors import ApiError, api_error_handler
from .routers import auth, brand, creator, ops, webhooks
# Import services so their @jobs.task handlers register.
from .services import ai, audit, connections, jobs, money, scoring, tracking  # noqa: F401

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def init_db():
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        clock.load(db)
        jobs.ensure_recurring(db)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    worker = None
    if settings.worker_enabled:
        worker = jobs.Worker(interval=1.0)
        worker.start()
    yield
    if worker:
        worker.stop()


app = FastAPI(title="Flu API", version="0.1.0", lifespan=lifespan,
              description="Performance-paid UGC marketplace for India: briefs, escrow, verified views, Creator Score.")
app.add_exception_handler(ApiError, api_error_handler)
app.add_middleware(CORSMiddleware, allow_origins=[settings.web_origin], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
for r in (auth.router, creator.router, brand.router, ops.router, webhooks.router):
    app.include_router(r)
if settings.dev_mode:
    from .routers import dev
    app.include_router(dev.router)


@app.get("/health")
def health():
    return {"ok": True, "now": clock.now(), "dev_mode": settings.dev_mode, "provider_mode": settings.provider_mode,
            "ai": "live" if ai.live_enabled() else "heuristic"}
