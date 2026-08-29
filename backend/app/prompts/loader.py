"""Prompt loader — ADR-003's versioned-prompt convention made loadable in
code.

Every LLM-backed agent in `backend/app/agents/intake/` (and every roster
agent built after it) reads its instruction text through
`load_prompt(agent_id)` rather than an inline string literal or a
hand-typed file path, so `manifest.json` stays the single place a prompt
version is pinned (PHASES.md Phase 15: "prompt versions pinned"), and so
every `contracts.agents.AgentOutput.prompt_version` an agent records is
provably the version whose text actually ran, not a guess.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent
_MANIFEST_PATH = _PROMPTS_DIR / "manifest.json"

_AGENT_DIR_NAMES: dict[str, str] = {
    "A2": "a2_intake_router",
    "A3": "a3_document_extraction",
    "A3b": "a3b_line_item_extraction",
    "A3c": "a3c_verification",
    "A4": "a4_message_normalization",
    "A5": "a5_entity_resolution",
    "A6": "a6_relevance_classifier",
    "A12": "a12_implication_agent",
    "A13": "a13_constraint_checker",
    "A14": "a14_conflict_radar",
    "A16": "a16_constraint_learner",
    "A28": "a28_reconciliation_agent",
    "A29": "a29_leakage_detection",
    "A30": "a30_recovery_drafting",
    "A32": "a32_dispute_branch",
    "A34": "a34_staff_payroll",
    "A17": "a17_interviewer",
    "A17_ANSWER": "a17_interviewer_answer",
    "A18": "a18_valuation_extraction",
    "A19": "a19_fairness_verifier_explainer",
    "A20": "a20_renegotiation_trigger",
    "A21": "a21_load_monitor",
    "A22": "a22_intention_capture",
    "A23": "a23_blocker_diagnosis",
    "A24_INFO": "a24_unblocker_information",
    "A24_DECISION": "a24_unblocker_decision",
    "A24_AVERSION": "a24_unblocker_aversion",
    "A24_FIRST_STEP": "a24_unblocker_first_step",
    "A25_COUNTERPARTY": "a25_window_scheduling_counterparty",
    "A26": "a26_slippage_analyst",
    "A35": "a35_decision_framing",
    "A36_QUERY": "a36_grounding_query",
    "A36_RELEVANCE": "a36_grounding_relevance",
    "A37": "a37_path_simulator",
    "A38": "a38_consistency_critic",
    "A39": "a39_calibration",
    "A40": "a40_decision_synthesizer",
    "A40_FOLLOWUP": "a40_decision_synthesizer_followup",
    "A40_BACKWARD": "a40_decision_synthesizer_backward",
    "A41": "a41_council_convener",
    "A42": "a42_finance_specialist",
    "A43": "a43_care_specialist",
    "A44": "a44_education_specialist",
    "A45": "a45_logistics_specialist",
    "A46": "a46_legal_specialist",
    "A47": "a47_member_delegate",
    "A48": "a48_council_adversary",
    "A50": "a50_requirement_clarifier",
    "A52": "a52_provider_ranking",
    "A53": "a53_call_planner",
    "A55": "a55_confirmation_verifier",
}
"""Maps a roster agent id to its `backend/app/prompts/<dir>/` directory
name (ADR-003: "one directory per agent... named by agent ID in lowercase
with its short name"). Extended by later phases as new LLM-backed agents
are built — never pre-populated ahead of the agent that uses it.

`"A17_ANSWER"` is a deliberate, minimal extension of that convention, not
a new roster agent: A17 (Interviewer) genuinely needs two distinct
prompts for two genuinely distinct reasoning jobs at two distinct tiers
(Pro-tier next-comparison selection vs. Flash-tier free-text answer
parsing — spec §15.8 A17's own tier split), unlike A3/A3b/A3c which are
three separate roster agents each with one prompt. Every `AgentOutput`-
shaped result A17 produces still records `AgentId("A17")` — this second
manifest key is purely a prompt-loading implementation detail, never
conflated with agent identity.

`"A24_INFO"`/`"A24_DECISION"`/`"A24_AVERSION"`/`"A24_FIRST_STEP"` extend
the same convention for A24 (Unblocker/Preparation, Phase 9): four
genuinely distinct reasoning jobs (fetch, narrow, switch modality,
decompose) per blocker type it handles, at two distinct tiers (spec
§15.9 A24: "Flash for retrieval, Pro-tier for narrowing/drafting").
`"A25_COUNTERPARTY"` is the same pattern for A25's one genuinely
unstructured reasoning job (interpreting `Provider.availability_notes`
free text) — A25's other two signals (person schedule, historical
likelihood) are deterministic and make no model call at all, so need no
prompt. Every result these produce still records `AgentId("A24")` /
`AgentId("A25")` respectively — these manifest keys are prompt-loading
details only, never agent identity.

`"A36_QUERY"`/`"A36_RELEVANCE"` extend the same convention for A36
(Grounding/Research, Phase 11): two genuinely distinct reasoning jobs at
two distinct tiers (spec §15.8 A36: "Flash retrieval, Pro-tier
relevance") — constructing a real search query is Flash, filtering
already-retrieved grounding results for relevance to the branch's actual
topic is Pro-tier. `"A40_FOLLOWUP"`/`"A40_BACKWARD"` extend it for A40
(Decision Synthesizer, Phase 11): three genuinely distinct jobs at the
same Pro-tier (assembling the forward-mode brief, answering an
interrogation-mode follow-up, and backward-mode failure-point synthesis
— ADR-017 decision 3). Every result these produce still records
`AgentId("A36")` / `AgentId("A40")` respectively."""


class PromptNotFound(RuntimeError):
    """Raised when `agent_id` has no manifest entry, no known directory
    mapping, or the manifest-pinned version file does not exist on disk.
    A missing prompt must fail loudly — an agent silently falling back to
    no instruction at all would be worse than crashing."""

    def __init__(self, *, agent_id: str, detail: str) -> None:
        self.agent_id = agent_id
        self.detail = detail
        super().__init__(f"prompt not found for agent '{agent_id}': {detail}")


@dataclass(frozen=True, slots=True)
class LoadedPrompt:
    """A resolved prompt: the exact version pinned in `manifest.json` and
    its full text, ready to interpolate into a call. `version` is what
    every `AgentOutput.prompt_version` this agent produces must record."""

    agent_id: str
    version: str
    text: str


def load_prompt(agent_id: str) -> LoadedPrompt:
    """Resolves `agent_id`'s active prompt version from `manifest.json`
    and reads its text.

    Args:
        agent_id: a roster agent id, e.g. `"A3"` — must be a key in
            `_AGENT_DIR_NAMES`.

    Returns:
        The resolved `LoadedPrompt`.

    Raises:
        PromptNotFound: `agent_id` is not mapped to a prompt directory,
            has no manifest entry, or the pinned version file is missing.
    """
    dir_name = _AGENT_DIR_NAMES.get(agent_id)
    if dir_name is None:
        raise PromptNotFound(agent_id=agent_id, detail="no known prompt directory mapping")

    try:
        manifest = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PromptNotFound(agent_id=agent_id, detail=f"manifest not found at {_MANIFEST_PATH}") from exc

    version = manifest.get(agent_id)
    if not isinstance(version, str) or not version:
        raise PromptNotFound(agent_id=agent_id, detail="no active version pinned in manifest.json")

    version_path = _PROMPTS_DIR / dir_name / f"{version}.md"
    try:
        text = version_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise PromptNotFound(
            agent_id=agent_id, detail=f"pinned version file not found: {version_path}"
        ) from exc

    return LoadedPrompt(agent_id=agent_id, version=version, text=text)


__all__ = ["LoadedPrompt", "PromptNotFound", "load_prompt"]
