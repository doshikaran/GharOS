/**
 * Pure nearest-node hit-testing for canvas click handling — kept dependency
 * and DOM-free so it is unit-testable without a real `<canvas>`.
 */

export interface PositionedNode {
  readonly id: string;
  readonly x?: number;
  readonly y?: number;
}

/**
 * Returns the id of the node closest to `(x, y)` (world/simulation space,
 * already inverse-transformed for any zoom/pan) that is within `radius` of
 * it, or `null` if none qualify. Nodes without a settled position
 * (`x`/`y` still `undefined`, e.g. seeded this frame) are skipped.
 */
export function findNodeAtPoint(
  nodes: readonly PositionedNode[],
  x: number,
  y: number,
  radius: number,
): string | null {
  let closestId: string | null = null;
  let closestDistance = Infinity;

  for (const node of nodes) {
    if (node.x === undefined || node.y === undefined) continue;
    const dx = node.x - x;
    const dy = node.y - y;
    const distance = Math.sqrt(dx * dx + dy * dy);
    if (distance <= radius && distance < closestDistance) {
      closestDistance = distance;
      closestId = node.id;
    }
  }

  return closestId;
}
