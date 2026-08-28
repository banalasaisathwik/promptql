from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import EmailStr, StringConstraints

from app.api.v1.models import ApiError, ApiErrorCode
from app.auth import (
    AuthPersistenceError,
    SessionSigner,
    User,
    UserAlreadyExistsError,
    UserRepository,
)
from app.config import AuthConfigurationError, AuthSettings
from app.connectors.models import ContractModel
from app.database import PostgresUserRepository

SESSION_COOKIE_NAME = "promptql_session"
_MIN_PASSWORD_LENGTH = 8
_MAX_PASSWORD_LENGTH = 200

router = APIRouter(prefix="/v1/auth", tags=["auth"])


class RegisterRequest(ContractModel):
    email: EmailStr
    password: Annotated[
        str,
        StringConstraints(
            min_length=_MIN_PASSWORD_LENGTH, max_length=_MAX_PASSWORD_LENGTH
        ),
    ]


class LoginRequest(ContractModel):
    email: EmailStr
    password: Annotated[str, StringConstraints(min_length=1, max_length=_MAX_PASSWORD_LENGTH)]


class UserResponse(ContractModel):
    id: UUID
    email: str
    created_at: datetime


def get_user_repository(request: Request) -> UserRepository:
    session_factory = getattr(request.app.state, "run_session_factory", None)
    if session_factory is None:
        raise AuthPersistenceError("Auth persistence is unavailable.")
    return PostgresUserRepository(session_factory)


def get_session_signer(request: Request) -> SessionSigner:
    session_signer = getattr(request.app.state, "session_signer", None)
    if session_signer is not None:
        return session_signer
    try:
        auth_settings = AuthSettings.from_environment()
    except AuthConfigurationError:
        raise AuthPersistenceError("Session signing is unavailable.") from None
    session_signer = SessionSigner(
        auth_settings.session_secret_key, auth_settings.session_max_age_seconds
    )
    request.app.state.session_signer = session_signer
    return session_signer


def get_current_user(
    request: Request,
    user_repository: Annotated[UserRepository, Depends(get_user_repository)],
    session_signer: Annotated[SessionSigner, Depends(get_session_signer)],
) -> User:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token is None:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    user_id = session_signer.unsign(token)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    user = user_repository.get_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    return user


def get_current_user_optional(request: Request) -> User | None:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token is None:
        return None

    user_repository = get_user_repository(request)
    session_signer = get_session_signer(request)
    user_id = session_signer.unsign(token)
    if user_id is None:
        return None
    return user_repository.get_by_id(user_id)


def _user_response(user: User) -> UserResponse:
    return UserResponse(id=user.id, email=user.email, created_at=user.created_at)


def _set_session_cookie(
    response: Response, session_signer: SessionSigner, user_id: UUID
) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_signer.sign(user_id),
        max_age=session_signer.max_age_seconds,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=201,
    responses={409: {"model": ApiError}},
)
def register(
    body: RegisterRequest,
    user_repository: Annotated[UserRepository, Depends(get_user_repository)],
    session_signer: Annotated[SessionSigner, Depends(get_session_signer)],
) -> JSONResponse:
    try:
        user = user_repository.create_user(body.email, body.password)
    except UserAlreadyExistsError:
        error = ApiError(
            code=ApiErrorCode.USER_ALREADY_EXISTS,
            message="An account with this email already exists.",
        )
        return JSONResponse(status_code=409, content=error.model_dump(mode="json"))

    response = JSONResponse(
        status_code=201,
        content=_user_response(user).model_dump(mode="json"),
    )
    _set_session_cookie(response, session_signer, user.id)
    return response


@router.post(
    "/login",
    response_model=UserResponse,
    responses={401: {"model": ApiError}},
)
def login(
    body: LoginRequest,
    user_repository: Annotated[UserRepository, Depends(get_user_repository)],
    session_signer: Annotated[SessionSigner, Depends(get_session_signer)],
) -> JSONResponse:
    user = user_repository.authenticate(body.email, body.password)
    if user is None:
        error = ApiError(
            code=ApiErrorCode.INVALID_CREDENTIALS,
            message="Incorrect email or password.",
        )
        return JSONResponse(status_code=401, content=error.model_dump(mode="json"))

    response = JSONResponse(content=_user_response(user).model_dump(mode="json"))
    _set_session_cookie(response, session_signer, user.id)
    return response


@router.post("/logout", status_code=204)
def logout() -> Response:
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return response
