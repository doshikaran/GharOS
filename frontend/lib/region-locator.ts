/**
 * Client-side mirror of `backend/app/persistence/region_resolver.py`'s two
 * region-locator conventions — read in full as the source of truth.
 * `SourceRegionViewer` uses this to decide how to highlight a node's
 * provenance region against its raw document bytes.
 *
 * **Convention 1 — byte-offset span**, for text-shaped documents:
 * `"<start>-<end>"`, zero-indexed, half-open against the raw payload bytes
 * (`payload[start:end]`, Python slice semantics).
 *
 * **Convention 2 — page + bounding box**, for image/scan-shaped documents:
 * `"page=<n>;bbox=<x0>,<y0>,<x1>,<y1>"`, 1-indexed page, pixel-unit bbox.
 *
 * Detection tries the byte-offset form first (a bare `\d+-\d+`), falling
 * back to the `page=...;bbox=...` form — same precedence as the backend.
 */

const TEXT_SPAN_PATTERN = /^(\d+)-(\d+)$/;
const PAGE_BBOX_PATTERN =
  /^page=(\d+);bbox=(\d+(?:\.\d+)?),(\d+(?:\.\d+)?),(\d+(?:\.\d+)?),(\d+(?:\.\d+)?)$/;

export interface TextSpanRegion {
  readonly kind: "text-span";
  readonly start: number;
  readonly end: number;
}

export interface BoundingBox {
  readonly x0: number;
  readonly y0: number;
  readonly x1: number;
  readonly y1: number;
}

export interface PageBoundingBoxRegion {
  readonly kind: "page-bbox";
  readonly page: number;
  readonly bbox: BoundingBox;
}

export type RegionLocator = TextSpanRegion | PageBoundingBoxRegion;

export class MalformedRegionError extends Error {
  constructor(region: string, reason: string) {
    super(`Malformed region ${JSON.stringify(region)}: ${reason}`);
    this.name = "MalformedRegionError";
  }
}

/**
 * Parses a `region` locator string against the two supported conventions.
 *
 * @throws {MalformedRegionError} `region` matches neither convention, or
 *   matches one syntactically but fails its own validity rule (start >=
 *   end; x1 <= x0 or y1 <= y0; page < 1).
 */
export function parseRegion(region: string): RegionLocator {
  const textMatch = TEXT_SPAN_PATTERN.exec(region);
  if (textMatch) {
    const start = Number(textMatch[1]);
    const end = Number(textMatch[2]);
    if (start >= end) {
      throw new MalformedRegionError(region, `start (${start}) must be < end (${end})`);
    }
    return { kind: "text-span", start, end };
  }

  const bboxMatch = PAGE_BBOX_PATTERN.exec(region);
  if (bboxMatch) {
    const page = Number(bboxMatch[1]);
    if (page < 1) {
      throw new MalformedRegionError(region, `page must be >= 1, got ${page}`);
    }
    const [x0, y0, x1, y1] = [bboxMatch[2], bboxMatch[3], bboxMatch[4], bboxMatch[5]].map(Number) as [
      number,
      number,
      number,
      number,
    ];
    if (x1 <= x0 || y1 <= y0) {
      throw new MalformedRegionError(
        region,
        `bbox must have x1 > x0 and y1 > y0, got (${x0},${y0},${x1},${y1})`,
      );
    }
    return { kind: "page-bbox", page, bbox: { x0, y0, x1, y1 } };
  }

  throw new MalformedRegionError(
    region,
    "matches neither the 'start-end' byte-offset convention nor the 'page=N;bbox=x0,y0,x1,y1' convention",
  );
}

/**
 * Decodes a byte-offset span into `{ before, highlighted, after }` text
 * pieces from raw document bytes. Slices at byte boundaries and decodes
 * each contiguous range independently (rather than decoding the whole
 * payload once and indexing into the resulting UTF-16 string), which stays
 * correct for multi-byte UTF-8 as long as `start`/`end` fall on codepoint
 * boundaries — the same assumption the backend's byte-offset convention
 * already makes of every extraction agent that produces one.
 */
export function decodeHighlightedTextSpan(
  bytes: Uint8Array,
  region: TextSpanRegion,
): { before: string; highlighted: string; after: string } {
  const decoder = new TextDecoder("utf-8", { fatal: false });
  const start = Math.max(0, Math.min(region.start, bytes.length));
  const end = Math.max(start, Math.min(region.end, bytes.length));
  return {
    before: decoder.decode(bytes.slice(0, start)),
    highlighted: decoder.decode(bytes.slice(start, end)),
    after: decoder.decode(bytes.slice(end)),
  };
}
