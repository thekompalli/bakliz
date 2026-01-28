from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import Settings


_engine = None
SessionLocal = sessionmaker(autocommit=False, autoflush=False)


def init_engine(database_url: str):
    global _engine
    connect_args = {}
    engine_kwargs = {}

    if database_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
        if database_url.endswith(":memory:"):
            engine_kwargs["poolclass"] = StaticPool

    _engine = create_engine(database_url, pool_pre_ping=True, connect_args=connect_args, **engine_kwargs)
    SessionLocal.configure(bind=_engine)
    return _engine


def get_engine():
    if _engine is None:
        settings = Settings()
        init_engine(settings.database_url)
    return _engine


def get_db():
    if _engine is None:
        settings = Settings()
        init_engine(settings.database_url)
    db: Session = SessionLocal()  # type: ignore[misc]
    try:
        yield db
    finally:
        db.close()


# Initialize default engine on import for app runtime.
init_engine(Settings().database_url)
