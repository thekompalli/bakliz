from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.settings import Settings


def create_app() -> FastAPI:
    settings = Settings()

    app = FastAPI(title="BAKLIZ API", version="0.1.0")

    allow_origins = [o.strip() for o in settings.cors_allow_origins.split(",") if o.strip()]
    if allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allow_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(api_router)
    return app


app = create_app()

