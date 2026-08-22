"""`FirestoreIdempotencyStore` (spec §19.1) — Gate 1: "same idempotency
key twice -> one effect," including a forced-replay/crash-recovery style
test: a second identical call arriving after the first's effect was
recorded must return the original result, with no duplicate effect.
"""

from __future__ import annotations

import pytest
from contracts.actions import IdempotencyKey
from google.cloud import firestore

from app.persistence.idempotency_store import FirestoreIdempotencyStore


class TestFirstUseThenReplay:
    def test_first_use_returns_none_then_replay_returns_recorded_result(
        self, idempotency_store: FirestoreIdempotencyStore
    ) -> None:
        key = IdempotencyKey(entity_id="obligation-1", action_type="pay", cycle="2026-08").as_str()

        assert idempotency_store.check_and_reserve(key) is None
        idempotency_store.record_result(key, "action-record-1")

        assert idempotency_store.check_and_reserve(key) == "action-record-1"
        # replaying again is still a stable no-op
        assert idempotency_store.check_and_reserve(key) == "action-record-1"

    def test_different_keys_are_independent(self, idempotency_store: FirestoreIdempotencyStore) -> None:
        key_a = IdempotencyKey(entity_id="obligation-1", action_type="pay", cycle="2026-08").as_str()
        key_b = IdempotencyKey(entity_id="obligation-1", action_type="pay", cycle="2026-09").as_str()

        idempotency_store.record_result(key_a, "result-a")
        assert idempotency_store.check_and_reserve(key_b) is None

    def test_reservation_without_result_is_not_treated_as_used(
        self, idempotency_store: FirestoreIdempotencyStore
    ) -> None:
        key = IdempotencyKey(entity_id="obligation-2", action_type="notify", cycle="2026-08").as_str()
        assert idempotency_store.check_and_reserve(key) is None
        # a second check before record_result is still "first use" territory
        assert idempotency_store.check_and_reserve(key) is None


class TestRecordResultConflictDetection:
    def test_recording_the_same_result_twice_is_a_harmless_no_op(
        self, idempotency_store: FirestoreIdempotencyStore
    ) -> None:
        key = IdempotencyKey(entity_id="obligation-3", action_type="pay", cycle="2026-08").as_str()
        idempotency_store.record_result(key, "result-x")
        idempotency_store.record_result(key, "result-x")  # no error
        assert idempotency_store.check_and_reserve(key) == "result-x"

    def test_recording_a_different_result_for_a_completed_key_raises(
        self, idempotency_store: FirestoreIdempotencyStore
    ) -> None:
        key = IdempotencyKey(entity_id="obligation-4", action_type="pay", cycle="2026-08").as_str()
        idempotency_store.record_result(key, "result-x")
        with pytest.raises(ValueError, match="already completed"):
            idempotency_store.record_result(key, "result-y")


class TestCrashRecoveryStyleReplay:
    """Simulates a process crash between the first call recording its
    effect and a second identical call arriving later: a brand-new
    `FirestoreIdempotencyStore` instance (standing in for a restarted
    process) reading from the *same durable Firestore project* must see
    the completed result and must not cause the effect to run twice."""

    def test_second_store_instance_sees_the_completed_result_no_duplicate_effect(
        self, firestore_client: firestore.Client
    ) -> None:
        key = IdempotencyKey(entity_id="obligation-5", action_type="pay", cycle="2026-08").as_str()

        effect_call_count = 0

        def run_effect_once_guarded(store: FirestoreIdempotencyStore) -> str:
            nonlocal effect_call_count
            prior = store.check_and_reserve(key)
            if prior is not None:
                return prior
            effect_call_count += 1
            result_ref = f"action-record-{effect_call_count}"
            store.record_result(key, result_ref)
            return result_ref

        # "process 1": first call, runs the effect for real
        store_process_1 = FirestoreIdempotencyStore(firestore_client)
        result_1 = run_effect_once_guarded(store_process_1)
        assert effect_call_count == 1
        assert result_1 == "action-record-1"

        # simulated crash + restart: a brand-new store instance, but the
        # *same* durable Firestore project (this is what makes it a real
        # crash-recovery proof rather than an in-process replay)
        store_process_2 = FirestoreIdempotencyStore(firestore_client)
        result_2 = run_effect_once_guarded(store_process_2)

        assert effect_call_count == 1  # the effect did NOT run a second time
        assert result_2 == result_1  # the original result was returned
