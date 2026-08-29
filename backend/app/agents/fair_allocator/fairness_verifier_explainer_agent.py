"""A19 — Fairness Verifier / Explainer (spec §8.3 Stage 4, §15.8).

*Responsibility:* two genuinely distinct halves, per spec's own wording:

1. **Verification is deterministic.** Checks the EF1 property holds on an
   already-produced `app.solvers.fair_allocation.FairAllocationResult`
   via `app.solvers.fair_allocation.verify_ef1` — a real external
   checkable signal, not LLM self-critique (spec §15.8: "verification
   against an external checkable signal, deliberately avoiding LLM
   self-critique"). This half makes **no model call at all**.
2. **Explanation is Pro-tier.** Explains each person's own share using
   *their own* real `ValuationProfile.costs` values — never a generic
   explanation, never another person's valuations.

*Forbidden:* **altering the allocation.** This module holds no path back
into the solver (it never calls `solve_fair_allocation`) and no write
tool that could touch an `Obligation`'s `owned_by` edge — its only import
from `app.solvers.fair_allocation` is `verify_ef1` and the two read-only
result/error types it needs, nothing that could construct or mutate an
allocation.
"""

from __future__ import annotations

import uuid

from contracts.agents import ModelTier
from contracts.graph_types import AgentId, NodeId

from ...prompts.loader import load_prompt
from ...reasoning.gemini_client import GeminiClient
from ...solvers.fair_allocation import CostMatrix, EF1Violation, FairAllocationResult, verify_ef1
from .json_utils import parse_json_response, require_float, require_str
from .types import (
    BundleComparison,
    FairnessVerificationResult,
    PersonShareExplanation,
    ShareExplanationRequest,
)

AGENT_ID = AgentId("A19")


def _bundles(result: FairAllocationResult) -> dict[NodeId, set[NodeId]]:
    bundles: dict[NodeId, set[NodeId]] = {person_id: set() for person_id in result.order}
    for task_id, person_id in result.allocation.items():
        bundles.setdefault(person_id, set()).add(task_id)
    return bundles


def _own_bundle_block(request: ShareExplanationRequest) -> str:
    if not request.own_costs:
        return "(no tasks in this person's bundle)"
    lines = [
        f'- "{request.own_task_descriptions[task_id]}": costs you {cost:.2f}'
        for task_id, cost in request.own_costs.items()
    ]
    return "\n".join(lines)


def _comparisons_block(request: ShareExplanationRequest) -> str:
    if not request.comparisons:
        return "(no other household members to compare against)"
    lines = []
    for comparison in request.comparisons:
        tasks = ", ".join(f'"{d}"' for d in comparison.other_person_task_descriptions) or "(nothing)"
        lines.append(
            f"- {comparison.other_person_id}'s bundle ({tasks}) would cost you "
            f"{comparison.cost_to_this_person:.2f} in your own terms"
        )
    return "\n".join(lines)


def _fairness_result_block(request: ShareExplanationRequest) -> str:
    if request.ef1_holds_for_this_person:
        return "Fair (EF1 holds for you): under your own valuation, you do not envy anyone here."
    return (
        "Fair up to one item (EF1), but real envy exists before the one-item relaxation: "
        f"{request.violation_detail}"
    )


class FairnessVerifierExplainerAgent:
    """A19 Fairness Verifier / Explainer. Dependency-injected on a
    `GeminiClient` only — no `GraphWriter`, no solver-construction import,
    no path back to the allocation (see this module's docstring)."""

    def __init__(self, *, gemini_client: GeminiClient) -> None:
        self._gemini_client = gemini_client

    def verify_and_explain(
        self,
        *,
        result: FairAllocationResult,
        costs: CostMatrix,
        task_descriptions: dict[str, str],
    ) -> FairnessVerificationResult:
        """Runs both halves for one completed solve.

        Args:
            result: the solver's own output — never reconstructed here.
            costs: the exact cost matrix that produced `result` — used
                only to read each person's own row; never cross-used.
            task_descriptions: task id (as `str`) -> human-readable
                description, for every task in `result.allocation`.

        Returns:
            A `FairnessVerificationResult` carrying both the deterministic
            verdict and one Pro-tier explanation per person.

        Raises:
            app.solvers.fair_allocation.IncompleteCostCoverageError:
                `costs` lacks a priced entry needed to compute the check
                for some ordered pair.
            errors.ModelResponseMalformed: an explanation call's response
                could not be parsed as the expected JSON shape.
        """
        violations = verify_ef1(result, costs)
        violating_enviers = {violation.envier for violation in violations}
        bundles = _bundles(result)
        prompt = load_prompt("A19")

        explanations: list[PersonShareExplanation] = []
        for person_id in result.order:
            own_bundle = tuple(sorted(bundles[person_id], key=str))
            explanation_request = self._build_explanation_request(
                person_id=person_id,
                own_bundle=own_bundle,
                bundles=bundles,
                costs=costs,
                task_descriptions=task_descriptions,
                violations=violations,
                person_envies=person_id in violating_enviers,
            )
            explanations.append(self._explain_share(explanation_request, prompt_text=prompt.text))

        return FairnessVerificationResult(
            ef1_holds=not violations,
            violation_count=len(violations),
            explanations=tuple(explanations),
            model_tier="pro",
            prompt_version=prompt.version,
            invocation_id=uuid.uuid4().hex,
        )

    def _build_explanation_request(
        self,
        *,
        person_id: NodeId,
        own_bundle: tuple[NodeId, ...],
        bundles: dict[NodeId, set[NodeId]],
        costs: CostMatrix,
        task_descriptions: dict[str, str],
        violations: tuple[EF1Violation, ...],
        person_envies: bool,
    ) -> ShareExplanationRequest:
        own_costs_row = costs.get(person_id, {})
        own_task_descriptions = {str(t): task_descriptions[str(t)] for t in own_bundle}
        own_costs = {str(t): own_costs_row[t] for t in own_bundle}
        own_total_cost = sum(own_costs.values())

        comparisons = tuple(
            BundleComparison(
                other_person_id=other_id,
                other_person_task_descriptions=tuple(
                    task_descriptions[str(t)] for t in sorted(bundles[other_id], key=str)
                ),
                cost_to_this_person=sum(own_costs_row[t] for t in bundles[other_id]),
            )
            for other_id in sorted(bundles, key=str)
            if other_id != person_id
        )

        violation_detail: str | None = None
        if person_envies:
            for violation in violations:
                if violation.envier == person_id:
                    violation_detail = (
                        f"your bundle costs you {violation.envier_own_bundle_cost:.2f}, and even after "
                        "removing your own single costliest task "
                        f"({violation.envier_worst_own_item_cost:.2f}), that is compared against "
                        f"{violation.envied}'s bundle, which would cost you "
                        f"{violation.envier_cost_for_envied_bundle:.2f}"
                    )
                    break

        return ShareExplanationRequest(
            person_id=person_id,
            own_task_descriptions=own_task_descriptions,
            own_costs=own_costs,
            own_total_cost=own_total_cost,
            comparisons=comparisons,
            ef1_holds_for_this_person=not person_envies,
            violation_detail=violation_detail,
        )

    def _explain_share(self, request: ShareExplanationRequest, *, prompt_text: str) -> PersonShareExplanation:
        rendered = prompt_text.format(
            person_id=request.person_id,
            own_bundle_block=_own_bundle_block(request),
            own_total_cost=f"{request.own_total_cost:.2f}",
            comparisons_block=_comparisons_block(request),
            fairness_result_block=_fairness_result_block(request),
        )
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.PRO, prompt=rendered
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)
        explanation_text = require_str(parsed, "explanation", agent_id=AGENT_ID)
        confidence = require_float(parsed, "confidence", agent_id=AGENT_ID, default=0.0)

        return PersonShareExplanation(
            person_id=request.person_id,
            task_ids=tuple(NodeId(t) for t in request.own_task_descriptions),
            total_cost_to_self=request.own_total_cost,
            explanation_text=explanation_text,
            confidence=confidence,
        )


__all__ = ["AGENT_ID", "FairnessVerifierExplainerAgent"]
