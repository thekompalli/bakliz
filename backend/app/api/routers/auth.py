from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.core.security import constant_time_equals, create_access_token
from app.core.settings import Settings

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class PingResponse(BaseModel):
    ok: bool = True


@router.get("/auth/ping", response_model=PingResponse)
def ping() -> PingResponse:
    return PingResponse()


@router.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest) -> LoginResponse:
    settings = Settings()
    if not constant_time_equals(payload.username, settings.admin_username) or not constant_time_equals(
        payload.password, settings.admin_password
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token = create_access_token(
        subject=payload.username,
        secret=settings.jwt_secret,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        expires_in_minutes=settings.jwt_exp_minutes,
    )
    return LoginResponse(access_token=token, expires_in=settings.jwt_exp_minutes * 60)
