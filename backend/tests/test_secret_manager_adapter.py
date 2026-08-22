"""Tests for `app.adapters.secret_manager`.

Two tiers, matching this repo's existing testing conventions
(gharos-standards: "integration tests per subsystem against the real
thing, not mocks" — Secret Manager has no local emulator, so its
"real thing" is the live GCP project):

1. **Unit tests** (always run) — a fake client implementing the same two
   methods the adapter calls (`secret_version_path`,
   `access_secret_version`), proving the adapter's own logic: project-id
   validation, NotFound -> SecretNotFoundError, other API errors ->
   SecretManagerUnavailable, successful decode.
2. **One live integration test**, marked `live_gcp` and skipped by
   default (registered in `pyproject.toml`) — it calls the real Secret
   Manager API against the real `gharos-demo-secret` secret (created via
   `gcloud secrets create gharos-demo-secret`, PHASES.md Phase 2 work item
   4) and asserts the placeholder value round-trips. Enable with:

       GHAROS_RUN_LIVE_GCP_TESTS=1 GCP_PROJECT_ID=<project> \\
           uv run pytest tests/test_secret_manager_adapter.py -m live_gcp

   Off by default so the rest of the suite never needs live credentials or
   makes a real network call (gharos-standards: "no cloud spend day to
   day" for routine local development).
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from google.api_core.exceptions import GoogleAPICallError, NotFound

from app.adapters.secret_manager import (
    SecretManagerAdapter,
    SecretManagerUnavailable,
    SecretNotConfigured,
    SecretNotFoundError,
)
from app.settings import Settings


class _FakeAccessResponse:
    def __init__(self, data: bytes) -> None:
        self.payload = _FakePayload(data)


class _FakePayload:
    def __init__(self, data: bytes) -> None:
        self.data = data


class _FakeSecretManagerClient:
    """Implements exactly the two `SecretManagerServiceClient` methods
    `SecretManagerAdapter` calls, so the adapter's own logic can be tested
    without a real API call or the heavier real-client mocking machinery."""

    def __init__(
        self,
        secrets: dict[tuple[str, str], bytes] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self._secrets = secrets or {}
        self._error = error

    def secret_version_path(self, project: str, secret: str, secret_version: str) -> str:
        return f"projects/{project}/secrets/{secret}/versions/{secret_version}"

    def access_secret_version(self, request: dict[str, Any]) -> _FakeAccessResponse:
        if self._error is not None:
            raise self._error
        name = request["name"]
        for (secret_id, version), data in self._secrets.items():
            if name.endswith(f"/secrets/{secret_id}/versions/{version}"):
                return _FakeAccessResponse(data)
        # `NotFound.__init__` carries no parameter annotations in
        # google-api-core's own source (same untyped-third-party-call gap as
        # `app.api.pubsub_receiver._verify_google_oidc_token`'s
        # `verify_oauth2_token` call) — the module is py.typed but this
        # constructor predates the library's annotation coverage.
        raise NotFound(f"no fake secret registered for {name}")  # type: ignore[no-untyped-call]


class TestSecretManagerAdapterConstruction:
    def test_raises_when_project_id_unset(self) -> None:
        with pytest.raises(SecretNotConfigured):
            SecretManagerAdapter(_FakeSecretManagerClient(), project_id="")

    def test_from_settings_uses_settings_project_id(self) -> None:
        settings = Settings(gcp_project_id="my-real-project")
        fake = _FakeSecretManagerClient({("gharos-demo-secret", "latest"): b"hello"})
        adapter = SecretManagerAdapter.from_settings(settings, client=fake)
        assert adapter.get_secret("gharos-demo-secret") == "hello"


class TestSecretManagerAdapterGetSecret:
    def test_decodes_utf8_payload(self) -> None:
        fake = _FakeSecretManagerClient({("gharos-demo-secret", "latest"): "café ☕".encode()})
        adapter = SecretManagerAdapter(fake, project_id="p")
        assert adapter.get_secret("gharos-demo-secret") == "café ☕"

    def test_uses_requested_version(self) -> None:
        fake = _FakeSecretManagerClient({("gharos-demo-secret", "3"): b"v3-value"})
        adapter = SecretManagerAdapter(fake, project_id="p")
        assert adapter.get_secret("gharos-demo-secret", version="3") == "v3-value"

    def test_not_found_raises_typed_error(self) -> None:
        fake = _FakeSecretManagerClient({})
        adapter = SecretManagerAdapter(fake, project_id="p")
        with pytest.raises(SecretNotFoundError) as exc_info:
            adapter.get_secret("no-such-secret")
        assert exc_info.value.secret_id == "no-such-secret"
        assert exc_info.value.version == "latest"

    def test_other_api_error_raises_unavailable_not_fabricated_success(self) -> None:
        # Same untyped-third-party-constructor gap as `NotFound` above.
        api_error = GoogleAPICallError("quota exceeded")  # type: ignore[no-untyped-call]
        fake = _FakeSecretManagerClient(error=api_error)
        adapter = SecretManagerAdapter(fake, project_id="p")
        with pytest.raises(SecretManagerUnavailable) as exc_info:
            adapter.get_secret("gharos-demo-secret")
        assert exc_info.value.secret_id == "gharos-demo-secret"


_LIVE_TESTS_ENABLED = os.environ.get("GHAROS_RUN_LIVE_GCP_TESTS") == "1"
_LIVE_PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "")


@pytest.mark.live_gcp
@pytest.mark.skipif(
    not _LIVE_TESTS_ENABLED or not _LIVE_PROJECT_ID,
    reason=(
        "live GCP test — set GHAROS_RUN_LIVE_GCP_TESTS=1 and GCP_PROJECT_ID "
        "to run against the real Secret Manager API"
    ),
)
def test_reads_the_real_placeholder_demo_secret_from_live_secret_manager() -> None:
    """Proves the Secret Manager wiring is real, end to end: a real SDK
    client, real ADC auth, a real network call to the live project, real
    decode of the real (placeholder-valued) `gharos-demo-secret` created by
    `gcloud secrets create gharos-demo-secret` for PHASES.md Phase 2 work
    item 4. Not mocked."""
    settings = Settings(gcp_project_id=_LIVE_PROJECT_ID)
    adapter = SecretManagerAdapter.from_settings(settings)
    value = adapter.get_secret("gharos-demo-secret")
    assert value  # non-empty: the real placeholder string round-tripped
    assert "placeholder" in value.lower()
