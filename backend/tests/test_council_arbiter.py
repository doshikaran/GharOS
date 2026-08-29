"""`app.solvers.council_arbiter.resolve` (Phase 12, ADR-019 Decision 3) —
every regret value below is hand-computed in the comment right next to the
assertion it backs, the same discipline as Phase 8's `verify_ef1` and
Phase 11's hand-computed calibration stats tests.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from contracts.graph_types import AgentId, Derivation, NodeId, Provenance, SourceRef, ValuationProfile

from app.solvers.council_arbiter import (
    CouncilArbiterError,
    NoCostSignalError,
    NoSurvivingBranchesError,
    resolve,
)

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


def _profile(person_id: str, costs: dict[str, float]) -> ValuationProfile:
    return ValuationProfile(
        id=NodeId(f"valuation-{person_id}"),
        provenance=Provenance(
            derivation=Derivation.INFERRED,
            source_ref=SourceRef(source_document_id=NodeId("doc-1"), region="interview"),
            confidence=0.8,
            deriving_agent=AgentId("A47"),
            created_at=NOW,
        ),
        person_id=NodeId(person_id),
        costs=costs,
        elicitation_method="interview",
    )


class TestBasicMinimaxRegret:
    """Two people, three surviving branches, every profile fully priced —
    no sparsity, no tie. Hand-computed:

    Priya: b1=10, b2=20, b3=13 -> her own min is 10 (b1).
      regret(b1) = 10-10 = 0
      regret(b2) = 20-10 = 10
      regret(b3) = 13-10 = 3
    Arjun: b1=15, b2=5, b3=9 -> his own min is 5 (b2).
      regret(b1) = 15-5 = 10
      regret(b2) = 5-5 = 0
      regret(b3) = 9-5 = 4

    max regret per branch: b1 = max(0,10) = 10; b2 = max(10,0) = 10;
    b3 = max(3,4) = 4. b3 has the lowest max regret -> b3 wins.
    """

    def test_lowest_max_regret_branch_wins(self) -> None:
        priya = _profile("person-priya", {"branch-b1": 10.0, "branch-b2": 20.0, "branch-b3": 13.0})
        arjun = _profile("person-arjun", {"branch-b1": 15.0, "branch-b2": 5.0, "branch-b3": 9.0})

        result = resolve(
            surviving_branch_ids=(NodeId("branch-b1"), NodeId("branch-b2"), NodeId("branch-b3")),
            eliminated_branch_ids=(),
            valuation_profiles=(priya, arjun),
        )

        assert result.winning_branch_id == NodeId("branch-b3")
        assert result.regret_by_person == {
            NodeId("person-priya"): 3.0,
            NodeId("person-arjun"): 4.0,
        }
        # Arjun has the higher regret (4 > 3) for the winner -> costs him most.
        assert result.most_costly_to == NodeId("person-arjun")
        # Priya has the lower regret (3 < 4) -> most favourable to her.
        assert result.most_favorable_to == NodeId("person-priya")
        # Both regrets are > 0 -> both are real concessions.
        assert result.conceding_person_ids == (NodeId("person-arjun"), NodeId("person-priya"))
        assert result.eliminated_branch_ids == ()


class TestLeximinTiebreak:
    """Three people, three surviving branches (bC a cheap reference option,
    bA/bB the genuine contenders) — bA and bB tie on max regret (8), and
    the tie is broken by comparing the second-highest regret. Hand-computed:

    Priya:  bC=100 (own min), bA=108, bB=108.
      regret(bC)=0, regret(bA)=8, regret(bB)=8
    Arjun:  bC=50 (own min), bA=53, bB=55.
      regret(bC)=0, regret(bA)=3, regret(bB)=5
    Dadi:   bB=20 (own min), bA=21, bC=40.
      regret(bB)=0, regret(bA)=1, regret(bC)=20

    Per-branch regret vectors (sorted descending):
      bA: (8, 3, 1) -> max = 8
      bB: (8, 5, 0) -> max = 8
      bC: (20, 0, 0) -> max = 20 (loses outright, not part of the tie)

    bA and bB tie on the max (8 == 8). Compare the second-highest: bA's is
    3, bB's is 5. 3 < 5, so bA wins the leximin refinement.
    """

    def test_second_highest_regret_breaks_the_tie(self) -> None:
        priya = _profile("person-priya", {"branch-c": 100.0, "branch-a": 108.0, "branch-b": 108.0})
        arjun = _profile("person-arjun", {"branch-c": 50.0, "branch-a": 53.0, "branch-b": 55.0})
        dadi = _profile("person-dadi", {"branch-b": 20.0, "branch-a": 21.0, "branch-c": 40.0})

        result = resolve(
            surviving_branch_ids=(NodeId("branch-a"), NodeId("branch-b"), NodeId("branch-c")),
            eliminated_branch_ids=(),
            valuation_profiles=(priya, arjun, dadi),
        )

        assert result.winning_branch_id == NodeId("branch-a")
        assert result.regret_by_person == {
            NodeId("person-priya"): 8.0,
            NodeId("person-arjun"): 3.0,
            NodeId("person-dadi"): 1.0,
        }
        assert result.most_costly_to == NodeId("person-priya")
        assert result.most_favorable_to == NodeId("person-dadi")
        assert set(result.conceding_person_ids) == {
            NodeId("person-priya"),
            NodeId("person-arjun"),
            NodeId("person-dadi"),
        }


class TestDifferentLengthLeximinVectors:
    """A genuine leximin tie where the sparse-cost policy has excluded a
    different number of profiles from each tied branch, so the two
    branches' descending-regret tuples have different lengths. Documented
    behaviour: Python tuple comparison treats a shorter, true-prefix
    vector as smaller (wins the tie). Hand-computed:

    P1: b1=10 (own min), b2=20 -> regret(b1)=0, regret(b2)=10. (b3 never
        priced by P1 -> P1 contributes no entry to b3's regret dict at all.)
    P2: b1=8, b2=8, b3=8 (own min=8, fully priced) -> regret(b1)=0,
        regret(b2)=0, regret(b3)=0.

    b1: {P1:0, P2:0} -> sorted desc (0, 0)
    b2: {P1:10, P2:0} -> sorted desc (10, 0) -> max 10, loses outright
    b3: {P2:0} (P1 excluded — never priced it) -> sorted desc (0,)

    b1's vector (0, 0) and b3's vector (0,) tie on the only element b3
    has; b3's vector is a true prefix of b1's and is therefore considered
    smaller by ordinary tuple comparison -> b3 wins.
    """

    def test_shorter_prefix_vector_wins_the_tie(self) -> None:
        p1 = _profile("person-p1", {"branch-1": 10.0, "branch-2": 20.0})
        p2 = _profile("person-p2", {"branch-1": 8.0, "branch-2": 8.0, "branch-3": 8.0})

        result = resolve(
            surviving_branch_ids=(NodeId("branch-1"), NodeId("branch-2"), NodeId("branch-3")),
            eliminated_branch_ids=(),
            valuation_profiles=(p1, p2),
        )

        assert result.winning_branch_id == NodeId("branch-3")
        assert result.regret_by_person == {NodeId("person-p2"): 0.0}


class TestHardConstraintElimination:
    """An eliminated branch never appears in any profile's cost dict at
    all (Phase 4 interest scoring never asks a delegate to price an
    eliminated option) — and must never be selectable, even though other
    surviving branches are genuinely priced and scored."""

    def test_eliminated_branch_is_never_selectable(self) -> None:
        priya = _profile("person-priya", {"branch-sedan": 10.0, "branch-hatchback": 5.0})
        arjun = _profile("person-arjun", {"branch-sedan": 8.0, "branch-hatchback": 12.0})

        result = resolve(
            surviving_branch_ids=(NodeId("branch-sedan"), NodeId("branch-hatchback")),
            eliminated_branch_ids=(NodeId("branch-suv-too-tall-for-dad"),),
            valuation_profiles=(priya, arjun),
        )

        assert result.winning_branch_id != NodeId("branch-suv-too-tall-for-dad")
        assert result.winning_branch_id in (NodeId("branch-sedan"), NodeId("branch-hatchback"))
        assert result.eliminated_branch_ids == (NodeId("branch-suv-too-tall-for-dad"),)


class TestSparseCostPolicy:
    """The documented missing-value policy, at both granularities:

    P1: b1=10, b2=20 (b3 never priced at all). Own min = 10 (b1).
      regret(b1) = 0, regret(b2) = 10. P1 contributes NO entry to b3's
      regret dict (never fabricated as 0.0 or +inf).
    P2: b1=8, b2=6, b3=10 (fully priced). Own min = 6 (b2).
      regret(b1) = 2, regret(b2) = 0, regret(b3) = 4.
    P3: {} — priced nothing for this decision at all. Has no reference
      minimum of its own, so P3 contributes NO entry anywhere (not to
      b1, b2, or b3) — fully excluded, not just from b3.

    Regret matrix:
      b1: {P1:0, P2:2} -> max = 2
      b2: {P1:10, P2:0} -> max = 10
      b3: {P2:4} (P1 and P3 both excluded) -> max = 4

    b1 has the lowest max regret (2) -> b1 wins, cleanly, no tie.
    """

    def test_missing_single_branch_price_excludes_only_that_branch(self) -> None:
        p1 = _profile("person-p1", {"branch-1": 10.0, "branch-2": 20.0})
        p2 = _profile("person-p2", {"branch-1": 8.0, "branch-2": 6.0, "branch-3": 10.0})
        p3 = _profile("person-p3", {})

        result = resolve(
            surviving_branch_ids=(NodeId("branch-1"), NodeId("branch-2"), NodeId("branch-3")),
            eliminated_branch_ids=(),
            valuation_profiles=(p1, p2, p3),
        )

        assert result.winning_branch_id == NodeId("branch-1")
        assert result.regret_by_person == {
            NodeId("person-p1"): 0.0,
            NodeId("person-p2"): 2.0,
        }
        assert NodeId("person-p3") not in result.regret_by_person
        assert result.most_costly_to == NodeId("person-p2")
        assert result.most_favorable_to == NodeId("person-p1")
        assert result.conceding_person_ids == (NodeId("person-p2"),)


class TestEmptyAndNoSignalErrors:
    def test_empty_surviving_branches_raises(self) -> None:
        with pytest.raises(NoSurvivingBranchesError):
            resolve(
                surviving_branch_ids=(),
                eliminated_branch_ids=(NodeId("branch-eliminated"),),
                valuation_profiles=(_profile("person-p1", {"branch-eliminated": 5.0}),),
            )

    def test_no_profile_has_any_surviving_cost_raises(self) -> None:
        # Every profile's costs reference only a branch that is NOT in the
        # surviving set — genuinely zero signal for any surviving branch.
        p1 = _profile("person-p1", {"branch-not-surviving": 5.0})
        p2 = _profile("person-p2", {})

        with pytest.raises(NoCostSignalError):
            resolve(
                surviving_branch_ids=(NodeId("branch-1"), NodeId("branch-2")),
                eliminated_branch_ids=(),
                valuation_profiles=(p1, p2),
            )

    def test_no_signal_error_is_a_council_arbiter_error(self) -> None:
        assert issubclass(NoCostSignalError, CouncilArbiterError)
        assert issubclass(NoSurvivingBranchesError, CouncilArbiterError)


class TestInputValidation:
    def test_duplicate_surviving_branch_ids_rejected(self) -> None:
        with pytest.raises(ValueError, match="duplicate"):
            resolve(
                surviving_branch_ids=(NodeId("branch-1"), NodeId("branch-1")),
                eliminated_branch_ids=(),
                valuation_profiles=(_profile("person-p1", {"branch-1": 1.0}),),
            )

    def test_overlap_between_surviving_and_eliminated_rejected(self) -> None:
        with pytest.raises(ValueError, match="both"):
            resolve(
                surviving_branch_ids=(NodeId("branch-1"),),
                eliminated_branch_ids=(NodeId("branch-1"),),
                valuation_profiles=(_profile("person-p1", {"branch-1": 1.0}),),
            )

    def test_duplicate_person_profiles_rejected(self) -> None:
        first = _profile("person-p1", {"branch-1": 1.0})
        second = _profile("person-p1", {"branch-1": 2.0})
        with pytest.raises(ValueError, match="duplicate"):
            resolve(
                surviving_branch_ids=(NodeId("branch-1"),),
                eliminated_branch_ids=(),
                valuation_profiles=(first, second),
            )
