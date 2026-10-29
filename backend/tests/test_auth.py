from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from firebase_admin import auth as firebase_auth
from google.auth.credentials import AnonymousCredentials

from backend.api import auth
from backend.api.auth import CurrentUser, get_current_user, require_document_manager
from backend.config.settings import settings


REQUEST = SimpleNamespace(state=SimpleNamespace(request_id="test-request"))


def _configure_allowlist(monkeypatch):
    monkeypatch.setattr(settings, "firebase_project_id", "meridian-test")
    monkeypatch.setattr(settings, "allowed_user_emails_raw", "reader@example.com, manager@example.com")
    monkeypatch.setattr(settings, "document_manager_emails_raw", "manager@example.com")


def test_missing_bearer_token_is_rejected(monkeypatch):
    _configure_allowlist(monkeypatch)
    with pytest.raises(HTTPException) as error:
        get_current_user(REQUEST, None)
    assert error.value.status_code == 401


def test_document_managers_must_be_in_the_approved_user_list(monkeypatch):
    monkeypatch.setattr(settings, "firebase_project_id", "meridian-test")
    monkeypatch.setattr(settings, "allowed_user_emails_raw", "reader@example.com")
    monkeypatch.setattr(settings, "document_manager_emails_raw", "manager@example.com")
    with pytest.raises(HTTPException) as error:
        get_current_user(REQUEST, "Bearer valid-token")
    assert error.value.status_code == 503


def test_firebase_token_for_approved_reader_is_verified_and_read_only(monkeypatch):
    _configure_allowlist(monkeypatch)
    verified = []

    def verify(token):
        verified.append(token)
        return {"uid": "reader-id", "email": "reader@example.com", "email_verified": True}

    monkeypatch.setattr(auth, "_verify_token", verify)
    user = get_current_user(REQUEST, "Bearer valid-token")

    assert verified == ["valid-token"]
    assert user == CurrentUser(
        uid="reader-id",
        email="reader@example.com",
        can_manage_documents=False,
    )


def test_unapproved_or_unverified_accounts_are_rejected(monkeypatch):
    _configure_allowlist(monkeypatch)
    monkeypatch.setattr(
        auth,
        "_verify_token",
        lambda token: {
            "uid": "other-id",
            "email": "outside@example.com",
            "email_verified": True,
        },
    )
    with pytest.raises(HTTPException) as error:
        get_current_user(REQUEST, "Bearer valid-token")
    assert error.value.status_code == 403

    monkeypatch.setattr(
        auth,
        "_verify_token",
        lambda token: {
            "uid": "reader-id",
            "email": "reader@example.com",
            "email_verified": False,
        },
    )
    with pytest.raises(HTTPException) as error:
        get_current_user(REQUEST, "Bearer valid-token")
    assert error.value.status_code == 403


def test_document_manager_guard_rejects_reader():
    reader = CurrentUser(uid="reader", email="reader@example.com", can_manage_documents=False)
    with pytest.raises(HTTPException) as error:
        require_document_manager(reader)
    assert error.value.status_code == 403


def test_invalid_firebase_token_returns_401(monkeypatch):
    _configure_allowlist(monkeypatch)

    def reject(_):
        raise firebase_auth.InvalidIdTokenError("private token verifier detail")

    monkeypatch.setattr(auth, "_verify_token", reject)
    with pytest.raises(HTTPException) as error:
        get_current_user(REQUEST, "Bearer invalid-token")
    assert error.value.status_code == 401
    assert "private token verifier detail" not in error.value.detail


def test_firebase_verifier_outage_returns_503(monkeypatch):
    _configure_allowlist(monkeypatch)

    def fail(_):
        raise ValueError("private verifier outage details")

    monkeypatch.setattr(auth, "_verify_token", fail)
    with pytest.raises(HTTPException) as error:
        get_current_user(REQUEST, "Bearer valid-token")
    assert error.value.status_code == 503
    assert "private verifier outage details" not in error.value.detail


def test_token_verification_uses_configured_revocation_policy(monkeypatch):
    observed = {}
    monkeypatch.setattr(settings, "firebase_check_revoked", False)
    monkeypatch.setattr(auth, "_firebase_app", lambda: "firebase-app")

    def verify(token, app, check_revoked):
        observed.update(token=token, app=app, check_revoked=check_revoked)
        return {"uid": "reader-id"}

    monkeypatch.setattr(firebase_auth, "verify_id_token", verify)
    assert auth._verify_token("test-token") == {"uid": "reader-id"}
    assert observed == {
        "token": "test-token",
        "app": "firebase-app",
        "check_revoked": False,
    }


@pytest.mark.parametrize("check_revoked", [False, True])
def test_firebase_app_uses_credentials_appropriate_for_revocation_policy(monkeypatch, check_revoked):
    import firebase_admin

    initialized = {}

    def no_app():
        raise ValueError("Firebase app is not initialized")

    def initialize_app(credential=None, options=None):
        initialized.update(credential=credential, options=options)
        return "firebase-app"

    monkeypatch.setattr(settings, "firebase_project_id", "meridian-test")
    monkeypatch.setattr(settings, "firebase_check_revoked", check_revoked)
    monkeypatch.setattr(firebase_admin, "get_app", no_app)
    monkeypatch.setattr(firebase_admin, "initialize_app", initialize_app)
    auth._firebase_app.cache_clear()
    try:
        assert auth._firebase_app() == "firebase-app"
    finally:
        auth._firebase_app.cache_clear()

    if check_revoked:
        assert initialized["credential"] is None
    else:
        assert isinstance(initialized["credential"], AnonymousCredentials)
    assert initialized["options"] == {"projectId": "meridian-test"}
