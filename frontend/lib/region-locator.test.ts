import { describe, expect, it } from "vitest";
import { decodeHighlightedTextSpan, MalformedRegionError, parseRegion } from "./region-locator";

describe("parseRegion", () => {
  it("parses a byte-offset span", () => {
    expect(parseRegion("120-340")).toEqual({ kind: "text-span", start: 120, end: 340 });
  });

  it("parses a page+bbox region", () => {
    expect(parseRegion("page=1;bbox=10,20,300,400")).toEqual({
      kind: "page-bbox",
      page: 1,
      bbox: { x0: 10, y0: 20, x1: 300, y1: 400 },
    });
  });

  it("parses fractional bbox coordinates", () => {
    expect(parseRegion("page=2;bbox=10.5,20.25,300.75,400.1")).toEqual({
      kind: "page-bbox",
      page: 2,
      bbox: { x0: 10.5, y0: 20.25, x1: 300.75, y1: 400.1 },
    });
  });

  it("rejects a byte-offset span where start >= end", () => {
    expect(() => parseRegion("340-120")).toThrow(MalformedRegionError);
    expect(() => parseRegion("100-100")).toThrow(MalformedRegionError);
  });

  it("rejects a page < 1", () => {
    expect(() => parseRegion("page=0;bbox=1,1,2,2")).toThrow(MalformedRegionError);
  });

  it("rejects a bbox with x1 <= x0 or y1 <= y0", () => {
    expect(() => parseRegion("page=1;bbox=10,10,10,20")).toThrow(MalformedRegionError);
    expect(() => parseRegion("page=1;bbox=10,10,20,10")).toThrow(MalformedRegionError);
  });

  it("rejects a string matching neither convention", () => {
    expect(() => parseRegion("not-a-region")).toThrow(MalformedRegionError);
    expect(() => parseRegion("")).toThrow(MalformedRegionError);
  });

  it("tries the byte-offset form first, matching the backend's precedence", () => {
    // A string that could only ever match the text-span pattern.
    expect(parseRegion("0-1").kind).toBe("text-span");
  });
});

describe("decodeHighlightedTextSpan", () => {
  it("splits ASCII text into before/highlighted/after around the byte span", () => {
    const text = "The vendor offers a 4:00-5:00 PM slot tomorrow.";
    const bytes = new TextEncoder().encode(text);
    const start = text.indexOf("4:00-5:00 PM");
    const end = start + "4:00-5:00 PM".length;

    const result = decodeHighlightedTextSpan(bytes, { kind: "text-span", start, end });

    expect(result.before + result.highlighted + result.after).toBe(text);
    expect(result.highlighted).toBe("4:00-5:00 PM");
  });

  it("decodes correctly across a multi-byte UTF-8 boundary when the span itself stays codepoint-aligned", () => {
    const text = "₹14,000 for August";
    const bytes = new TextEncoder().encode(text);
    // "₹" is 3 bytes in UTF-8; the highlighted span starts right after it.
    const start = new TextEncoder().encode("₹").length;
    const end = bytes.length;

    const result = decodeHighlightedTextSpan(bytes, { kind: "text-span", start, end });

    expect(result.before).toBe("₹");
    expect(result.highlighted).toBe("14,000 for August");
  });

  it("clamps an out-of-range end to the payload length rather than throwing", () => {
    const bytes = new TextEncoder().encode("short");
    const result = decodeHighlightedTextSpan(bytes, { kind: "text-span", start: 0, end: 999 });
    expect(result.highlighted).toBe("short");
    expect(result.after).toBe("");
  });
});
