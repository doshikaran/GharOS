"""A10 Pattern Miner (`app.graph.pattern_miner`) — PHASES.md Phase 14,
ADR-021 Decision 1.

Gate 14's own acceptance list, this module's share of it:
- **The hard support/slip-rate gate**: a candidate below either threshold
  never reaches `PatternRepository.write_pattern` — proven directly, not
  inferred from the absence of a written `Pattern`.
- A real, non-obvious pattern mined from seeded history: the Monday-slip
  scenario in `seeds.demo_household` (Phase 14 addition), run against the
  real Firestore-emulator-backed `FirestoreGraphReader`/
  `FirestorePatternRepository` — not a hand-constructed fixture standing
  in for "seeded history."
- The Wednesday control in that same seeded scenario produces no pattern
  (below `MIN_PATTERN_SUPPORT`), proving the miner is sensitive to the
  specific day, not "appointments in general."
- Pro-tier narration failure isolates to one tag; it does not fabricate a
  description and does not crash the run.

Unit tests use `FakeGraphReader`/`FakePatternRepository` and a real
`GeminiClient` wired to `_gemini_fakes.fake_router` (no network) — mirrors
`test_calibration_agent.py`'s established pattern for A39, the closest
prior art for a Pro-tier-narrates/code-decides agent.
"""

from __future__ import annotations

from datetime import UTC, datetime

from contracts.graph_types import AgentId, Derivation, NodeId, Outcome, Provenance
from google.genai import errors as genai_errors

from app.graph.pattern_miner import MIN_PATTERN_SLIP_RATE, MIN_PATTERN_SUPPORT, PatternMiner
from app.graph.pattern_repository import FirestorePatternRepository
from app.graph.reader import FirestoreGraphReader
from app.persistence.firestore_store import FirestoreGraphStore
from app.reasoning.gemini_client import GeminiClient
from seeds.demo_household import SeedResult

from ._fake_graph_reader import FakeGraphReader
from ._fake_pattern_repository import FakePatternRepository
from ._gemini_fakes import FakeModels, fake_router

_NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


def _outcome(node_id: str, *, variance: float | None, tag: str) -> Outcome:
    return Outcome(
        id=NodeId(node_id),
        provenance=Provenance(
            derivation=Derivation.AMBIGUOUS,
            source_ref=None,
            confidence=0.8,
            deriving_agent=AgentId("A26"),
            created_at=_NOW,
        ),
        predicted="on schedule",
        actual="see variance",
        variance=variance,
        attribution_tags=(tag,),
    )


def _miner(
    *, outcomes_by_tag: dict[str, tuple[Outcome, ...]], texts: list[str]
) -> tuple[PatternMiner, FakePatternRepository, FakeModels]:
    reader = FakeGraphReader(outcome_variance_by_tag=outcomes_by_tag)
    pattern_repo = FakePatternRepository()
    fake_models = FakeModels(texts=texts)
    client = GeminiClient(router=fake_router(fake_models))
    miner = PatternMiner(graph_reader=reader, pattern_repository=pattern_repo, gemini_client=client)
    return miner, pattern_repo, fake_models


class TestSupportThresholdGate:
    """Spec §15.2 A10's own forbidden-list line: "creating patterns below
    a support threshold." Below `MIN_PATTERN_SUPPORT`, a candidate must
    never reach `write_pattern` — checked directly against the fake
    repository's call log, not inferred from the miner's return value."""

    def test_two_samples_never_reaches_write_pattern(self) -> None:
        assert MIN_PATTERN_SUPPORT == 3, "test assumes the documented threshold; update if it changes"
        outcomes = (
            _outcome("o1", variance=50.0, tag="scheduled_tuesday"),
            _outcome("o2", variance=50.0, tag="scheduled_tuesday"),
        )
        miner, pattern_repo, fake_models = _miner(
            outcomes_by_tag={"scheduled_tuesday": outcomes}, texts=["should never be read"]
        )

        written = miner.run(now=_NOW)

        assert written == ()
        assert pattern_repo.write_pattern_calls == []
        assert len(fake_models.calls) == 0, "below-threshold candidate must never trigger a model call"

    def test_zero_samples_never_reaches_write_pattern(self) -> None:
        miner, pattern_repo, fake_models = _miner(outcomes_by_tag={}, texts=["should never be read"])

        written = miner.run(now=_NOW)

        assert written == ()
        assert pattern_repo.write_pattern_calls == []
        assert len(fake_models.calls) == 0


class TestSlipRateGate:
    """Enough samples, but the correlation is too weak to be a real
    regularity — also never written."""

    def test_low_slip_rate_never_reaches_write_pattern(self) -> None:
        assert MIN_PATTERN_SLIP_RATE == 0.5, "test assumes the documented threshold; update if it changes"
        # 4 samples (clears MIN_PATTERN_SUPPORT), only 1 slipped (25% < 50%).
        outcomes = (
            _outcome("o1", variance=50.0, tag="scheduled_friday"),
            _outcome("o2", variance=0.0, tag="scheduled_friday"),
            _outcome("o3", variance=0.0, tag="scheduled_friday"),
            _outcome("o4", variance=-10.0, tag="scheduled_friday"),
        )
        miner, pattern_repo, fake_models = _miner(
            outcomes_by_tag={"scheduled_friday": outcomes}, texts=["should never be read"]
        )

        written = miner.run(now=_NOW)

        assert written == ()
        assert pattern_repo.write_pattern_calls == []
        assert len(fake_models.calls) == 0

    def test_unresolved_variance_outcomes_excluded_from_both_counts(self) -> None:
        """An `Outcome` with `variance is None` (prediction not yet
        settled) carries no evidence — excluded from sample size AND slip
        count, never treated as a non-slip. Three settled + two
        unsettled must behave exactly as three settled alone."""
        outcomes = (
            _outcome("o1", variance=50.0, tag="scheduled_thursday"),
            _outcome("o2", variance=50.0, tag="scheduled_thursday"),
            _outcome("o3", variance=50.0, tag="scheduled_thursday"),
            _outcome("o4", variance=None, tag="scheduled_thursday"),
            _outcome("o5", variance=None, tag="scheduled_thursday"),
        )
        miner, pattern_repo, _ = _miner(
            outcomes_by_tag={"scheduled_thursday": outcomes}, texts=["Appointments on Thursday slip."]
        )

        written = miner.run(now=_NOW)

        assert len(written) == 1
        assert written[0].support_count == 3
        assert set(written[0].contributing_outcome_ids) == {NodeId("o1"), NodeId("o2"), NodeId("o3")}
        assert len(pattern_repo.write_pattern_calls) == 1


class TestCandidateWrittenWhenBothThresholdsClear:
    def test_pattern_written_with_model_description(self) -> None:
        outcomes = (
            _outcome("o1", variance=90.0, tag="scheduled_monday"),
            _outcome("o2", variance=40.0, tag="scheduled_monday"),
            _outcome("o3", variance=60.0, tag="scheduled_monday"),
            _outcome("o4", variance=0.0, tag="scheduled_monday"),
        )
        expected_text = "Appointments scheduled on Monday slip in this household 75% of the time."
        miner, pattern_repo, fake_models = _miner(
            outcomes_by_tag={"scheduled_monday": outcomes}, texts=[expected_text]
        )

        written = miner.run(now=_NOW)

        assert len(written) == 1
        pattern = written[0]
        assert pattern.description == expected_text
        assert pattern.support_count == 4
        expected_ids = {NodeId("o1"), NodeId("o2"), NodeId("o3"), NodeId("o4")}
        assert set(pattern.contributing_outcome_ids) == expected_ids
        assert pattern_repo.write_pattern_calls == [pattern]
        assert len(fake_models.calls) == 1

    def test_whitespace_only_model_response_falls_back_to_template(self) -> None:
        """`GeminiClient.generate_text` only raises on a *falsy* response;
        a purely-whitespace one is truthy and passed through — this
        module's own fallback must catch it rather than writing a blank
        description."""
        outcomes = (
            _outcome("o1", variance=90.0, tag="scheduled_monday"),
            _outcome("o2", variance=40.0, tag="scheduled_monday"),
            _outcome("o3", variance=60.0, tag="scheduled_monday"),
        )
        miner, pattern_repo, _ = _miner(outcomes_by_tag={"scheduled_monday": outcomes}, texts=["   "])

        written = miner.run(now=_NOW)

        assert len(written) == 1
        assert written[0].description  # non-blank
        assert "scheduled_monday" in written[0].description
        assert pattern_repo.write_pattern_calls == [written[0]]

    def test_model_call_failure_isolates_to_one_tag_and_never_raises(self) -> None:
        """A failed Pro-tier narration call for one candidate is logged
        and skipped — it must never fabricate a description, and must
        never crash the whole run for other candidates."""
        outcomes = (
            _outcome("o1", variance=90.0, tag="scheduled_monday"),
            _outcome("o2", variance=40.0, tag="scheduled_monday"),
            _outcome("o3", variance=60.0, tag="scheduled_monday"),
        )
        reader = FakeGraphReader(outcome_variance_by_tag={"scheduled_monday": outcomes})
        pattern_repo = FakePatternRepository()
        api_error = genai_errors.APIError(503, {"error": {"message": "simulated Vertex AI outage"}})
        fake_models = FakeModels(texts=["irrelevant"], error=api_error)
        client = GeminiClient(router=fake_router(fake_models))
        miner = PatternMiner(graph_reader=reader, pattern_repository=pattern_repo, gemini_client=client)

        written = miner.run(now=_NOW)  # must not raise

        assert written == ()
        assert pattern_repo.write_pattern_calls == []


class TestRealSeededHistoryProducesNonObviousPattern:
    """Gate 14: "Pattern mining produces >=1 non-obvious correct pattern
    from seeded history." Run against the real Firestore emulator, the
    real `FirestoreGraphReader`/`FirestorePatternRepository`, and the real
    seeded demo household — not a hand-built fixture standing in for it.
    """

    def test_monday_slip_pattern_mined_from_real_seeded_data(
        self, store: FirestoreGraphStore, reader: FirestoreGraphReader, seeded: SeedResult
    ) -> None:
        pattern_repo = FirestorePatternRepository(store)
        fake_models = FakeModels(
            texts=["Appointments scheduled on Monday slip in this household 75% of the time."]
        )
        client = GeminiClient(router=fake_router(fake_models))
        miner = PatternMiner(graph_reader=reader, pattern_repository=pattern_repo, gemini_client=client)

        written = miner.run(now=_NOW)

        # Identify the Monday pattern by its actual contributing ids (the
        # seed's four Monday outcome ids) rather than by guessing at
        # description text, so this assertion is robust to prompt wording.
        expected_monday_ids = {
            NodeId("outcome-dadi-physio-mon1"),
            NodeId("outcome-aarav-dentist-mon2"),
            NodeId("outcome-dadi-cardio-mon3"),
            NodeId("outcome-aarav-eye-mon4"),
        }
        monday_pattern = next(
            (p for p in written if set(p.contributing_outcome_ids) == expected_monday_ids), None
        )
        assert monday_pattern is not None, [(p.description, p.contributing_outcome_ids) for p in written]
        assert monday_pattern.support_count == 4

        # The Wednesday control (2 samples, below MIN_PATTERN_SUPPORT)
        # must NOT produce a pattern — proves specificity to Monday, not
        # "appointments in general."
        wednesday_ids = {NodeId("outcome-dadi-physio-wed1"), NodeId("outcome-aarav-dentist-wed2")}
        assert not any(set(p.contributing_outcome_ids) == wednesday_ids for p in written)

        # And the write actually persisted through the real repository.
        all_patterns = pattern_repo.all_patterns()
        assert monday_pattern.id in {p.id for p in all_patterns}
