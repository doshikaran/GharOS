/**
 * Plain-language connector phrases for `EdgeType.value` (contracts/graph_types.py),
 * used by `JustificationPanel` to render each justification step as a real
 * sentence fragment (e.g. "Obligation ← implied by ← Field trip email")
 * rather than a bare edge-type code.
 *
 * Every edge/type pair prints as `"{active}"` when the step being described
 * is the edge's `from_id` looking at its own outgoing relationship, or
 * `"{passive}"` when the step is the edge's `to_id` (the relationship's
 * target) — `connectorPhrase` below picks the right one.
 */

interface PhrasePair {
  readonly active: string;
  readonly passive: string;
}

const EDGE_PHRASES: Record<string, PhrasePair> = {
  states: { active: "states", passive: "stated in" },
  implies: { active: "implies", passive: "implied by" },
  owned_by: { active: "owned by", passive: "owner of" },
  benefits: { active: "benefits", passive: "benefited by" },
  conflicts_with: { active: "conflicts with", passive: "conflicts with" },
  violates: { active: "violates", passive: "violated by" },
  depends_on: { active: "depends on", passive: "depended on by" },
  supersedes: { active: "supersedes", passive: "superseded by" },
  completes_into: { active: "completes into", passive: "completed from" },
  belongs_to: { active: "belongs to", passive: "contains" },
  owed_to: { active: "owed to", passive: "owed by" },
  paid_for: { active: "paid for", passive: "paid for by" },
  contains: { active: "contains", passive: "belongs to" },
  supports: { active: "supports", passive: "supported by" },
  opposes: { active: "opposes", passive: "opposed by" },
  grounded_in: { active: "grounded in", passive: "grounds" },
  resolved_as: { active: "resolved as", passive: "resolution of" },
  conceded_by: { active: "conceded by", passive: "concedes" },
  predicted_by: { active: "predicted by", passive: "predicts" },
  constrains: { active: "constrains", passive: "constrained by" },
  booked_with: { active: "booked with", passive: "booking for" },
  learned_from: { active: "learned from", passive: "source for" },
  line_item_of: { active: "a line item of", passive: "itemised by" },
  discharges: { active: "discharges", passive: "discharged by" },
  verifies: { active: "verifies", passive: "verified by" },
  contradicts: { active: "contradicts", passive: "contradicted by" },
  absent_from: { active: "absent from", passive: "missing" },
  substitutes: { active: "substitutes for", passive: "substituted by" },
  evidences_effort: { active: "evidences effort for", passive: "evidenced by" },
  covers: { active: "covers", passive: "covered by" },
  acts_on: { active: "acts on", passive: "acted on by" },
  authorizes: { active: "authorizes", passive: "authorized by" },
  approved_by: { active: "approved by", passive: "approves" },
};

/**
 * The connector phrase to print between a parent step (already rendered
 * above) and this child step, given the edge that connects them.
 *
 * @param edgeType - `EdgeType.value`, e.g. `"implies"`.
 * @param childIsFromId - true if the step being rendered is the edge's
 *   `from_id` (its own outgoing relationship points at the parent) —
 *   grammatically this reads as the passive form from the parent's side
 *   ("obligation implied by email"); false (the step is `to_id`) reads
 *   as the active form ("obligation contains line item").
 */
export function connectorPhrase(edgeType: string, childIsFromId: boolean): string {
  const pair = EDGE_PHRASES[edgeType];
  const spaced = edgeType.replace(/_/g, " ");
  if (!pair) return childIsFromId ? `${spaced} (reverse)` : spaced;
  return childIsFromId ? pair.passive : pair.active;
}
