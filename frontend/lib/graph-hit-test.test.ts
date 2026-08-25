import { describe, expect, it } from "vitest";
import { findNodeAtPoint } from "./graph-hit-test";

describe("findNodeAtPoint", () => {
  const nodes = [
    { id: "a", x: 0, y: 0 },
    { id: "b", x: 100, y: 0 },
    { id: "c", x: 100, y: 5 },
  ];

  it("returns the id of the node within radius of the point", () => {
    expect(findNodeAtPoint(nodes, 2, 1, 10)).toBe("a");
  });

  it("returns the closest node when multiple are within radius", () => {
    // b=(100,0) is distance 2 from (100,2); c=(100,5) is distance 3 — b wins.
    expect(findNodeAtPoint(nodes, 100, 2, 10)).toBe("b");
  });

  it("returns null when nothing is within radius", () => {
    expect(findNodeAtPoint(nodes, 500, 500, 10)).toBeNull();
  });

  it("skips nodes without a settled position", () => {
    const withUnsettled = [{ id: "unsettled", x: undefined, y: undefined }, ...nodes];
    expect(findNodeAtPoint(withUnsettled, 0, 0, 10)).toBe("a");
  });

  it("returns null against an empty node list", () => {
    expect(findNodeAtPoint([], 0, 0, 10)).toBeNull();
  });
});
