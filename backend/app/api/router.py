from fastapi import APIRouter

from app.api.routers import auth
from app.api.routers import blacklist, config, history, run, runs
from app.api.routers import provider_logs
from app.api.routers import zeliq

api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router, tags=["auth"])
api_router.include_router(config.router, tags=["config"])
api_router.include_router(blacklist.router, tags=["blacklist"])
api_router.include_router(history.router, tags=["history"])
api_router.include_router(runs.router, tags=["runs"])
api_router.include_router(run.router, tags=["run"])
api_router.include_router(provider_logs.router, tags=["provider-logs"])
api_router.include_router(zeliq.router, tags=["zeliq"])
