"""`FirestoreOAuthPendingStore` (Phase 14.5) against the real Firestore
emulator.

Proves: a minted `state`'s `code_verifier` / `principal_hint` round-trip
through `put_pending` -> `take_pending`; `take_pending` is single-use
(delete-on-read); an expired record is never returned and is swept;
`put_pending` refuses to overwrite an in-flight `state`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from google.cloud import firestore

from app.persistence.codecs.common import NaiveDatetimeError
from app.persistence.conformance import _oauth_pending_store_conforms
from app.persistence.errors import OAuthPendingConflict
from app.persistence.oauth_pending_store import (
    PENDING_TTL,
    FirestoreOAuthPendingStore,
    create_oauth_pending_store,
)

T0 = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


class _Clock:
    """A hand-advanced clock — the documented test seam on
    `FirestoreOAuthPendingStore`."""

    def __init__(self, start: datetime) -> None:
        self._now = start

    def __call__(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta


@pytest.fixture
def clock() -> _Clock:
    return _Clock(T0)


@pytest.fixture
def pending_store(firestore_client: firestore.Client, clock: _Clock) -> FirestoreOAuthPendingStore:
    return FirestoreOAuthPendingStore(firestore_client, clock=clock)


class TestConformance:
    def test_conformance_factory_constructs(self, firestore_client: firestore.Client) -> None:
        assert _oauth_pending_store_conforms(firestore_client) is not None

    def test_default_factory_constructs_with_wall_clock(self, firestore_client: firestore.Client) -> None:
        assert create_oauth_pending_store(firestore_client) is not None


class TestRoundTripAndSingleUse:
    def test_put_then_take_returns_the_record_once(self, pending_store: FirestoreOAuthPendingStore) -> None:
        pending_store.put_pending(
            "state-abc", code_verifier="verifier-xyz", principal_hint="alice@example.com"
        )

        first = pending_store.take_pending("state-abc")
        assert first is not None
        assert first.code_verifier == "verifier-xyz"
        assert first.principal_hint == "alice@example.com"
        assert first.created_at == T0

        assert pending_store.take_pending("state-abc") is None  # delete-on-read

    def test_take_unknown_state_returns_none(self, pending_store: FirestoreOAuthPendingStore) -> None:
        assert pending_store.take_pending("never-minted") is None

    def test_principal_hint_may_be_absent(self, pending_store: FirestoreOAuthPendingStore) -> None:
        pending_store.put_pending("state-2", code_verifier="v2", principal_hint=None)
        record = pending_store.take_pending("state-2")
        assert record is not None
        assert record.principal_hint is None

    def test_states_are_independent(self, pending_store: FirestoreOAuthPendingStore) -> None:
        pending_store.put_pending("state-a", code_verifier="va", principal_hint=None)
        pending_store.put_pending("state-b", code_verifier="vb", principal_hint=None)

        rec_a = pending_store.take_pending("state-a")
        assert rec_a is not None and rec_a.code_verifier == "va"
        rec_b = pending_store.take_pending("state-b")
        assert rec_b is not None and rec_b.code_verifier == "vb"

    def test_put_pending_refuses_to_overwrite_in_flight_state(
        self, pending_store: FirestoreOAuthPendingStore
    ) -> None:
        pending_store.put_pending("dup", code_verifier="first", principal_hint=None)
        with pytest.raises(OAuthPendingConflict):
            pending_store.put_pending("dup", code_verifier="second", principal_hint=None)
        # the original record is intact and still consumable
        record = pending_store.take_pending("dup")
        assert record is not None
        assert record.code_verifier == "first"


class TestExpiry:
    def test_expired_record_is_not_returned(
        self, pending_store: FirestoreOAuthPendingStore, clock: _Clock
    ) -> None:
        pending_store.put_pending("stale", code_verifier="v", principal_hint=None)
        clock.advance(PENDING_TTL + timedelta(seconds=1))
        assert pending_store.take_pending("stale") is None

    def test_record_just_within_ttl_is_still_returned(
        self, pending_store: FirestoreOAuthPendingStore, clock: _Clock
    ) -> None:
        pending_store.put_pending("fresh", code_verifier="v", principal_hint=None)
        clock.advance(PENDING_TTL - timedelta(seconds=1))
        assert pending_store.take_pending("fresh") is not None

    def test_take_pending_consumes_an_expired_record(
        self,
        pending_store: FirestoreOAuthPendingStore,
        clock: _Clock,
        firestore_client: firestore.Client,
    ) -> None:
        pending_store.put_pending("stale", code_verifier="v", principal_hint=None)
        clock.advance(PENDING_TTL + timedelta(minutes=1))
        assert pending_store.take_pending("stale") is None
        snap = firestore_client.collection("oauth_pending").document("stale").get()
        assert not snap.exists  # single-use: deleted even though expired

    def test_sweep_expired_deletes_only_past_ttl(
        self, pending_store: FirestoreOAuthPendingStore, clock: _Clock
    ) -> None:
        pending_store.put_pending("old-1", code_verifier="v", principal_hint=None)
        pending_store.put_pending("old-2", code_verifier="v", principal_hint=None)
        clock.advance(PENDING_TTL + timedelta(minutes=5))
        pending_store.put_pending("recent", code_verifier="v", principal_hint=None)

        deleted = pending_store.sweep_expired()
        assert deleted == 2
        assert pending_store.take_pending("recent") is not None
        assert pending_store.take_pending("old-1") is None

    def test_naive_now_is_rejected(self, firestore_client: firestore.Client) -> None:
        store = FirestoreOAuthPendingStore(firestore_client, clock=lambda: datetime(2026, 8, 29, 12, 0))
        with pytest.raises(NaiveDatetimeError):
            store.put_pending("x", code_verifier="v", principal_hint=None)
