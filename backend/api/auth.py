"""Firebase Authentication verification and Phase 1 application permissions."""
from functools import lru_cache

from firebase_admin import auth as firebase_auth
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from google.auth.credentials import AnonymousCredentials
from pydantic import BaseModel

try:
    from backend.config.settings import settings
    from backend.logger import GLOBAL_LOGGER as log
except ImportError:  # pragma: no cover - supports running with `--app-dir backend`
    from config.settings import settings
    from logger import GLOBAL_LOGGER as log


class CurrentUser(BaseModel):
    uid: str
    email: str
    can_manage_documents: bool


auth_router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@lru_cache(maxsize=1)
def _firebase_app():
    import firebase_admin

    try:
        return firebase_admin.get_app()
    except ValueError:
        options = {"projectId": settings.firebase_project_id}
        if settings.firebase_check_revoked:
            return firebase_admin.initialize_app(options=options)
        return firebase_admin.initialize_app(
            credential=AnonymousCredentials(),
            options=options,
        )


def _verify_token(token: str) -> dict:
    return firebase_auth.verify_id_token(
        token,
        app=_firebase_app(),
        check_revoked=settings.firebase_check_revoked,
    )


def get_current_user(
    request: Request,
    authorization: str | None = Header(default=None),
) -> CurrentUser:
    if (
        not settings.firebase_project_id
        or not settings.allowed_user_emails
        or not settings.document_manager_emails
        or not settings.document_manager_emails.issubset(settings.allowed_user_emails)
    ):
        raise HTTPException(
            status_code=503,
            detail="Authentication access is not configured correctly. Contact the application administrator.",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Sign-in is required.")

    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Sign-in is required.")

    try:
        claims = _verify_token(token)
    except Exception as error:
        if isinstance(error, (firebase_auth.InvalidIdTokenError, firebase_auth.UserDisabledError)):
            log.info("Firebase ID token rejected", request_id=request.state.request_id)
            raise HTTPException(
                status_code=401,
                detail="The sign-in session is invalid or expired.",
            ) from error
        log.error(
            "Firebase Authentication verification is unavailable",
            error=str(error),
            request_id=request.state.request_id,
        )
        raise HTTPException(
            status_code=503,
            detail="Authentication service is temporarily unavailable.",
        ) from error

    uid = claims.get("uid")
    email = claims.get("email")
    if (
        not isinstance(uid, str)
        or not isinstance(email, str)
        or not claims.get("email_verified", False)
    ):
        raise HTTPException(status_code=403, detail="A verified, approved account is required.")

    normalized_email = email.casefold()
    if normalized_email not in settings.allowed_user_emails:
        raise HTTPException(status_code=403, detail="This account is not approved to use the application.")

    return CurrentUser(
        uid=uid,
        email=normalized_email,
        can_manage_documents=normalized_email in settings.document_manager_emails,
    )


def require_document_manager(
    current_user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    if not current_user.can_manage_documents:
        raise HTTPException(status_code=403, detail="Document manager permission is required.")
    return current_user


@auth_router.get("/me", response_model=CurrentUser)
def current_user_profile(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    return current_user
