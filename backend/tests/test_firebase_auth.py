"""Tests for Firebase Authentication & Email Verification enforcement."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from httpx import AsyncClient

from app.core.errors import UnauthenticatedError
from app.services.firebase_auth_service import verify_firebase_id_token
from tests.conftest import TEST_PASSWORD


def test_verify_firebase_token_empty():
    with pytest.raises(UnauthenticatedError):
        verify_firebase_id_token("")


async def test_firebase_login_rejects_unverified_email(client: AsyncClient):
    fake_payload = {
        "sub": "firebase_uid_123",
        "email": "unverified@example.com",
        "email_verified": False,
        "name": "Unverified User",
    }
    with patch("app.services.firebase_auth_service.verify_firebase_id_token", return_value=fake_payload):
        response = await client.post(
            "/api/v1/auth/firebase-login",
            json={"id_token": "mock_id_token_unverified"},
        )
        assert response.status_code == 403
        data = response.json()
        error_msg = data.get("error", {}).get("message", "") or data.get("detail", "")
        assert "not verified" in error_msg.lower()


async def test_firebase_login_provisions_new_user_and_workspace(client: AsyncClient):
    fake_payload = {
        "sub": "firebase_uid_456",
        "email": "new_google_user@example.com",
        "email_verified": True,
        "name": "Sarah Connor",
    }
    with patch("app.services.firebase_auth_service.verify_firebase_id_token", return_value=fake_payload):
        response = await client.post(
            "/api/v1/auth/firebase-login",
            json={"id_token": "mock_id_token_verified"},
        )
        assert response.status_code == 200
        tokens = response.json()
        assert "access_token" in tokens
        assert "refresh_token" in tokens

        # Verify access token works on authenticated endpoints
        me_response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        assert me_response.status_code == 200
        me = me_response.json()
        assert me["user"]["email"] == "new_google_user@example.com"
        assert me["user"]["full_name"] == "Sarah Connor"
        assert len(me["organizations"]) == 1
        assert me["organizations"][0]["role"] == "owner"


async def test_firebase_login_links_existing_user(client: AsyncClient):
    # 1. Register an account using password
    reg_response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "existing_dev@example.com",
            "password": TEST_PASSWORD,
            "full_name": "Dev User",
            "organization_name": "Dev Org",
        },
    )
    assert reg_response.status_code == 201

    # 2. Log in with Google/Firebase using the same email
    fake_payload = {
        "sub": "firebase_uid_789",
        "email": "existing_dev@example.com",
        "email_verified": True,
        "name": "Dev User (Google)",
    }
    with patch("app.services.firebase_auth_service.verify_firebase_id_token", return_value=fake_payload):
        response = await client.post(
            "/api/v1/auth/firebase-login",
            json={"id_token": "mock_id_token_existing"},
        )
        assert response.status_code == 200
        tokens = response.json()

        # Check me
        me_response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        assert me_response.status_code == 200
        me = me_response.json()
        assert me["user"]["email"] == "existing_dev@example.com"
        assert me["organizations"][0]["organization_name"] == "Dev Org"
