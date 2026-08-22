"""`app.persistence.firestore_client.create_firestore_client` — dependency
injection entrypoint for constructing a real `firestore.Client` from typed
settings (no module-level singleton)."""

from __future__ import annotations

import os

import pytest

from app.persistence.firestore_client import create_firestore_client
from app.settings import Settings


class TestCreateFirestoreClient:
    def test_uses_configured_project_id_when_set(self) -> None:
        settings = Settings(gcp_project_id="my-real-project", firestore_database="(default)")
        client = create_firestore_client(settings)
        assert client.project == "my-real-project"
        client.close()  # type: ignore[no-untyped-call]

    def test_falls_back_to_local_project_id_against_the_emulator(self) -> None:
        assert os.environ.get("FIRESTORE_EMULATOR_HOST")  # set by conftest module import
        settings = Settings(gcp_project_id="", firestore_database="(default)")
        client = create_firestore_client(settings)
        assert client.project == "gharos-local"
        client.close()  # type: ignore[no-untyped-call]

    def test_raises_when_no_project_id_and_no_emulator(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("FIRESTORE_EMULATOR_HOST", raising=False)
        settings = Settings(gcp_project_id="", firestore_database="(default)")
        with pytest.raises(ValueError, match="gcp_project_id is unset"):
            create_firestore_client(settings)
