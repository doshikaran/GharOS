"""Tests for `app.reasoning.constraint_promotion` — the Memory
Consolidation service's constraint-promotion pass (spec §20, ADR-021
Decision 4).

Pure unit tests only — this module holds no `GraphReader`/`GraphWriter`
of any kind (by design, see the module docstring's "Never writes
anything"), so there is nothing here for the Firestore emulator to
exercise; every test constructs its own `ConstraintMention` pool directly.
"""

from __future__ import annotations

from contracts.actions import RiskTier
from contracts.graph_types import ConstraintKind, ConstraintSeverity, NodeId

from app.reasoning.constraint_promotion import (
    MIN_CONSTRAINT_PROMOTION_SUPPORT,
    ConstraintMention,
    ConstraintPromotionCandidate,
    scan_for_constraint_promotions,
)


def _mention(
    *,
    constraint_id: str,
    source_document_id: str,
    kind: ConstraintKind = ConstraintKind.DIETARY,
    severity: ConstraintSeverity = ConstraintSeverity.SOFT,
    structured: dict[str, str] | None = None,
    original_text: str = "no nuts for Aarav",
) -> ConstraintMention:
    return ConstraintMention(
        constraint_id=NodeId(constraint_id),
        kind=kind,
        severity=severity,
        structured=structured if structured is not None else {"allergen": "nut", "person": "Aarav"},
        original_text=original_text,
        source_document_id=NodeId(source_document_id),
    )


def test_repeated_dietary_mentions_produce_a_pending_candidate_never_an_effective_constraint() -> None:
    """The spec §20 worked example: three independent mentions of the same
    nut-allergy signal, each from a distinct SOURCE_DOCUMENT, meets the
    MIN_CONSTRAINT_PROMOTION_SUPPORT=3 threshold and produces exactly one
    `ConstraintPromotionCandidate` — never a real, already-effective
    `contracts.graph_types.Constraint` node (this module cannot construct
    one at all: `Constraint` is never imported here)."""
    mentions = (
        _mention(constraint_id="c1", source_document_id="doc-1", original_text="no nuts for Aarav please"),
        _mention(constraint_id="c2", source_document_id="doc-2", original_text="Aarav is allergic to nuts"),
        _mention(constraint_id="c3", source_document_id="doc-3", original_text="no nuts for Aarav please"),
    )

    candidates = scan_for_constraint_promotions(mentions)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert isinstance(candidate, ConstraintPromotionCandidate)
    # The safety-critical assertion: structurally pinned, not "usually" pending.
    assert candidate.status == "pending_confirmation"
    assert candidate.severity is ConstraintSeverity.HARD
    assert candidate.kind is ConstraintKind.DIETARY
    assert candidate.structured == {"allergen": "nut", "person": "Aarav"}
    assert candidate.support_count == 3
    assert candidate.contributing_constraint_ids == (NodeId("c1"), NodeId("c2"), NodeId("c3"))
    assert candidate.contributing_source_document_ids == (NodeId("doc-1"), NodeId("doc-2"), NodeId("doc-3"))
    # Both distinct original texts preserved, deduplicated, never discarded.
    assert candidate.original_text == "no nuts for Aarav please; Aarav is allergic to nuts"
    assert candidate.recommended_risk_tier is RiskTier.R2_APPROVE
    assert candidate.evidence_bundle.confidence == candidate.confidence
    assert candidate.evidence_bundle.evidence_consulted == ("doc-1", "doc-2", "doc-3")


def test_below_threshold_produces_no_candidate() -> None:
    """Two distinct source documents — one short of
    MIN_CONSTRAINT_PROMOTION_SUPPORT=3 — must never produce a candidate."""
    assert MIN_CONSTRAINT_PROMOTION_SUPPORT == 3
    mentions = (
        _mention(constraint_id="c1", source_document_id="doc-1"),
        _mention(constraint_id="c2", source_document_id="doc-2"),
    )

    candidates = scan_for_constraint_promotions(mentions)

    assert candidates == ()


def test_repeated_mentions_within_one_document_do_not_count_as_separate_support() -> None:
    """Two mentions sharing the same source_document_id are one occurrence
    of support, not two — matches A10/A16's own distinct-source-document
    counting convention."""
    mentions = (
        _mention(constraint_id="c1", source_document_id="doc-1"),
        _mention(constraint_id="c2", source_document_id="doc-1"),
        _mention(constraint_id="c3", source_document_id="doc-2"),
    )

    candidates = scan_for_constraint_promotions(mentions)

    assert candidates == ()


def test_already_hard_mentions_are_not_eligible_for_promotion() -> None:
    """A mention already severity=HARD is already live and authoritative;
    it must not be counted toward — or itself trigger — a promotion."""
    mentions = (
        _mention(constraint_id="c1", source_document_id="doc-1", severity=ConstraintSeverity.HARD),
        _mention(constraint_id="c2", source_document_id="doc-2", severity=ConstraintSeverity.HARD),
        _mention(constraint_id="c3", source_document_id="doc-3", severity=ConstraintSeverity.HARD),
    )

    candidates = scan_for_constraint_promotions(mentions)

    assert candidates == ()


def test_different_structured_signatures_are_not_merged() -> None:
    """A different allergen is a different rule — three mentions of "nut"
    plus two of "dairy" must not combine into one five-mention candidate,
    and "dairy" alone (2 < 3) must not produce a candidate of its own."""
    mentions = (
        _mention(constraint_id="c1", source_document_id="doc-1", structured={"allergen": "nut"}),
        _mention(constraint_id="c2", source_document_id="doc-2", structured={"allergen": "nut"}),
        _mention(constraint_id="c3", source_document_id="doc-3", structured={"allergen": "nut"}),
        _mention(constraint_id="c4", source_document_id="doc-4", structured={"allergen": "dairy"}),
        _mention(constraint_id="c5", source_document_id="doc-5", structured={"allergen": "dairy"}),
    )

    candidates = scan_for_constraint_promotions(mentions)

    assert len(candidates) == 1
    assert candidates[0].structured == {"allergen": "nut"}


def test_confidence_increases_with_support_and_is_capped_below_one() -> None:
    """Worked example, hand-verifiable: confidence at exactly the
    threshold (3) is the R2 confidence floor (0.75); each further distinct
    source document adds 0.05, capped at 0.95."""
    three = scan_for_constraint_promotions(
        (
            _mention(constraint_id="c1", source_document_id="doc-1"),
            _mention(constraint_id="c2", source_document_id="doc-2"),
            _mention(constraint_id="c3", source_document_id="doc-3"),
        )
    )[0]
    assert three.confidence == 0.75

    five = scan_for_constraint_promotions(
        (
            _mention(constraint_id="c1", source_document_id="doc-1"),
            _mention(constraint_id="c2", source_document_id="doc-2"),
            _mention(constraint_id="c3", source_document_id="doc-3"),
            _mention(constraint_id="c4", source_document_id="doc-4"),
            _mention(constraint_id="c5", source_document_id="doc-5"),
        )
    )[0]
    assert five.confidence == 0.85

    many = scan_for_constraint_promotions(
        tuple(_mention(constraint_id=f"c{i}", source_document_id=f"doc-{i}") for i in range(1, 11))
    )[0]
    assert many.confidence == 0.95


def test_module_holds_no_graph_writer_import() -> None:
    """Structural guarantee, not just a docstring claim: this module's
    actual `import`/`from ... import` statements must never name
    `contracts.repositories`, `GraphWriter`, or an approval-gate module —
    so it is physically incapable of writing a live Constraint node, or of
    calling the Approval Gate itself, under any code path. Parses the AST
    rather than grepping raw text, since the module's own docstring
    discusses `GraphWriter` in prose (that discussion is not an import)."""
    import ast

    import app.reasoning.constraint_promotion as module

    source = module.__file__
    assert source is not None
    with open(source, encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=source)

    imported_names: set[str] = set()
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_modules.add(node.module)
            imported_names.update(alias.name for alias in node.names)

    assert "contracts.repositories" not in imported_modules
    assert "GraphWriter" not in imported_names
    assert "GraphReader" not in imported_names
    assert not any("arbitration" in module_name for module_name in imported_modules)
    assert "ApprovalGate" not in imported_names
