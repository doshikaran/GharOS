import { describe, expect, it } from "vitest";
import type { GraphEdge, GraphNode } from "./graph-types";
import { applyGraphFilters, EMPTY_GRAPH_FILTER_STATE, hasActiveFilters, type GraphFilterState } from "./graph-filters";

function node(overrides: Partial<GraphNode> & Pick<GraphNode, "id" | "type">): GraphNode {
  return {
    label: overrides.id,
    derivation: "extracted",
    confidence: 0.9,
    source_document_id: null,
    region: null,
    created_at: "2026-08-20T00:00:00Z",
    fields: {},
    ...overrides,
  };
}

function edge(overrides: Partial<GraphEdge> & Pick<GraphEdge, "id" | "from_id" | "to_id" | "type">): GraphEdge {
  return {
    derivation: "extracted",
    confidence: 0.9,
    is_conflict: false,
    ...overrides,
  };
}

const priya = node({ id: "person-priya", type: "PERSON", label: "Priya" });
const aarav = node({ id: "person-aarav", type: "PERSON", label: "Aarav" });
const obligation = node({ id: "obligation-1", type: "OBLIGATION", label: "Pay maintenance" });
const vendor = node({ id: "vendor-1", type: "VENDOR", label: "Om Electricals", derivation: "inferred" });
const pattern = node({
  id: "pattern-1",
  type: "PATTERN",
  label: "Late payments",
  derivation: "ambiguous",
  created_at: "2026-08-25T00:00:00Z",
});

const nodes = [priya, aarav, obligation, vendor, pattern];

const edges = [
  edge({ id: "e1", from_id: "obligation-1", to_id: "person-priya", type: "owned_by" }),
  edge({ id: "e2", from_id: "obligation-1", to_id: "vendor-1", type: "paid_for" }),
  edge({ id: "e3", from_id: "person-aarav", to_id: "pattern-1", type: "benefits" }),
];

describe("applyGraphFilters", () => {
  it("returns everything unchanged when no filter dimension is engaged", () => {
    const result = applyGraphFilters(nodes, edges, EMPTY_GRAPH_FILTER_STATE);
    expect(result.nodes).toHaveLength(nodes.length);
    expect(result.edges).toHaveLength(edges.length);
  });

  it("filters by type (multi-select)", () => {
    const filters: GraphFilterState = { ...EMPTY_GRAPH_FILTER_STATE, types: ["PERSON", "VENDOR"] };
    const result = applyGraphFilters(nodes, edges, filters);
    expect(result.nodes.map((n) => n.id).sort()).toEqual(["person-aarav", "person-priya", "vendor-1"]);
  });

  it("filters by derivation (multi-select)", () => {
    const filters: GraphFilterState = { ...EMPTY_GRAPH_FILTER_STATE, derivations: ["ambiguous"] };
    const result = applyGraphFilters(nodes, edges, filters);
    expect(result.nodes.map((n) => n.id)).toEqual(["pattern-1"]);
  });

  it("filters by time window (inclusive from/to)", () => {
    const filters: GraphFilterState = {
      ...EMPTY_GRAPH_FILTER_STATE,
      timeWindow: { from: "2026-08-22T00:00:00Z", to: null },
    };
    const result = applyGraphFilters(nodes, edges, filters);
    expect(result.nodes.map((n) => n.id)).toEqual(["pattern-1"]);
  });

  it("excludes a node with no created_at from an engaged time-window filter", () => {
    const undated = node({ id: "undated-1", type: "PATTERN", label: "Undated", created_at: null });
    const filters: GraphFilterState = {
      ...EMPTY_GRAPH_FILTER_STATE,
      timeWindow: { from: "2020-01-01T00:00:00Z", to: null },
    };
    const result = applyGraphFilters([undated], [], filters);
    expect(result.nodes).toHaveLength(0);
  });

  it("filters by person: the PERSON node itself, plus nodes connected via an association edge, either direction", () => {
    const filters: GraphFilterState = { ...EMPTY_GRAPH_FILTER_STATE, personId: "person-priya" };
    const result = applyGraphFilters(nodes, edges, filters);
    // obligation-1 -owned_by-> person-priya is a PERSON_ASSOCIATION_EDGE_TYPES edge.
    expect(result.nodes.map((n) => n.id).sort()).toEqual(["obligation-1", "person-priya"]);
  });

  it("does not treat a non-association edge type as a person association", () => {
    // obligation-1 -paid_for-> vendor-1 is NOT in PERSON_ASSOCIATION_EDGE_TYPES,
    // so vendor-1 must not appear when filtering on an unrelated person.
    const filters: GraphFilterState = { ...EMPTY_GRAPH_FILTER_STATE, personId: "person-aarav" };
    const result = applyGraphFilters(nodes, edges, filters);
    expect(result.nodes.map((n) => n.id).sort()).toEqual(["pattern-1", "person-aarav"]);
  });

  it("drops any edge touching a filtered-out node — never shows a dangling edge", () => {
    const filters: GraphFilterState = { ...EMPTY_GRAPH_FILTER_STATE, types: ["PERSON"] };
    const result = applyGraphFilters(nodes, edges, filters);
    // e1 (obligation -> priya) must disappear because obligation-1 is filtered out,
    // even though priya (one endpoint) is visible.
    expect(result.edges).toHaveLength(0);
  });

  it("combines multiple engaged dimensions with AND semantics", () => {
    const filters: GraphFilterState = {
      ...EMPTY_GRAPH_FILTER_STATE,
      types: ["OBLIGATION", "VENDOR"],
      derivations: ["inferred"],
    };
    const result = applyGraphFilters(nodes, edges, filters);
    expect(result.nodes.map((n) => n.id)).toEqual(["vendor-1"]);
  });
});

describe("hasActiveFilters", () => {
  it("is false for the empty state", () => {
    expect(hasActiveFilters(EMPTY_GRAPH_FILTER_STATE)).toBe(false);
  });

  it("is true when any single dimension is engaged", () => {
    expect(hasActiveFilters({ ...EMPTY_GRAPH_FILTER_STATE, personId: "person-priya" })).toBe(true);
    expect(hasActiveFilters({ ...EMPTY_GRAPH_FILTER_STATE, types: ["PERSON"] })).toBe(true);
    expect(hasActiveFilters({ ...EMPTY_GRAPH_FILTER_STATE, derivations: ["extracted"] })).toBe(true);
    expect(
      hasActiveFilters({ ...EMPTY_GRAPH_FILTER_STATE, timeWindow: { from: null, to: "2026-01-01T00:00:00Z" } }),
    ).toBe(true);
  });
});
