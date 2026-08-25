import type { NodeFillMode, NodeGeometry } from "@/lib/graph-visual-encoding";

export interface NodeGeometryIconProps {
  geometry: NodeGeometry;
  fillMode: NodeFillMode;
  /** CSS custom-property name, e.g. "--royal-primary" — used directly as
   * an inline SVG `var(...)` reference (SVG, unlike canvas, participates
   * in the CSS cascade, so no runtime token resolution is needed here). */
  colorToken: string;
  size?: number;
}

const R = 9; // icon-space radius, viewBox is [-12, -12, 24, 24]

function polygonPoints(sides: number, rotation: number, radius: number = R): string {
  const points: string[] = [];
  for (let i = 0; i < sides; i += 1) {
    const angle = rotation + (i * 2 * Math.PI) / sides;
    points.push(`${(radius * Math.cos(angle)).toFixed(2)},${(radius * Math.sin(angle)).toFixed(2)}`);
  }
  return points.join(" ");
}

function starPoints(): string {
  const points: string[] = [];
  const outer = R;
  const inner = R * 0.45;
  for (let i = 0; i < 10; i += 1) {
    const r = i % 2 === 0 ? outer : inner;
    const angle = -Math.PI / 2 + (i * Math.PI) / 5;
    points.push(`${(r * Math.cos(angle)).toFixed(2)},${(r * Math.sin(angle)).toFixed(2)}`);
  }
  return points.join(" ");
}

/**
 * A small SVG glyph approximating one `graph-visual-encoding.ts` node
 * geometry, used by `GraphLegend` and `NodeInspector` so the same
 * type-to-shape convention the canvas draws is legible off-canvas too.
 */
export function NodeGeometryIcon({ geometry, fillMode, colorToken, size = 24 }: NodeGeometryIconProps) {
  const color = `var(${colorToken})`;
  const fill = fillMode === "outline" ? "none" : color;
  const stroke = color;
  const strokeWidth = fillMode === "outline" ? 2 : 1;

  let shape: React.ReactNode;
  switch (geometry) {
    case "circle":
      shape = <circle cx={0} cy={0} r={R} fill={fill} stroke={stroke} strokeWidth={strokeWidth} />;
      break;
    case "diamond":
      shape = <polygon points={polygonPoints(4, 0)} fill={fill} stroke={stroke} strokeWidth={strokeWidth} />;
      break;
    case "square":
      shape = <polygon points={polygonPoints(4, Math.PI / 4)} fill={fill} stroke={stroke} strokeWidth={strokeWidth} />;
      break;
    case "triangle-up":
      shape = <polygon points={polygonPoints(3, -Math.PI / 2)} fill={fill} stroke={stroke} strokeWidth={strokeWidth} />;
      break;
    case "triangle-down":
      shape = <polygon points={polygonPoints(3, Math.PI / 2)} fill={fill} stroke={stroke} strokeWidth={strokeWidth} />;
      break;
    case "pentagon":
      shape = <polygon points={polygonPoints(5, -Math.PI / 2)} fill={fill} stroke={stroke} strokeWidth={strokeWidth} />;
      break;
    case "hexagon":
      shape = <polygon points={polygonPoints(6, 0)} fill={fill} stroke={stroke} strokeWidth={strokeWidth} />;
      break;
    case "star":
      shape = <polygon points={starPoints()} fill={fill} stroke={stroke} strokeWidth={strokeWidth} />;
      break;
    case "rounded-rect":
      shape = <rect x={-R} y={-R} width={R * 2} height={R * 2} rx={4} fill={fill} stroke={stroke} strokeWidth={strokeWidth} />;
      break;
    case "cross":
      shape = (
        <path
          d={`M -3,-9 3,-9 3,-3 9,-3 9,3 3,3 3,9 -3,9 -3,3 -9,3 -9,-3 -3,-3 Z`}
          fill={fill}
          stroke={stroke}
          strokeWidth={strokeWidth}
        />
      );
      break;
    case "x-mark":
      shape = (
        <>
          <line x1={-6} y1={-6} x2={6} y2={6} stroke={stroke} strokeWidth={2.5} />
          <line x1={6} y1={-6} x2={-6} y2={6} stroke={stroke} strokeWidth={2.5} />
        </>
      );
      break;
  }

  return (
    <svg width={size} height={size} viewBox="-12 -12 24 24" aria-hidden="true">
      {shape}
    </svg>
  );
}
