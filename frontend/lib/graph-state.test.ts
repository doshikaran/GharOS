import { describe, expect, it } from "vitest";
import type { GraphNode } from "./graph-types";
import { applySnapshot, applyStreamEvent, createEmptyGraphState, isLiveArrival, listEdges, listNodes } from "./graph-state";

function makeNode(id: string): GraphNode {
  return {
    id,
    type: "OBLIGATION",
    label: id,
    derivation: "extracted",
    confidence: 0.9,
    source_document_id: null,
    region: null,
    created_at: "2026-08-20T00:00:00Z",
    fields: {},
  };
}

describe("graph-state", () => {
  it("starts empty", () => {
    const state = createEmptyGraphState();
    expect(listNodes(state)).toHaveLength(0);
    expect(listEdges(state)).toHaveLength(0);
  });

  it("applySnapshot loads the baseline without marking anything as a live arrival", () => {
    const state = applySnapshot(createEmptyGraphState(), { nodes: [makeNode("a"), makeNode("b")], edges: [] });
    expect(listNodes(state).map((n) => n.id).sort()).toEqual(["a", "b"]);
    expect(isLiveArrival(state, "a", 600, Date.now())).toBe(false);
    expect(isLiveArrival(state, "b", 600, Date.now())).toBe(false);
  });

  it("applyStreamEvent adds a node distinct from the baseline snapshot and flags it as a live arrival", () => {
    const afterSnapshot = applySnapshot(createEmptyGraphState(), { nodes: [makeNode("a")], edges: [] });
    const now = 1_000_000;
    const afterStream = applyStreamEvent(afterSnapshot, { kind: "node", node: makeNode("b") }, now);

    // Both present — the new one is genuinely added, not replacing the baseline.
    expect(listNodes(afterStream).map((n) => n.id).sort()).toEqual(["a", "b"]);

    // Distinct arrival semantics: "a" (snapshot) never counts as a live
    // arrival; "b" (stream) does, right after arriving.
    expect(isLiveArrival(afterStream, "a", 600, now)).toBe(false);
    expect(isLiveArrival(afterStream, "b", 600, now)).toBe(true);
  });

  it("a live arrival stops reading as 'still animating' once its animation window elapses", () => {
    const state = applyStreamEvent(createEmptyGraphState(), { kind: "node", node: makeNode("b") }, 1_000_000);
    expect(isLiveArrival(state, "b", 600, 1_000_000 + 300)).toBe(true);
    expect(isLiveArrival(state, "b", 600, 1_000_000 + 700)).toBe(false);
  });

  it("applyStreamEvent upserts an edge and marks it live too", () => {
    const state = applyStreamEvent(createEmptyGraphState(), {
      kind: "edge",
      edge: { id: "e1", type: "implies", from_id: "a", to_id: "b", derivation: "extracted", confidence: 0.8, is_conflict: false },
    });
    expect(listEdges(state).map((e) => e.id)).toEqual(["e1"]);
    expect(isLiveArrival(state, "e1", 600)).toBe(true);
  });

  it("applying a snapshot after a stream event preserves prior live-arrival bookkeeping", () => {
    const withLiveNode = applyStreamEvent(createEmptyGraphState(), { kind: "node", node: makeNode("b") }, 1_000_000);
    const resnapshotted = applySnapshot(withLiveNode, { nodes: [makeNode("a"), makeNode("b")], edges: [] });
    // "b" still reads as a live arrival even though a later snapshot also
    // happens to contain it — applySnapshot never touches liveArrivedAt.
    expect(isLiveArrival(resnapshotted, "b", 600, 1_000_000)).toBe(true);
  });
});
