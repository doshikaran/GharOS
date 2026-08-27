import { describe, expect, it } from "vitest";
import type { GraphNode } from "./graph-types";
import { buildLiveCostMatrix, findCell } from "./fair-allocator-matrix";

function personNode(id: string, displayName: string): GraphNode {
  return {
    id,
    type: "PERSON",
    label: displayName,
    derivation: "extracted",
    confidence: 0.9,
    source_document_id: "doc-school-whatsapp",
    region: "header",
    created_at: "2026-08-22T09:00:00Z",
    fields: { display_name: displayName },
  };
}

function obligationNode(id: string, title: string, status = "assigned"): GraphNode {
  return {
    id,
    type: "OBLIGATION",
    label: title,
    derivation: "extracted",
    confidence: 0.9,
    source_document_id: "doc-school-whatsapp",
    region: "msg-9",
    created_at: "2026-08-22T09:00:00Z",
    fields: { title, status },
  };
}

function valuationNode(id: string, personId: string, costs: Record<string, number>): GraphNode {
  return {
    id,
    type: "VALUATION_PROFILE",
    label: "mixed valuation",
    derivation: "inferred",
    confidence: 0.7,
    source_document_id: "doc-school-whatsapp",
    region: "derived",
    created_at: "2026-08-22T09:00:00Z",
    fields: { person_id: personId, costs, elicitation_method: "mixed" },
  };
}

const priya = personNode("person-priya", "Priya");
const maya = personNode("person-maya", "Maya");
const pickup = obligationNode("obligation-pickup-aarav", "Pick up Aarav from school");
const groceries = obligationNode("obligation-weekly-groceries", "Buy weekly groceries");
const superseded = obligationNode("obligation-pay-maintenance", "Pay society maintenance", "superseded");
const priyaValuation = valuationNode("valuation-priya", "person-priya", {
  "obligation-pickup-aarav": 3.0,
  "obligation-weekly-groceries": 1.0,
});

describe("buildLiveCostMatrix", () => {
  it("includes every PERSON and every non-superseded OBLIGATION", () => {
    const matrix = buildLiveCostMatrix([priya, maya, pickup, groceries, superseded, priyaValuation]);
    expect(matrix.people.map((p) => p.personId).sort()).toEqual(["person-maya", "person-priya"]);
    expect(matrix.tasks.map((t) => t.taskId)).not.toContain(superseded.id);
    expect(matrix.tasks.map((t) => t.taskId).sort()).toEqual(
      ["obligation-pickup-aarav", "obligation-weekly-groceries"].sort(),
    );
  });

  it("renders a live-priced cell with its real cost and elicitation method", () => {
    const matrix = buildLiveCostMatrix([priya, maya, pickup, groceries, priyaValuation]);
    const cell = findCell(matrix, "person-priya", "obligation-weekly-groceries");
    expect(cell?.source).toBe("live");
    expect(cell?.cost).toBe(1.0);
    expect(cell?.elicitationMethod).toBe("mixed");
  });

  it("renders a person never priced for a task as 'not_asked' with cost null, never a fabricated 0", () => {
    const matrix = buildLiveCostMatrix([priya, maya, pickup, groceries, priyaValuation]);
    const mayaOnPickup = findCell(matrix, "person-maya", "obligation-pickup-aarav");
    expect(mayaOnPickup?.source).toBe("not_asked");
    expect(mayaOnPickup?.cost).toBeNull();
    expect(mayaOnPickup?.elicitationMethod).toBeNull();
  });

  it("renders a person's own genuinely-unpriced task as 'not_asked', distinct from their priced tasks", () => {
    // Priya has a live VALUATION_PROFILE but it never mentions a third
    // hypothetical task — that pair must still read as "not asked".
    const otherTask = obligationNode("obligation-renew-prescription", "Renew Dadi's prescription");
    const matrix = buildLiveCostMatrix([priya, maya, pickup, groceries, otherTask, priyaValuation]);
    const cell = findCell(matrix, "person-priya", "obligation-renew-prescription");
    expect(cell?.source).toBe("not_asked");
    expect(cell?.cost).toBeNull();
  });

  it("produces exactly people.length * tasks.length cells", () => {
    const matrix = buildLiveCostMatrix([priya, maya, pickup, groceries, priyaValuation]);
    expect(matrix.cells).toHaveLength(matrix.people.length * matrix.tasks.length);
  });

  it("records the VALUATION_PROFILE node id behind a person's live cells", () => {
    const matrix = buildLiveCostMatrix([priya, maya, pickup, groceries, priyaValuation]);
    expect(matrix.valuationProfileIdByPerson["person-priya"]).toBe("valuation-priya");
    expect(matrix.valuationProfileIdByPerson["person-maya"]).toBeUndefined();
  });

  it("is stable/deterministic regardless of input node order", () => {
    const forward = buildLiveCostMatrix([priya, maya, pickup, groceries, priyaValuation]);
    const shuffled = buildLiveCostMatrix([priyaValuation, groceries, maya, pickup, priya]);
    expect(shuffled.people).toEqual(forward.people);
    expect(shuffled.tasks).toEqual(forward.tasks);
    expect(shuffled.cells).toEqual(forward.cells);
  });

  it("returns an empty matrix (no error) when there are no people or tasks yet", () => {
    const matrix = buildLiveCostMatrix([]);
    expect(matrix.people).toEqual([]);
    expect(matrix.tasks).toEqual([]);
    expect(matrix.cells).toEqual([]);
  });
});
