/**
 * Historical decision browser — "why did we buy this car?" (PHASES.md
 * Phase 12, E4 work item; spec §12.4's own closing promise; ADR-019's
 * closing note).
 *
 * **No new backend endpoint.** `GET /graph/snapshot` (`lib/graph-api.ts`'s
 * `fetchGraphSnapshot`, the same call `/graph`'s `GraphExplorer` already
 * makes) already returns every current node and edge generically,
 * including `DECISION`/`BRANCH`/`COUNCIL_POSITION` nodes and
 * `conceded_by` edges — A49 Recorder writes them through the same
 * already-generic `FirestoreGraphWriter.write_node`/`write_edge` every
 * other node type uses (ADR-019 Decision 5). This file adds nothing to
 * the fetch path; it only *filters and joins* an already-fetched
 * `GraphSnapshot` client-side, exactly as `lib/graph-filters.ts` already
 * does for the live graph view.
 *
 * Field names read out of `GraphNode.fields` below are the exact
 * snake_case names `contracts/graph_types.py` declares on `Decision` /
 * `Branch` / `CouncilPosition` (`backend/app/graph/serialization.py`
 * writes every dataclass field through untouched — see `lib/graph-types.ts`'s
 * own module docstring):
 *   - `Decision`: `question`, `trigger`, `status`, `resolution_summary`, `rationale`
 *   - `Branch`: `decision_id`, `label`, `projected_impacts`, `grounding_refs`, `critiques`
 *   - `CouncilPosition`: `decision_id`, `held_by_agent`, `stance`, `branch_id`, `reasoning`, `evidence_refs`
 *
 * `fields` is untyped JSON at the wire boundary (`Readonly<Record<string,
 * unknown>>`) — every accessor below narrows defensively rather than
 * trusting the shape, the same discipline `lib/graph-filters.ts` and
 * `lib/graph-state.ts` already apply to snapshot data.
 */

import type { GraphEdge, GraphNode, GraphSnapshot } from "./graph-types";
import type { CouncilStance } from "./council";

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function asStringOrNull(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function asStringArray(value: unknown): readonly string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function asStringRecord(value: unknown): Readonly<Record<string, string>> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return {};
  const out: Record<string, string> = {};
  for (const [key, entry] of Object.entries(value as Record<string, unknown>)) {
    if (typeof entry === "string") out[key] = entry;
  }
  return out;
}

function asStance(value: unknown): CouncilStance {
  return value === "supports" || value === "opposes" || value === "neutral" ? value : "neutral";
}

// ---------------------------------------------------------------------------
// Typed replay shapes, derived from raw GraphNode.fields
// ---------------------------------------------------------------------------

export interface DecisionRecord {
  readonly id: string;
  readonly question: string;
  readonly trigger: string;
  /** `Decision.status` — "open" | "briefed" | "resolved" (ADR-019 Decision
   * 6: the Council itself sets only "briefed"; "resolved" is set only once
   * a human decision is later recorded). */
  readonly status: string;
  readonly resolutionSummary: string | null;
  readonly rationale: string | null;
}

export interface BranchRecord {
  readonly id: string;
  readonly decisionId: string;
  readonly label: string;
  readonly projectedImpacts: Readonly<Record<string, string>>;
  readonly groundingRefs: readonly string[];
  readonly critiques: readonly string[];
}

export interface CouncilPositionRecord {
  readonly id: string;
  readonly decisionId: string;
  readonly heldByAgent: string;
  readonly stance: CouncilStance;
  readonly branchId: string | null;
  readonly reasoning: string;
  readonly evidenceRefs: readonly string[];
}

export interface ConcedingPerson {
  readonly personId: string;
  readonly personLabel: string;
}

export interface DecisionReplay {
  readonly decision: DecisionRecord;
  readonly branches: readonly BranchRecord[];
  readonly positions: readonly CouncilPositionRecord[];
  readonly conceders: readonly ConcedingPerson[];
}

// ---------------------------------------------------------------------------
// Node -> record mapping
// ---------------------------------------------------------------------------

function toDecisionRecord(node: GraphNode): DecisionRecord {
  return {
    id: node.id,
    question: asString(node.fields.question) || node.label,
    trigger: asString(node.fields.trigger),
    status: asString(node.fields.status),
    resolutionSummary: asStringOrNull(node.fields.resolution_summary),
    rationale: asStringOrNull(node.fields.rationale),
  };
}

function toBranchRecord(node: GraphNode): BranchRecord {
  return {
    id: node.id,
    decisionId: asString(node.fields.decision_id),
    label: asString(node.fields.label) || node.label,
    projectedImpacts: asStringRecord(node.fields.projected_impacts),
    groundingRefs: asStringArray(node.fields.grounding_refs),
    critiques: asStringArray(node.fields.critiques),
  };
}

function toCouncilPositionRecord(node: GraphNode): CouncilPositionRecord {
  return {
    id: node.id,
    decisionId: asString(node.fields.decision_id),
    heldByAgent: asString(node.fields.held_by_agent),
    stance: asStance(node.fields.stance),
    branchId: asStringOrNull(node.fields.branch_id),
    reasoning: asString(node.fields.reasoning),
    evidenceRefs: asStringArray(node.fields.evidence_refs),
  };
}

// ---------------------------------------------------------------------------
// Snapshot-wide queries — every function below is a pure filter/join over
// an already-fetched GraphSnapshot, never a fetch of its own.
// ---------------------------------------------------------------------------

/** Every `Decision` node currently in the snapshot, in snapshot order. */
export function listDecisions(snapshot: GraphSnapshot): readonly DecisionRecord[] {
  return snapshot.nodes.filter((node) => node.type === "DECISION").map(toDecisionRecord);
}

/** Case-insensitive substring match over `question` — the browser's search
 * box, per this phase's brief ("a list/search of past Decisions by
 * question"). An empty query returns every decision unfiltered. */
export function searchDecisions(decisions: readonly DecisionRecord[], query: string): readonly DecisionRecord[] {
  const trimmed = query.trim().toLowerCase();
  if (trimmed.length === 0) return decisions;
  return decisions.filter((decision) => decision.question.toLowerCase().includes(trimmed));
}

/** Every `Branch` node naming `decisionId` via its own `decision_id` field. */
export function branchesForDecision(snapshot: GraphSnapshot, decisionId: string): readonly BranchRecord[] {
  return snapshot.nodes
    .filter((node) => node.type === "BRANCH")
    .map(toBranchRecord)
    .filter((branch) => branch.decisionId === decisionId);
}

/** Every `CouncilPosition` node naming `decisionId` via its own
 * `decision_id` field — never inferred from an edge, since A49 Recorder
 * writes `decision_id` directly on the node (ADR-019). */
export function positionsForDecision(snapshot: GraphSnapshot, decisionId: string): readonly CouncilPositionRecord[] {
  return snapshot.nodes
    .filter((node) => node.type === "COUNCIL_POSITION")
    .map(toCouncilPositionRecord)
    .filter((position) => position.decisionId === decisionId);
}

/** Every person who conceded on `decisionId`, resolved via the real
 * `conceded_by` edge (`Decision` -> `Person`, `contracts/graph_types.py`'s
 * `EdgeType.CONCEDED_BY`) rather than re-derived from regret numbers —
 * this is the permanent, already-written record, not a live
 * recomputation. */
export function concedersForDecision(snapshot: GraphSnapshot, decisionId: string): readonly ConcedingPerson[] {
  const personById = new Map(
    snapshot.nodes.filter((node) => node.type === "PERSON").map((node) => [node.id, node] as const),
  );
  const concessionEdges: readonly GraphEdge[] = snapshot.edges.filter(
    (edge) => edge.type === "conceded_by" && edge.from_id === decisionId,
  );
  return concessionEdges.map((edge) => ({
    personId: edge.to_id,
    personLabel: personById.get(edge.to_id)?.label ?? edge.to_id,
  }));
}

/** Assembles the full "why did we make this decision" replay for one
 * `decisionId` — every `Branch`, every `CouncilPosition` naming it, and
 * who conceded, exactly the four things spec §12.4's own "two years
 * later" promise names. Returns `null` when `decisionId` names no real
 * `Decision` node in `snapshot` (defensive — a stale selection after the
 * snapshot refreshes). */
export function buildDecisionReplay(snapshot: GraphSnapshot, decisionId: string): DecisionReplay | null {
  const decisionNode = snapshot.nodes.find((node) => node.type === "DECISION" && node.id === decisionId);
  if (!decisionNode) return null;

  return {
    decision: toDecisionRecord(decisionNode),
    branches: branchesForDecision(snapshot, decisionId),
    positions: positionsForDecision(snapshot, decisionId),
    conceders: concedersForDecision(snapshot, decisionId),
  };
}
