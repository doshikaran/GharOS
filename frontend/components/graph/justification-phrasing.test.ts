import { describe, expect, it } from "vitest";
import { connectorPhrase } from "./justification-phrasing";

describe("connectorPhrase", () => {
  it("uses the passive form when the child step is the edge's from_id", () => {
    // email --implies--> obligation; rendering the obligation (parent)
    // above and the email (child, from_id) below reads "implied by".
    expect(connectorPhrase("implies", true)).toBe("implied by");
  });

  it("uses the active form when the child step is the edge's to_id", () => {
    // obligation --contains--> line_item; rendering obligation (parent)
    // above and line_item (child, to_id) below reads "contains".
    expect(connectorPhrase("contains", false)).toBe("contains");
  });

  it("falls back to a spaced, honestly-labelled form for an unrecognised edge type", () => {
    expect(connectorPhrase("some_future_edge_type", false)).toBe("some future edge type");
    expect(connectorPhrase("some_future_edge_type", true)).toBe("some future edge type (reverse)");
  });

  it("has a phrase pair for every EdgeType value referenced in the household graph model", () => {
    const knownTypes = [
      "states",
      "implies",
      "owned_by",
      "benefits",
      "conflicts_with",
      "violates",
      "depends_on",
      "supersedes",
      "completes_into",
      "belongs_to",
      "owed_to",
      "paid_for",
      "contains",
      "supports",
      "opposes",
      "grounded_in",
      "resolved_as",
      "conceded_by",
      "predicted_by",
      "constrains",
      "booked_with",
      "learned_from",
      "line_item_of",
      "discharges",
      "verifies",
      "contradicts",
      "absent_from",
      "substitutes",
      "evidences_effort",
      "covers",
      "acts_on",
      "authorizes",
      "approved_by",
    ];
    for (const type of knownTypes) {
      expect(connectorPhrase(type, false)).not.toContain("(reverse)");
    }
  });
});
