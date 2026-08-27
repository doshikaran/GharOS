"""Tests for `app.api.pubsub_receiver` — envelope parsing and OIDC push
verification.

`verify_push_request` takes an injectable `verifier` callable (DI, per
gharos-standards) so these tests never make a real network call to fetch
Google's public certificates; `test_pubsub_topics_script.py` and the
Phase 2 report cover proving the real `--push-auth-service-account` wiring
against the live project.
"""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.pubsub_receiver import PubSubMessage, _decode_message_data, verify_push_request
from app.main import app
from app.settings import Settings

client = TestClient(app)


def _b64(payload: dict[str, Any]) -> str:
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


def _envelope_body(*, data: str | None) -> dict[str, Any]:
    return {
        "message": {
            "data": data,
            "messageId": "10000000000001",
            "publishTime": "2026-08-22T06:00:00.123Z",
            "attributes": {"cycle_label": "heartbeat"},
        },
        "subscription": "projects/p/subscriptions/gharos-heartbeat-push",
    }


class TestReceiveHeartbeatEndpoint:
    def test_accepts_a_real_shaped_envelope_and_returns_204(self) -> None:
        app.dependency_overrides.clear()
        body = _envelope_body(data=_b64({"job_name": "gharos-heartbeat-tick", "cycle_label": "heartbeat"}))
        response = client.post("/events/heartbeat", json=body)
        assert response.status_code == 204
        assert response.content == b""

    def test_accepts_an_attributes_only_message_with_no_data(self) -> None:
        app.dependency_overrides.clear()
        body = _envelope_body(data=None)
        response = client.post("/events/heartbeat", json=body)
        assert response.status_code == 204

    def test_malformed_base64_data_is_rejected_as_400(self) -> None:
        app.dependency_overrides.clear()
        body = _envelope_body(data="not-valid-base64!!!")
        response = client.post("/events/heartbeat", json=body)
        assert response.status_code == 400

    def test_missing_message_field_is_rejected_as_422(self) -> None:
        app.dependency_overrides.clear()
        response = client.post("/events/heartbeat", json={"subscription": "projects/p/subscriptions/s"})
        assert response.status_code == 422

    def test_verification_enforced_when_service_account_configured(self) -> None:
        from app.settings import get_settings

        app.dependency_overrides[get_settings] = lambda: Settings(
            pubsub_push_service_account_email="pusher@p.iam.gserviceaccount.com"
        )
        try:
            body = _envelope_body(data=_b64({"job_name": "gharos-heartbeat-tick"}))
            response = client.post("/events/heartbeat", json=body)
            assert response.status_code == 401
        finally:
            app.dependency_overrides.clear()


class TestReceiveFollowupSweepEndpoint:
    """A31's Scheduler tick receiver (PHASES.md Phase 7) — same envelope
    shape and same push-verification path as `/events/heartbeat`, proven
    identically."""

    def test_accepts_a_real_shaped_envelope_and_returns_204(self) -> None:
        app.dependency_overrides.clear()
        body = _envelope_body(
            data=_b64({"job_name": "gharos-followup-sweep", "cycle_label": "followup-sweep"})
        )
        response = client.post("/events/followup-sweep", json=body)
        assert response.status_code == 204
        assert response.content == b""

    def test_malformed_base64_data_is_rejected_as_400(self) -> None:
        app.dependency_overrides.clear()
        body = _envelope_body(data="not-valid-base64!!!")
        response = client.post("/events/followup-sweep", json=body)
        assert response.status_code == 400

    def test_verification_enforced_when_service_account_configured(self) -> None:
        from app.settings import get_settings

        app.dependency_overrides[get_settings] = lambda: Settings(
            pubsub_push_service_account_email="pusher@p.iam.gserviceaccount.com"
        )
        try:
            body = _envelope_body(data=_b64({"job_name": "gharos-followup-sweep"}))
            response = client.post("/events/followup-sweep", json=body)
            assert response.status_code == 401
        finally:
            app.dependency_overrides.clear()


class TestDecodeMessageData:
    def test_returns_none_for_no_data(self) -> None:
        message = PubSubMessage(data=None, messageId="1", publishTime="t")
        assert _decode_message_data(message) is None

    def test_parses_json_payload(self) -> None:
        message = PubSubMessage(data=_b64({"a": 1}), messageId="1", publishTime="t")
        assert _decode_message_data(message) == {"a": 1}

    def test_falls_back_to_raw_text_for_non_json_payload(self) -> None:
        raw = base64.b64encode(b"not json").decode("ascii")
        message = PubSubMessage(data=raw, messageId="1", publishTime="t")
        assert _decode_message_data(message) == "not json"

    def test_raises_400_on_invalid_base64(self) -> None:
        message = PubSubMessage(data="!!!not-base64", messageId="1", publishTime="t")
        with pytest.raises(HTTPException) as exc_info:
            _decode_message_data(message)
        assert exc_info.value.status_code == 400


class TestVerifyPushRequest:
    def test_skips_verification_when_no_service_account_configured(self) -> None:
        settings = Settings(pubsub_push_service_account_email="")
        verify_push_request(authorization=None, settings=settings)  # does not raise

    def test_rejects_missing_bearer_token_when_required(self) -> None:
        settings = Settings(pubsub_push_service_account_email="pusher@p.iam.gserviceaccount.com")
        with pytest.raises(HTTPException) as exc_info:
            verify_push_request(authorization=None, settings=settings)
        assert exc_info.value.status_code == 401

    def test_rejects_malformed_authorization_header(self) -> None:
        settings = Settings(pubsub_push_service_account_email="pusher@p.iam.gserviceaccount.com")
        with pytest.raises(HTTPException) as exc_info:
            verify_push_request(authorization="NotBearer xyz", settings=settings)
        assert exc_info.value.status_code == 401

    def test_rejects_a_token_that_fails_cryptographic_verification(self) -> None:
        settings = Settings(pubsub_push_service_account_email="pusher@p.iam.gserviceaccount.com")

        def failing_verifier(token: str, audience: str) -> dict[str, Any]:
            raise ValueError("Token expired")

        with pytest.raises(HTTPException) as exc_info:
            verify_push_request(authorization="Bearer badtoken", settings=settings, verifier=failing_verifier)
        assert exc_info.value.status_code == 401

    def test_rejects_a_valid_token_from_the_wrong_identity(self) -> None:
        settings = Settings(pubsub_push_service_account_email="pusher@p.iam.gserviceaccount.com")

        def wrong_identity_verifier(token: str, audience: str) -> dict[str, Any]:
            return {"email": "someone-else@p.iam.gserviceaccount.com"}

        with pytest.raises(HTTPException) as exc_info:
            verify_push_request(
                authorization="Bearer sometoken", settings=settings, verifier=wrong_identity_verifier
            )
        assert exc_info.value.status_code == 401

    def test_accepts_a_valid_token_from_the_expected_identity(self) -> None:
        settings = Settings(
            pubsub_push_service_account_email="pusher@p.iam.gserviceaccount.com",
            pubsub_push_audience="https://gharos-api-xyz.a.run.app",
        )
        seen: dict[str, str] = {}

        def correct_verifier(token: str, audience: str) -> dict[str, Any]:
            seen["audience"] = audience
            return {"email": "pusher@p.iam.gserviceaccount.com"}

        verify_push_request(authorization="Bearer goodtoken", settings=settings, verifier=correct_verifier)
        assert seen["audience"] == "https://gharos-api-xyz.a.run.app"
