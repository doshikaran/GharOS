"""A3c — Verification Agent (spec §15.2, §5.5).

*Responsibility:* given a verification document (a receipt, primarily —
spec §5.5's "strongest verification document in the system"), judge what
it confirms or contradicts in the existing graph: does a purchased item
verify or contradict a household CONSTRAINT, does an expected item never
appear (`absent_from`).
*Model tier:* Pro-tier — unlike A2-A6, this agent's core act is
*judgment* ("does this purchased item violate this constraint?"), not
literal extraction, so `Derivation.INFERRED` is the correct tag for the
edges it produces (see the derivation note below — this is deliberate,
not a violation of A3's "never infer" rule, because A3c is not an
extraction agent).
*Forbidden:* **silently overwriting a contradicted graph claim.** When
this agent's verdict disagrees with an existing `verifies`/`contradicts`
edge on the same constraint, it never removes or supersedes the prior
edge — it adds its own new edge alongside it and returns a `Discrepancy`
record for a human to see both. `verify_against_constraints` has no
`GraphWriter` dependency at all — it is structurally incapable of writing
to Firestore, let alone overwriting anything there (Layer 3 reasoning
agent; a future writer agent applies its output).

**A note on `Derivation.INFERRED` here, for anyone comparing this module
against `document_extraction.py`'s "never infer" rule:** A3 (extraction)
and A3c (verification) are different agents with different jobs by
design (spec §15.2) — A3 is forbidden from inferring because it launders
hallucination as literal fact; A3c's entire job *is* judgment over
already-extracted, already-real purchase items against already-existing
graph constraints, exactly the same category of reasoning spec §7.6
assigns to the Constraint Checker (A13, Phase 4: "does 'may contain
traces' violate a nut allergy? — yes, but that's judgment"). Tagging its
edges `INFERRED` is honest, not a loophole — the graph's own provenance
model exists precisely so a reader can tell these two kinds of claim
apart at a glance (solid vs dashed edges, spec §5.8).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from contracts.agents import AgentOutput, ModelTier
from contracts.graph_types import (
    AgentId,
    Constraint,
    Derivation,
    Edge,
    EdgeId,
    EdgeType,
    NodeId,
    Provenance,
    PurchaseItem,
    SourceRef,
)
from contracts.repositories import GraphReader

from ...prompts.loader import load_prompt
from ...reasoning.gemini_client import GeminiClient
from .json_utils import optional_str, parse_json_response, require_float, require_list, require_str

AGENT_ID = AgentId("A3c")

logger = structlog.get_logger(__name__)


class VerificationVerdict:
    VERIFIES = "verifies"
    CONTRADICTS = "contradicts"
    UNRELATED = "unrelated"


@dataclass(frozen=True, slots=True)
class Discrepancy:
    """Opened whenever this agent's verdict on a constraint disagrees with
    evidence already in the graph — spec §5.5's "never silently overwrite"
    rule made concrete. Always additive: both the old and new edges remain
    in the graph; this record is what tells a human they disagree."""

    constraint_id: NodeId
    new_verdict: str
    conflicting_prior_edge_type: EdgeType
    """`EdgeType.VERIFIES` or `EdgeType.CONTRADICTS` — whichever edge type
    already pointed at this constraint and now disagrees with
    `new_verdict`."""
    detail: str


@dataclass(frozen=True, slots=True)
class AbsentFromFinding:
    """An expected category never appeared on this receipt — spec §5.5's
    "if the nut-free bread never appears on any receipt..." case. Only
    raised for constraints whose `structured` dict explicitly names an
    `expected_category` — never guessed from the constraint's free text."""

    constraint_id: NodeId
    expected_category: str


@dataclass(frozen=True, slots=True)
class VerificationResult:
    agent_output: AgentOutput
    edges: tuple[Edge, ...]
    discrepancies: tuple[Discrepancy, ...]
    absent_from_findings: tuple[AbsentFromFinding, ...]


def _constraints_block(constraints: tuple[Constraint, ...]) -> str:
    lines = []
    for constraint in constraints:
        lines.append(
            f'- id="{constraint.id}" kind={constraint.kind.value} severity={constraint.severity.value} '
            f'structured={constraint.structured} original_text="{constraint.original_text}"'
        )
    return "\n".join(lines) if lines else "(no active constraints to check)"


def _purchase_items_block(purchase_items: tuple[PurchaseItem, ...]) -> str:
    lines = []
    for item in purchase_items:
        lines.append(f'- "{item.description}" (category: {item.normalized_category or "uncategorised"})')
    return "\n".join(lines) if lines else "(no purchase items)"


class VerificationAgent:
    """A3c Verification Agent. Dependency-injected on a `GeminiClient` and
    a `GraphReader` (T0, read-only) — deliberately no `GraphWriter`; see
    module docstring."""

    def __init__(self, *, gemini_client: GeminiClient, graph_reader: GraphReader) -> None:
        self._gemini_client = gemini_client
        self._graph_reader = graph_reader

    def verify_against_constraints(
        self,
        *,
        source_document_id: NodeId,
        purchase_items: tuple[PurchaseItem, ...],
        candidate_constraints: tuple[Constraint, ...],
    ) -> VerificationResult:
        """Judges each of `candidate_constraints` against `purchase_items`.

        Args:
            source_document_id: the receipt's SOURCE_DOCUMENT id.
            purchase_items: this receipt's already-extracted purchase
                items (from the receipt `ExtractionStrategy`'s
                `GraphMappingResult.nodes`, filtered to `PurchaseItem`).
            candidate_constraints: the constraints to check — typically
                every active CONSTRAINT reachable from the household
                members this purchase could plausibly relate to (caller's
                responsibility to select; this agent does not itself
                enumerate "every constraint in the graph").

        Raises:
            ModelResponseMalformed: the model's response could not be
                parsed as the expected JSON shape.
        """
        prompt = load_prompt("A3c")
        rendered = prompt.text.format(
            constraints_block=_constraints_block(candidate_constraints),
            purchase_items_block=_purchase_items_block(purchase_items),
        )
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.PRO, prompt=rendered
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)

        items_by_description = {item.description: item for item in purchase_items}
        constraints_by_id = {constraint.id: constraint for constraint in candidate_constraints}

        edges: list[Edge] = []
        discrepancies: list[Discrepancy] = []
        confidences: list[float] = []

        for raw_judgment in require_list(parsed, "judgments", agent_id=AGENT_ID):
            if not isinstance(raw_judgment, dict):
                continue
            constraint_id = NodeId(require_str(raw_judgment, "constraint_id", agent_id=AGENT_ID))
            verdict = require_str(raw_judgment, "verdict", agent_id=AGENT_ID)
            confidence = require_float(raw_judgment, "confidence", agent_id=AGENT_ID, default=0.0)
            reasoning = require_str(raw_judgment, "reasoning", agent_id=AGENT_ID)
            matched_description = optional_str(raw_judgment, "matched_item_description")
            confidences.append(confidence)

            if verdict == VerificationVerdict.UNRELATED or constraint_id not in constraints_by_id:
                continue

            matched_item = items_by_description.get(matched_description) if matched_description else None
            if matched_item is None:
                logger.warning(
                    "agents.intake.a3c.unmatched_item_reference",
                    constraint_id=str(constraint_id),
                    matched_description=matched_description,
                )
                continue

            edge_type = EdgeType.VERIFIES if verdict == VerificationVerdict.VERIFIES else EdgeType.CONTRADICTS
            matched_source_ref = matched_item.provenance.source_ref
            item_region = matched_source_ref.region if matched_source_ref is not None else ""
            edges.append(
                Edge(
                    id=EdgeId(uuid.uuid4().hex),
                    provenance=Provenance(
                        derivation=Derivation.INFERRED,
                        source_ref=SourceRef(source_document_id=source_document_id, region=item_region),
                        confidence=confidence,
                        deriving_agent=AGENT_ID,
                        created_at=datetime.now(UTC),
                    ),
                    edge_type=edge_type,
                    from_id=matched_item.id,
                    to_id=constraint_id,
                    metadata={"reasoning": reasoning},
                )
            )

            opposite_edge_type = EdgeType.CONTRADICTS if edge_type is EdgeType.VERIFIES else EdgeType.VERIFIES
            prior_conflicting = self._graph_reader.neighbours(constraint_id, opposite_edge_type)
            if prior_conflicting:
                discrepancies.append(
                    Discrepancy(
                        constraint_id=constraint_id,
                        new_verdict=verdict,
                        conflicting_prior_edge_type=opposite_edge_type,
                        detail=(
                            f"new evidence from {source_document_id} says '{verdict}' for constraint "
                            f"{constraint_id}, but {len(prior_conflicting)} prior "
                            f"{opposite_edge_type.value} edge(s) already exist for it — "
                            "both are retained; escalate for human review, never auto-resolved."
                        ),
                    )
                )
                logger.warning(
                    "agents.intake.a3c.discrepancy_opened",
                    constraint_id=str(constraint_id),
                    new_verdict=verdict,
                    prior_edge_type=opposite_edge_type.value,
                )

        absent_from_findings = self._check_absent_from(
            candidate_constraints=candidate_constraints, purchase_items=purchase_items
        )

        overall_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        agent_output = AgentOutput(
            invocation_id=uuid.uuid4().hex,
            agent_id=AGENT_ID,
            model_tier=ModelTier.PRO,
            prompt_version=prompt.version,
            confidence=overall_confidence,
            derivation=Derivation.INFERRED,
            citations=(),
            produced_at=datetime.now(UTC),
        )
        return VerificationResult(
            agent_output=agent_output,
            edges=tuple(edges),
            discrepancies=tuple(discrepancies),
            absent_from_findings=absent_from_findings,
        )

    def _check_absent_from(
        self, *, candidate_constraints: tuple[Constraint, ...], purchase_items: tuple[PurchaseItem, ...]
    ) -> tuple[AbsentFromFinding, ...]:
        """spec §5.5: "if the nut-free bread never appears on any receipt,
        the constraint the system believes it is honouring is not
        actually being honoured." Deterministic, not LLM-judged — only
        fires for a constraint whose `structured` dict explicitly names
        `expected_category`; never inferred from the constraint's free
        text."""
        present_categories = {item.normalized_category for item in purchase_items if item.normalized_category}
        findings: list[AbsentFromFinding] = []
        for constraint in candidate_constraints:
            expected_category = constraint.structured.get("expected_category")
            if expected_category and expected_category not in present_categories:
                findings.append(
                    AbsentFromFinding(constraint_id=constraint.id, expected_category=expected_category)
                )
        return tuple(findings)


__all__ = [
    "AGENT_ID",
    "AbsentFromFinding",
    "Discrepancy",
    "VerificationAgent",
    "VerificationResult",
    "VerificationVerdict",
]
